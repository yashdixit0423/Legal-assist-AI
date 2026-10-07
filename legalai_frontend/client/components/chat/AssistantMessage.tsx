import { RefreshCw, Search, Square } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  Abstention,
  SourceList,
  type AnswerState,
} from "@/components/AnswerPanel";
import { ErrorNotice } from "@/components/ErrorNotice";
import type { ChatMessage } from "@/hooks/use-chat";
import { AnswerText } from "./AnswerText";
import { MessageActions } from "./MessageActions";

/** The shared answer pieces read an `AnswerState`; a chat message maps onto one. */
function asAnswerState(message: ChatMessage): AnswerState {
  return {
    text: message.text,
    sources: message.sources,
    citedIds: message.citedIds,
    abstained: Boolean(message.abstain),
    abstainReason: message.abstain?.reason ?? null,
    topScore: message.abstain?.topScore ?? null,
    scoreFloor: message.abstain?.scoreFloor ?? 0,
    invalidating: Boolean(message.invalidating),
    done: message.done ?? null,
    streaming: message.status === "streaming",
  };
}

/** Loading copy describes only what the stream has actually reached. */
const PHASE_LABEL = {
  searching: "Searching the indexed Acts…",
  preparing: "Preparing answer…",
} as const;

export function AssistantMessage({
  message,
  isLatest,
  onRegenerate,
}: {
  message: ChatMessage;
  isLatest: boolean;
  onRegenerate: () => void;
}) {
  const navigate = useNavigate();
  const state = asAnswerState(message);
  const streaming = message.status === "streaming";
  const waiting =
    streaming &&
    !message.text &&
    !message.invalidating &&
    (message.phase === "searching" || message.phase === "preparing");

  if (message.abstain) {
    return (
      <div className="space-y-2">
        <Abstention state={state} />
        {!streaming && isLatest && (
          <MessageActions message={message} onRegenerate={onRegenerate} />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {waiting && message.phase && (
        <p className="inline-flex items-center gap-2 text-[13px] text-[hsl(var(--ink-3))]">
          <Search
            size={13}
            className="animate-pulse text-[hsl(var(--brand))]"
          />
          {PHASE_LABEL[message.phase]}
        </p>
      )}

      {message.invalidating && (
        <div className="flex items-start gap-2.5 rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-3">
          <RefreshCw
            size={14}
            className="mt-0.5 animate-spin text-[hsl(var(--brand))]"
          />
          <p className="text-[12.5px] leading-relaxed text-[hsl(var(--ink-2))]">
            That draft cited a provision outside the retrieved set, so it was
            discarded. Rewriting the answer from the sources below.
          </p>
        </div>
      )}

      {(message.text || (streaming && message.phase === "writing")) && (
        <div className="text-[15px] leading-[1.75] text-[hsl(var(--ink))]">
          <AnswerText text={message.text} sources={message.sources} />
          {streaming && <span className="stream-caret" aria-hidden="true" />}
        </div>
      )}

      {message.status === "stopped" && (
        <p className="inline-flex items-center gap-1.5 text-[12px] text-[hsl(var(--ink-4))]">
          <Square size={11} />
          {message.text ? "Stopped" : "Stopped before an answer was written"}
        </p>
      )}

      {message.error && (
        <ErrorNotice
          error={message.error}
          className="mt-1"
          onSettings={() => navigate("/settings")}
          onRetry={isLatest ? onRegenerate : undefined}
        />
      )}

      {message.sources.length > 0 && message.status === "done" && (
        <SourceList state={state} />
      )}

      {!streaming && !message.error && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <MessageActions
            message={message}
            onRegenerate={isLatest ? onRegenerate : undefined}
          />
          {message.done?.model && (
            <span className="text-[11px] text-[hsl(var(--ink-4))]">
              {message.done.model}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
