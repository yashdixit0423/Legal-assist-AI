import { FileText, RefreshCw, Search, Square } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  Abstention,
  SourceList,
  type AnswerState,
} from "@/components/AnswerPanel";
import { ErrorNotice } from "@/components/ErrorNotice";
import type { ChatMessage } from "@/hooks/use-chat";
import type { DocumentSourceBlock } from "@/lib/api/types";
import { displayName } from "@/lib/chat/files";
import { locatorLabel } from "@/lib/chat/citations";
import { AnswerText } from "./AnswerText";
import { MessageActions } from "./MessageActions";
import { useOpenDocument, useOpenSource } from "./SourcePanel";

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
  const openSource = useOpenSource();
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
        <div>
          <AnswerText
            text={message.text}
            sources={message.sources}
            documentSources={message.documentSources}
          />
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

      {message.status === "done" &&
        (message.documentSources?.length ?? 0) > 0 && (
          <DocumentSources
            sources={message.documentSources ?? []}
            cited={message.citedDocumentIds ?? []}
          />
        )}

      {message.sources.length > 0 && message.status === "done" && (
        <div>
          {(message.documentSources?.length ?? 0) > 0 && (
            <div className="meta-label -mb-1 mt-5">Legal sources</div>
          )}
          <SourceList state={state} onOpen={openSource} />
        </div>
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

/**
 * Passages of the user's own documents, listed apart from the law and labelled
 * as theirs. Cited passages first; the rest are what the model was also given.
 */
function DocumentSources({
  sources,
  cited,
}: {
  sources: DocumentSourceBlock[];
  cited: string[];
}) {
  const openDocument = useOpenDocument();
  const ordered = [
    ...sources.filter((s) => cited.includes(s.citation_id)),
    ...sources.filter((s) => !cited.includes(s.citation_id)),
  ];
  return (
    <div className="mt-5 border-t border-[hsl(var(--line))] pt-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="meta-label">Document sources</div>
        <span className="text-[11px] text-[hsl(var(--ink-4))]">
          {cited.length} cited · {sources.length} provided
        </span>
      </div>
      <div className="divide-y divide-[hsl(var(--line))] rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))]">
        {ordered.map((source) => (
          <button
            key={source.citation_id}
            type="button"
            onClick={() => openDocument?.(source)}
            className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-[hsl(var(--brand-soft))]"
          >
            <FileText
              size={14}
              className="mt-0.5 shrink-0 text-[hsl(var(--ink-3))]"
            />
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-[hsl(var(--ink))]">
                {displayName(source.filename, 40)} ·{" "}
                {locatorLabel(source.locator_kind, source.locator)}
              </div>
              <div className="mt-1 line-clamp-2 text-xs text-[hsl(var(--ink-3))]">
                {source.excerpt}
              </div>
              {!cited.includes(source.citation_id) && (
                <span className="mt-1 inline-block text-[10px] uppercase tracking-[0.08em] text-[hsl(var(--ink-4))]">
                  not cited
                </span>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
