import { useEffect, useState } from "react";
import { Check, Copy, RotateCcw } from "lucide-react";
import { shortStatute } from "@/components/CitationChip";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ChatMessage } from "@/hooks/use-chat";

/**
 * Citation markers are internal ids; a pasted answer should name the
 * provision instead, e.g. "(Registration Act 1908 · s. 17)".
 */
export function plainText(message: ChatMessage): string {
  const byId = new Map(message.sources.map((s) => [s.citation_id, s]));
  return message.text.replace(/\[([^[\]]*)\]/g, (whole, inner: string) => {
    const ids = inner.match(/\bS\d{1,12}\b/g);
    if (!ids) return whole;
    const labels = ids.map((id) => {
      const source = byId.get(id);
      return source
        ? `${shortStatute(source.statute)} · s. ${source.section_no}`
        : id;
    });
    return `(${labels.join("; ")})`;
  });
}

export function MessageActions({
  message,
  onRegenerate,
}: {
  message: ChatMessage;
  /** Only the latest answer can be regenerated; later turns depend on it. */
  onRegenerate?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(plainText(message));
      setCopied(true);
    } catch {
      /* clipboard refused (insecure context or permission); nothing to undo */
    }
  };

  return (
    <div className="flex items-center gap-1.5">
      {message.text && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={copy}
              className="icon-button h-8 w-8"
              aria-label={copied ? "Copied" : "Copy answer"}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </TooltipTrigger>
          <TooltipContent>{copied ? "Copied" : "Copy"}</TooltipContent>
        </Tooltip>
      )}
      {onRegenerate && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={onRegenerate}
              className="icon-button h-8 w-8"
              aria-label="Regenerate answer"
            >
              <RotateCcw size={14} />
            </button>
          </TooltipTrigger>
          <TooltipContent>Regenerate</TooltipContent>
        </Tooltip>
      )}
      {copied && (
        <span
          className="text-[11px] text-[hsl(var(--ink-4))]"
          aria-live="polite"
        >
          Copied
        </span>
      )}
    </div>
  );
}
