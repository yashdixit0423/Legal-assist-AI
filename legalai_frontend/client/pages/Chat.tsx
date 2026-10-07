import { useRef, useState } from "react";
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
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
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

  const startOver = () => {
    if (chat.messages.length === 0) return;
    setConfirmOpen(true);
  };

  return (
    <LegalAssistLayout variant="app">
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
              Informational assistance, not legal advice. Verify important
              matters with a qualified professional.
            </p>
            {rateLimit && signedIn && (
              <p className="text-[11px] text-[hsl(var(--ink-4))]">
                {Math.max(0, rateLimit.remaining)} of {rateLimit.limit}{" "}
                questions left this hour
              </p>
            )}
          </div>
        </div>
      </div>

      <NewChatDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onConfirm={() => {
          chat.reset();
          setDraft("");
        }}
        onClosed={() => composer.current?.focus()}
      />
    </LegalAssistLayout>
  );
}
