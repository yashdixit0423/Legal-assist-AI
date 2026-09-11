import { AlertTriangle, Info, RefreshCw } from "lucide-react";
import { CitationChip, shortStatute } from "@/components/CitationChip";
import { parseAnswer } from "@/lib/api/ask";
import type { AskDonePayload, SourceBlock } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export interface AnswerState {
  text: string;
  sources: SourceBlock[];
  citedIds: number[];
  abstained: boolean;
  abstainReason: string | null;
  topScore: number | null;
  scoreFloor: number;
  invalidating: boolean;
  done: AskDonePayload | null;
  streaming: boolean;
}

/**
 * The answer.
 *
 * Two states here are the product rather than edge cases:
 *
 *  - **Abstention** arrives at HTTP 200 and is a correct outcome. It is
 *    rendered as a composed answer, not an error and not an empty state. The
 *    wording is the server's; it names the six Acts held and says what is
 *    absent.
 *  - **Invalidating** means the server caught the model citing a section it
 *    was not given and killed the stream. Everything rendered is discarded and
 *    a correction is on the way. Shown as a working state, not a failure.
 */
export function AnswerPanel({ state }: { state: AnswerState }) {
  if (state.abstained) return <Abstention state={state} />;

  const parts = parseAnswer(state.text);
  const byId = new Map(
    state.sources.map((source) => [source.section_id, source]),
  );

  return (
    <div className="answer-card">
      {state.invalidating && (
        <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-3">
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

      <div className="space-y-3 text-[15px] leading-[1.75] text-[hsl(var(--ink))]">
        {parts.map((part, index) =>
          part.kind === "text" ? (
            <span key={index} className="whitespace-pre-wrap">
              {part.value}
            </span>
          ) : (
            <span key={index} className="mx-0.5 inline-flex gap-1">
              {part.sectionIds.map((id) => (
                <CitationChip key={id} sectionId={id} source={byId.get(id)} />
              ))}
            </span>
          ),
        )}
        {state.streaming && (
          <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-[hsl(var(--brand))] align-middle" />
        )}
      </div>

      {state.sources.length > 0 && <SourceList state={state} />}
      {state.done && <AnswerFooter done={state.done} />}
    </div>
  );
}

function Abstention({ state }: { state: AnswerState }) {
  return (
    <div className="answer-card">
      <div className="flex items-start gap-3">
        <span className="feature-icon shrink-0">
          <Info size={17} />
        </span>
        <div>
          <h3 className="font-display text-[19px] tracking-[-0.01em] text-[hsl(var(--ink))]">
            Outside the indexed corpus
          </h3>
          <p className="mt-2 text-[14.5px] leading-[1.7] text-[hsl(var(--ink-2))]">
            {state.text}
          </p>
        </div>
      </div>
      <details className="mt-4 border-t border-[hsl(var(--line))] pt-3">
        <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.12em] text-[hsl(var(--ink-4))]">
          Why it stopped
        </summary>
        <dl className="mt-2 grid gap-1 text-[12px] text-[hsl(var(--ink-3))]">
          <div className="flex gap-2">
            <dt className="w-36 text-[hsl(var(--ink-4))]">Best match scored</dt>
            <dd>
              {state.topScore === null
                ? "nothing retrieved"
                : state.topScore.toFixed(4)}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-36 text-[hsl(var(--ink-4))]">Required</dt>
            <dd>{state.scoreFloor.toFixed(2)} or better</dd>
          </div>
          {state.abstainReason && (
            <div className="flex gap-2">
              <dt className="w-36 text-[hsl(var(--ink-4))]">Reason</dt>
              <dd>{state.abstainReason.replace(/_/g, " ")}</dd>
            </div>
          )}
        </dl>
        <p className="mt-2 text-[11.5px] leading-relaxed text-[hsl(var(--ink-4))]">
          No model was called, so this question cost nothing.
        </p>
      </details>
    </div>
  );
}

function SourceList({ state }: { state: AnswerState }) {
  const cited = state.sources.filter((source) =>
    state.citedIds.includes(source.section_id),
  );
  const considered = state.sources.filter(
    (source) => !state.citedIds.includes(source.section_id),
  );

  return (
    <div className="mt-5 border-t border-[hsl(var(--line))] pt-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="meta-label">Sources used</div>
        <span className="text-[11px] text-[hsl(var(--ink-4))]">
          {cited.length} cited · {state.sources.length} retrieved
        </span>
      </div>
      <div className="divide-y divide-[hsl(var(--line))] rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))]">
        {(cited.length > 0 ? cited : state.sources).map((source) => (
          <SourceRow key={source.section_id} source={source} cited />
        ))}
      </div>
      {cited.length > 0 && considered.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.12em] text-[hsl(var(--ink-4))]">
            Also retrieved, not cited ({considered.length})
          </summary>
          <div className="mt-2 divide-y divide-[hsl(var(--line))] rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] opacity-75">
            {considered.map((source) => (
              <SourceRow
                key={source.section_id}
                source={source}
                cited={false}
              />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function SourceRow({ source, cited }: { source: SourceBlock; cited: boolean }) {
  return (
    <a
      href={`/sections/${source.section_id}`}
      className="flex items-start justify-between gap-4 px-4 py-3 transition-colors hover:bg-[hsl(var(--brand-soft))]"
    >
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold text-[hsl(var(--ink))]">
          s. {source.section_no}
          {source.marginal_note
            ? ` · ${source.marginal_note.replace(/\.$/, "")}`
            : ""}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--ink-3))]">
          <span>{shortStatute(source.statute)}</span>
          {source.origin === "cross_reference" && (
            <span className="rounded-full border border-[hsl(var(--line))] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[hsl(var(--ink-4))]">
              referenced by
            </span>
          )}
          {!cited && (
            <span className="text-[10px] uppercase tracking-[0.08em] text-[hsl(var(--ink-4))]">
              not cited
            </span>
          )}
        </div>
      </div>
    </a>
  );
}

function AnswerFooter({ done }: { done: AskDonePayload }) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[hsl(var(--line))] pt-3 text-[11px] text-[hsl(var(--ink-4))]">
      {done.model && <span>{done.model}</span>}
      {done.tokens_in !== null && (
        <span>
          {done.tokens_in.toLocaleString()} in ·{" "}
          {(done.tokens_out ?? 0).toLocaleString()} out
        </span>
      )}
      <span>{(done.latency_ms / 1000).toFixed(1)}s</span>
      <span>{done.prompt_version}</span>
      {done.citation_violation && (
        <span
          className={cn(
            "inline-flex items-center gap-1 text-[hsl(var(--ink-3))]",
          )}
        >
          <AlertTriangle size={11} /> corrected once
        </span>
      )}
    </div>
  );
}
