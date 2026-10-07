import { AlertCircle, Check, FileText, LoaderCircle, X } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { displayName, formatBytes } from "@/lib/chat/files";
import type { ChatAttachment } from "@/hooks/use-chat";
import { cn } from "@/lib/utils";

/** Opens the user's own file from memory; there is no built-in viewer. */
function openLocally(file: File) {
  const url = URL.createObjectURL(file);
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function AttachmentPreview({
  attachment,
  onRemove,
  compact = false,
}: {
  attachment: ChatAttachment;
  /** Omitted on a sent message, where the chip is a record, not a control. */
  onRemove?: () => void;
  compact?: boolean;
}) {
  const name = displayName(attachment.name, compact ? 28 : 36);
  const canOpen = attachment.file !== undefined && attachment.kind !== "docx";

  return (
    <div
      className={cn(
        "flex min-w-0 max-w-full items-center gap-2.5 rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas))] px-2.5 py-1.5",
        attachment.status === "error" && "border-[hsl(var(--line-strong))]",
      )}
    >
      <span className="feature-icon h-7 w-7 shrink-0 rounded-lg">
        <FileText size={14} />
      </span>
      <div className="min-w-0 flex-1">
        {canOpen ? (
          <button
            type="button"
            onClick={() => attachment.file && openLocally(attachment.file)}
            className="block max-w-full truncate text-left text-[12.5px] font-semibold text-[hsl(var(--ink))] hover:underline"
            title={`Open ${attachment.name} in a new tab`}
          >
            {name}
          </button>
        ) : (
          <span
            className="block truncate text-[12.5px] font-semibold text-[hsl(var(--ink))]"
            title={attachment.name}
          >
            {name}
          </span>
        )}
        <div className="flex items-center gap-1.5 text-[11px] text-[hsl(var(--ink-3))]">
          <span className="uppercase">
            {attachment.name.split(".").pop()?.slice(0, 5) || "file"}
          </span>
          <span>· {formatBytes(attachment.size)}</span>
          {attachment.pages ? <span>· {attachment.pages} pp.</span> : null}
          {attachment.status === "uploading" && (
            <span className="inline-flex items-center gap-1">
              · <LoaderCircle size={10} className="animate-spin" /> Reading
            </span>
          )}
          {attachment.status === "ready" && !compact && (
            <span className="inline-flex items-center gap-1 text-[hsl(var(--brand))]">
              · <Check size={11} /> Ready
            </span>
          )}
        </div>
        {attachment.status === "uploading" && (
          <Progress
            value={attachment.progress}
            className="mt-1 h-1"
            aria-label={`Uploading ${attachment.name}`}
          />
        )}
        {attachment.status === "error" && attachment.error && (
          <p className="mt-0.5 flex items-center gap-1 text-[11px] text-[hsl(var(--ink-2))]">
            <AlertCircle size={11} /> {attachment.error}
          </p>
        )}
      </div>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="icon-button h-7 w-7 shrink-0"
          aria-label={`Remove ${attachment.name}`}
        >
          <X size={13} />
        </button>
      )}
    </div>
  );
}
