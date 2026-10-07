import { KeyRound, RotateCcw } from "lucide-react";
import type { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/**
 * Errors are branched on `code`, never on message text. The 402 is the one
 * that matters: the backend uses that status precisely so a client can offer
 * Settings rather than a generic failure.
 */
export function ErrorNotice({
  error,
  onSettings,
  onRetry,
  className = "mt-6",
}: {
  error: ApiError;
  onSettings: () => void;
  /** Chat offers a retry under the failed message; Ask does not. */
  onRetry?: () => void;
  className?: string;
}) {
  const needsKey =
    error.code === "missing_provider_key" ||
    error.code === "provider_key_invalid" ||
    error.code === "provider_quota_exceeded";

  return (
    <div
      className={cn(
        "rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-5",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <span className="feature-icon shrink-0">
          <KeyRound size={16} />
        </span>
        <div>
          <h3 className="text-[15px] font-semibold text-[hsl(var(--ink))]">
            {needsKey
              ? "A provider key is needed"
              : "That request did not complete"}
          </h3>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[hsl(var(--ink-2))]">
            {error.message}
          </p>
          {error.retryAfterSeconds !== null && (
            <p className="mt-1 text-[12px] text-[hsl(var(--ink-3))]">
              Try again in {error.retryAfterSeconds}s.
            </p>
          )}
          {needsKey && (
            <button
              onClick={onSettings}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-[hsl(var(--brand))] px-3 py-1.5 text-[12px] font-semibold text-[hsl(var(--brand-foreground))]"
            >
              {error.provider ? `Add a ${error.provider} key` : "Open Settings"}
            </button>
          )}
          {onRetry && !needsKey && (
            <button
              onClick={onRetry}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-[hsl(var(--line))] px-3 py-1.5 text-[12px] font-semibold text-[hsl(var(--ink-2))] transition-colors hover:border-[hsl(var(--brand))] hover:text-[hsl(var(--brand))]"
            >
              <RotateCcw size={13} /> Retry
            </button>
          )}
          {error.requestId && (
            <p className="mt-2 font-mono text-[10px] text-[hsl(var(--ink-4))]">
              request {error.requestId}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
