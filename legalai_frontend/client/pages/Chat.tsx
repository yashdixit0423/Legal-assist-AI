import { useCallback, useEffect, useRef, useState } from "react";
import { LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";
import {
  ChatComposer,
  type ChatComposerHandle,
} from "@/components/chat/ChatComposer";
import { AttachmentButton } from "@/components/chat/AttachmentButton";
import { AttachmentPreview } from "@/components/chat/AttachmentPreview";
import { ChatEmptyState } from "@/components/chat/ChatEmptyState";
import { DocumentDropZone } from "@/components/chat/DocumentDropZone";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { ChatMessageList } from "@/components/chat/ChatMessageList";
import { NewChatDialog } from "@/components/chat/NewChatDialog";
import { VoiceInputButton } from "@/components/chat/VoiceInputButton";
import {
  DocumentOpenContext,
  SourceOpenContext,
  SourceOverlay,
  SourcePanel,
  usePanelMode,
  type SourceTarget,
} from "@/components/chat/SourcePanel";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { useAuth, useRateLimit } from "@/hooks/use-auth";
import { useChat } from "@/hooks/use-chat";
import type { DocumentSourceBlock } from "@/lib/api/types";
import { DOCUMENTS_ENABLED, MAX_FILES } from "@/lib/chat/files";

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
  const [target, setTarget] = useState<SourceTarget | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const mode = usePanelMode();

  const exhausted = rateLimit !== null && rateLimit.remaining <= 0;

  const send = () => {
    // A document still being read would silently miss this question.
    if (draft.trim().length < 3 || chat.streaming || chat.uploading) return;
    chat.send(draft);
    setDraft("");
  };

  const fill = (prompt: string) => {
    setDraft(prompt);
    composer.current?.focus();
  };

  // A citation opens its section beside the conversation, never instead of it:
  // navigating away would discard the in-memory conversation.
  const show = useCallback((next: SourceTarget) => {
    if (document.activeElement instanceof HTMLElement) {
      opener.current = document.activeElement;
    }
    setTarget(next);
  }, []);
  const openSource = useCallback(
    (sectionId: number) => show({ kind: "section", sectionId }),
    [show],
  );
  const openDocument = useCallback(
    (source: DocumentSourceBlock) => show({ kind: "document", source }),
    [show],
  );

  const returnFocus = useCallback(() => {
    const target = opener.current;
    if (target?.isConnected) target.focus();
    else composer.current?.focus();
  }, []);

  const closeSource = useCallback(() => {
    setTarget(null);
    if (mode === "split") requestAnimationFrame(returnFocus);
  }, [mode, returnFocus]);

  // The split panel has no dialog to catch Escape, so the page does.
  useEffect(() => {
    if (mode !== "split" || target === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) closeSource();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mode, target, closeSource]);

  const startOver = () => {
    if (chat.messages.length === 0) return;
    setConfirmOpen(true);
  };

  const conversation = (
    <div className="mx-auto flex min-h-0 w-full max-w-[840px] flex-1 flex-col px-5 sm:px-8">
      <ChatHeader onNewChat={startOver} canReset={chat.messages.length > 0} />

      <DocumentDropZone
        onFiles={chat.attach}
        disabled={!DOCUMENTS_ENABLED || !signedIn}
      >
        <ChatMessageList
          messages={chat.messages}
          streaming={chat.streaming}
          onRegenerate={chat.regenerate}
          empty={<ChatEmptyState onPick={signedIn ? fill : undefined} />}
        />
      </DocumentDropZone>

      <div className="pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2">
        <ChatComposer
          ref={composer}
          value={draft}
          onChange={setDraft}
          onSend={send}
          onStop={chat.stop}
          streaming={chat.streaming}
          sendBlocked={chat.uploading}
          disabled={!signedIn || exhausted}
          trailing={
            signedIn && !exhausted ? (
              <VoiceInputButton
                value={draft}
                onChange={setDraft}
                disabled={chat.streaming}
              />
            ) : undefined
          }
          leading={
            DOCUMENTS_ENABLED && signedIn ? (
              <AttachmentButton
                onFiles={chat.attach}
                disabled={
                  chat.attachments.filter((a) => a.status !== "error").length >=
                  MAX_FILES
                }
              />
            ) : undefined
          }
          header={
            DOCUMENTS_ENABLED && chat.attachments.length > 0 ? (
              <div className="mb-2 space-y-1.5 border-b border-[hsl(var(--line))] pb-2">
                <div className="flex flex-wrap gap-1.5">
                  {chat.attachments.map((attachment) => (
                    <AttachmentPreview
                      key={attachment.id}
                      attachment={attachment}
                      onRemove={() => chat.detach(attachment.id)}
                    />
                  ))}
                </div>
                <p className="text-[11px] text-[hsl(var(--ink-4))]">
                  Documents are processed temporarily and not stored.
                </p>
              </div>
            ) : undefined
          }
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
        <DocumentOpenContext.Provider value={openDocument}>
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
                <div className="flex h-full min-h-0 flex-col">
                  {conversation}
                </div>
              </ResizablePanel>
              {target !== null && (
                <>
                  <ResizableHandle withHandle />
                  <ResizablePanel
                    id="source"
                    order={2}
                    defaultSize={40}
                    minSize={25}
                  >
                    <SourcePanel
                      target={target}
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
                target={target}
                onClose={() => setTarget(null)}
                returnFocus={returnFocus}
              />
            </>
          )}
        </DocumentOpenContext.Provider>
      </SourceOpenContext.Provider>

      <NewChatDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onConfirm={() => {
          chat.reset();
          setDraft("");
          setTarget(null);
        }}
        onClosed={() => composer.current?.focus()}
      />
    </LegalAssistLayout>
  );
}
