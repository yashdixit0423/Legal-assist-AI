import {
  forwardRef,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
} from "react";
import { ArrowUp, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** The backend's limit on `question`. */
export const MAX_QUESTION_CHARS = 2000;
const COUNTER_FROM = 1800;

export interface ChatComposerHandle {
  focus: () => void;
}

/**
 * The chat input, built on the same `ask-composer` surface as Ask.
 *
 * Enter sends and Shift+Enter adds a line. While an answer streams, Send
 * becomes Stop. The value is owned by the page, so a suggested prompt or a
 * voice transcript can fill it without ever sending it.
 */
export const ChatComposer = forwardRef<
  ChatComposerHandle,
  {
    value: string;
    onChange: (value: string) => void;
    onSend: () => void;
    onStop: () => void;
    streaming: boolean;
    disabled?: boolean;
    disabledHint?: React.ReactNode;
    /** Left of the toolbar: the attach button. */
    leading?: React.ReactNode;
    /** Right of the toolbar, before Send: the mic. */
    trailing?: React.ReactNode;
    /** Above the textarea: attachment chips. */
    header?: React.ReactNode;
    /** Holds Send without disabling typing, e.g. while a document uploads. */
    sendBlocked?: boolean;
  }
>(function ChatComposer(
  {
    value,
    onChange,
    onSend,
    onStop,
    streaming,
    disabled = false,
    disabledHint,
    leading,
    trailing,
    header,
    sendBlocked = false,
  },
  ref,
) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => textarea.current?.focus() }));

  // Grow with the text, up to about 40% of the viewport.
  useLayoutEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    const max = Math.round(window.innerHeight * 0.4);
    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
    el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
  }, [value]);

  const canSend =
    value.trim().length >= 3 && !streaming && !disabled && !sendBlocked;

  return (
    <div
      className={cn(
        "ask-composer !p-3 sm:!p-4",
        disabled && "ask-composer-disabled",
      )}
    >
      {header}
      <label htmlFor="chat-input" className="sr-only">
        Message the Legal AI Assistant
      </label>
      <textarea
        id="chat-input"
        ref={textarea}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            if (canSend) onSend();
          }
        }}
        rows={1}
        maxLength={MAX_QUESTION_CHARS}
        disabled={disabled}
        placeholder="Ask about the indexed Acts, or follow up on an answer…"
        className="block max-h-[40vh] w-full resize-none bg-transparent px-1 text-[15px] leading-relaxed text-[hsl(var(--ink))] outline-none placeholder:text-[hsl(var(--ink-4))]"
      />
      <div className="mt-2 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">{leading}</div>
        <div className="flex items-center gap-2">
          {value.length >= COUNTER_FROM && (
            <span
              className={cn(
                "text-[11px] tabular-nums text-[hsl(var(--ink-4))]",
                value.length >= MAX_QUESTION_CHARS &&
                  "font-semibold text-[hsl(var(--ink-2))]",
              )}
            >
              {value.length.toLocaleString()} /{" "}
              {MAX_QUESTION_CHARS.toLocaleString()}
            </span>
          )}
          {disabled && disabledHint}
          {trailing}
          {streaming ? (
            <Button
              type="button"
              onClick={onStop}
              size="sm"
              variant="outline"
              className="gap-1.5"
              aria-label="Stop generating"
            >
              <Square size={12} className="fill-current" /> Stop
            </Button>
          ) : (
            <Button
              type="button"
              onClick={onSend}
              disabled={!canSend}
              size="sm"
              className="gap-1.5"
              aria-label="Send message"
            >
              Send <ArrowUp size={14} />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
});
