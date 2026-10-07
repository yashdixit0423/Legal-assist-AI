import type { ChatMessage } from "@/hooks/use-chat";

/** Compact and right-aligned: the question frames the answer, it is not the answer. */
export function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-[var(--radius)] border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-4 py-2.5 text-[14px] leading-relaxed text-[hsl(var(--ink))]">
        <p className="whitespace-pre-wrap break-words">{message.text}</p>
      </div>
    </div>
  );
}
