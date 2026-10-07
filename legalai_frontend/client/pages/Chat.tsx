import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import {
  useChat,
  type ChatAttachment,
  type ChatMessage,
} from "@/hooks/use-chat";
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
  const announcement = useMemo(
    () => answerStatus(chat.messages),
    [chat.messages],
  );
  const uploadAnnouncement = useMemo(
    () => attachmentStatus(chat.attachments),
    [chat.attachments],
  );
  const bottomBar = useRef<HTMLDivElement>(null);

  // On a phone the on-screen keyboard shrinks the visual viewport without
  // resizing the layout viewport, which can leave the composer underneath it.
  // Keep it in view while the user is typing.
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const keepVisible = () => {
      if (document.activeElement?.id === "chat-input") {
        bottomBar.current?.scrollIntoView({ block: "end" });
      }
    };
    viewport.addEventListener("resize", keepVisible);
    return () => viewport.removeEventListener("resize", keepVisible);
  }, []);

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

      <div
        ref={bottomBar}
        className="pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2"
      >
        {/* Polite status for screen readers: the streamed text itself is
            muted while it streams (aria-busy), so progress is announced here. */}
        <p className="sr-only" role="status" aria-live="polite">
          {announcement}
        </p>
        <p className="sr-only" aria-live="polite">
          {uploadAnnouncement}
        </p>
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
                <p className="text-[11px] text-[hsl(var(--ink-3))]">
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
          <p className="text-[11px] text-[hsl(var(--ink-3))]">
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

/** What a screen reader should hear about the latest answer, in plain words. */
function answerStatus(messages: ChatMessage[]): string {
  const last = [...messages].reverse().find((m) => m.role === "assistant");
  if (!last) return "";
  if (last.status === "streaming") {
    if (last.invalidating) return "Correcting the answer.";
    if (last.phase === "searching") return "Searching the indexed Acts…";
    if (last.phase === "preparing") return "Preparing answer…";
    return "Writing the answer…";
  }
  if (last.status === "stopped") return "Stopped.";
  if (last.status === "error") return "The request did not complete.";
  if (last.abstain) return "No provision in the indexed corpus answers this.";
  return "Answer ready.";
}

function attachmentStatus(attachments: ChatAttachment[]): string {
  const last = attachments[attachments.length - 1];
  if (!last) return "";
  if (last.status === "uploading") return `Reading ${last.name}…`;
  if (last.status === "ready") return `${last.name} is attached.`;
  return `${last.name} couldn't be attached. ${last.error ?? ""}`;
}
