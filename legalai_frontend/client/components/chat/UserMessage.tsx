import type { ChatMessage } from "@/hooks/use-chat";
import { AttachmentPreview } from "./AttachmentPreview";

/** Compact and right-aligned: the question frames the answer, it is not the answer. */
export function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <div className="flex flex-col items-end gap-1.5">
      {message.attachments && message.attachments.length > 0 && (
        <div className="flex max-w-[85%] flex-wrap justify-end gap-1.5">
          {message.attachments.map((attachment) => (
            <AttachmentPreview
              key={attachment.id}
              attachment={attachment}
              compact
            />
          ))}
        </div>
      )}
      <div className="max-w-[85%] rounded-[var(--radius)] border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-4 py-2.5 text-[14px] leading-relaxed text-[hsl(var(--ink))]">
        <p className="whitespace-pre-wrap break-words">{message.text}</p>
      </div>
    </div>
  );
}
