import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { ArrowDown } from "lucide-react";
import type { ChatMessage } from "@/hooks/use-chat";
import { AssistantMessage } from "./AssistantMessage";
import { UserMessage } from "./UserMessage";

/** Within this many pixels of the end counts as "following along". */
const BOTTOM_SLACK = 80;

/**
 * The conversation's scroll container.
 *
 * It follows a streaming answer only while the reader is already at the
 * bottom; scrolling up to re-read something stops the jump, and a button
 * offers the way back.
 */
export function ChatMessageList({
  messages,
  streaming,
  onRegenerate,
  empty,
}: {
  messages: ChatMessage[];
  streaming: boolean;
  onRegenerate: (id: string) => void;
  empty: React.ReactNode;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const atBottomRef = useRef(true);

  const onScroll = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    const near =
      el.scrollHeight - el.scrollTop - el.clientHeight < BOTTOM_SLACK;
    atBottomRef.current = near;
    setAtBottom(near);
  }, []);

  const scrollToEnd = useCallback((behavior: ScrollBehavior = "smooth") => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  // A new question always brings the reader down to it.
  const count = messages.length;
  useEffect(() => {
    atBottomRef.current = true;
    setAtBottom(true);
    if (count > 0) scrollToEnd("smooth");
  }, [count, scrollToEnd]);

  // Streamed text keeps the view pinned only when already pinned.
  useLayoutEffect(() => {
    if (atBottomRef.current) scrollToEnd("auto");
    else onScroll();
  }, [messages, scrollToEnd, onScroll]);

  const lastAssistant = [...messages]
    .reverse()
    .find((m) => m.role === "assistant");

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scroller}
        onScroll={onScroll}
        className="h-full overflow-y-auto overscroll-contain"
      >
        {messages.length === 0 ? (
          empty
        ) : (
          <div
            role="log"
            aria-live="polite"
            aria-busy={streaming}
            aria-label="Conversation"
            className="space-y-6 py-6"
          >
            {messages.map((message) =>
              message.role === "user" ? (
                <UserMessage key={message.id} message={message} />
              ) : (
                <AssistantMessage
                  key={message.id}
                  message={message}
                  isLatest={message.id === lastAssistant?.id}
                  onRegenerate={() => onRegenerate(message.id)}
                />
              ),
            )}
          </div>
        )}
      </div>
      {!atBottom && messages.length > 0 && (
        <button
          type="button"
          onClick={() => scrollToEnd()}
          className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 py-1.5 text-[12px] font-semibold text-[hsl(var(--ink-2))] shadow-sm transition-colors hover:border-[hsl(var(--brand))] hover:text-[hsl(var(--brand))]"
        >
          <ArrowDown size={13} /> Jump to latest
        </button>
      )}
    </div>
  );
}
