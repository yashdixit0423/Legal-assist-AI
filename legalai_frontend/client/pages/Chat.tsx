import { useCallback, useEffect, useRef, useState } from "react";
import { LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";
import {
  ChatComposer,
  type ChatComposerHandle,
} from "@/components/chat/ChatComposer";
import { ChatEmptyState } from "@/components/chat/ChatEmptyState";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { ChatMessageList } from "@/components/chat/ChatMessageList";
import { NewChatDialog } from "@/components/chat/NewChatDialog";
import {
  SourceOpenContext,
  SourceOverlay,
  SourcePanel,
  usePanelMode,
} from "@/components/chat/SourcePanel";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { useAuth, useRateLimit } from "@/hooks/use-auth";
import { useChat } from "@/hooks/use-chat";

/**
 * Chat: a multi-turn conversation over the unchanged `/v1/ask` pipeline.
 *
 * The conversation lives in memory only (see `useChat`). Sign-in and the
 * hourly limit are Ask's, shared: the same pipeline spends the same key.
 */
export default function Chat() {
  const { signedIn } = useAuth();
  const rateLimit = useRateLimit("/v1/ask");
  const chat = useChat();
  const [draft, setDraft] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const composer = useRef<ChatComposerHandle>(null);
  const [sourceId, setSourceId] = useState<number | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const mode = usePanelMode();

  const exhausted = rateLimit !== null && rateLimit.remaining <= 0;

  const send = () => {
    if (draft.trim().length < 3 || chat.streaming) return;
    chat.send(draft);
    setDraft("");
  };

  const fill = (prompt: string) => {
    setDraft(prompt);
    composer.current?.focus();
  };

  // A citation opens its section beside the conversation, never instead of it:
  // navigating away would discard the in-memory conversation.
  const openSource = useCallback((sectionId: number) => {
    if (document.activeElement instanceof HTMLElement) {
      opener.current = document.activeElement;
    }
    setSourceId(sectionId);
  }, []);

  const returnFocus = useCallback(() => {
    const target = opener.current;
    if (target?.isConnected) target.focus();
    else composer.current?.focus();
  }, []);

  const closeSource = useCallback(() => {
    setSourceId(null);
    if (mode === "split") requestAnimationFrame(returnFocus);
  }, [mode, returnFocus]);

  // The split panel has no dialog to catch Escape, so the page does.
  useEffect(() => {
    if (mode !== "split" || sourceId === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) closeSource();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mode, sourceId, closeSource]);

  const startOver = () => {
    if (chat.messages.length === 0) return;
    setConfirmOpen(true);
  };

  const conversation = (
    <div className="mx-auto flex min-h-0 w-full max-w-[840px] flex-1 flex-col px-5 sm:px-8">
      <ChatHeader onNewChat={startOver} canReset={chat.messages.length > 0} />

      <ChatMessageList
        messages={chat.messages}
        streaming={chat.streaming}
        onRegenerate={chat.regenerate}
        empty={<ChatEmptyState onPick={signedIn ? fill : undefined} />}
      />

      <div className="pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2">
        <ChatComposer
          ref={composer}
          value={draft}
          onChange={setDraft}
          onSend={send}
          onStop={chat.stop}
          streaming={chat.streaming}
          disabled={!signedIn || exhausted}
          disabledHint={
            !signedIn ? (
              <Link
                to="/login"
                className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[hsl(var(--brand))] hover:underline"
              >
                <LockKeyhole size={13} /> Sign in to chat
              </Link>
            ) : (
              <span className="text-[12px] text-[hsl(var(--ink-3))]">
                Hourly limit reached — resets in{" "}
                {Math.ceil((rateLimit?.resetAfter ?? 0) / 60)} min
              </span>
            )
          }
        />
        <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-0.5">
          <p className="text-[11px] text-[hsl(var(--ink-4))]">
            Informational assistance, not legal advice. Verify important matters
            with a qualified professional.
          </p>
          {rateLimit && signedIn && (
            <p className="text-[11px] text-[hsl(var(--ink-4))]">
              {Math.max(0, rateLimit.remaining)} of {rateLimit.limit} questions
              left this hour
            </p>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <LegalAssistLayout variant="app">
      <SourceOpenContext.Provider value={openSource}>
        {mode === "split" ? (
          <ResizablePanelGroup
            direction="horizontal"
            autoSaveId="legaledge.chat.split"
            className="min-h-0 flex-1"
          >
            <ResizablePanel
              id="conversation"
              order={1}
              defaultSize={60}
              minSize={40}
            >
              <div className="flex h-full min-h-0 flex-col">{conversation}</div>
            </ResizablePanel>
            {sourceId !== null && (
              <>
                <ResizableHandle withHandle />
                <ResizablePanel
                  id="source"
                  order={2}
                  defaultSize={40}
                  minSize={25}
                >
                  <SourcePanel
                    sectionId={sourceId}
                    onClose={closeSource}
                    className="bg-[hsl(var(--canvas-2)/.5)]"
                  />
                </ResizablePanel>
              </>
            )}
          </ResizablePanelGroup>
        ) : (
          <>
            {conversation}
            <SourceOverlay
              mode={mode}
              sectionId={sourceId}
              onClose={() => setSourceId(null)}
              returnFocus={returnFocus}
            />
          </>
        )}
      </SourceOpenContext.Provider>

      <NewChatDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onConfirm={() => {
          chat.reset();
          setDraft("");
          setSourceId(null);
        }}
        onClosed={() => composer.current?.focus()}
      />
    </LegalAssistLayout>
  );
}
