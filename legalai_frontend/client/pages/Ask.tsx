import { useCallback, useRef, useState } from "react";
import { KeyRound, LockKeyhole, Sparkles } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { AskComposer } from "@/components/AskComposer";
import { AnswerPanel, type AnswerState } from "@/components/AnswerPanel";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import { askStream } from "@/lib/api/ask";
import { ApiError } from "@/lib/api/client";
import { useAuth, useRateLimit } from "@/hooks/use-auth";
import type { Turn } from "@/lib/api/types";

/** Client-held history. The backend stores nothing; this lives in this tab only. */
const TURNS_KEY = "legaledge.turns";
const MAX_TURNS = 6;

function readTurns(): Turn[] {
  try {
    return JSON.parse(sessionStorage.getItem(TURNS_KEY) ?? "[]") as Turn[];
  } catch {
    return [];
  }
}

const empty: AnswerState = {
  text: "",
  sources: [],
  citedIds: [],
  abstained: false,
  abstainReason: null,
  topScore: null,
  scoreFloor: 0,
  invalidating: false,
  done: null,
  streaming: false,
};

export default function Ask() {
  const navigate = useNavigate();
  const { signedIn } = useAuth();
  const rateLimit = useRateLimit("/v1/ask");
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<AnswerState>(empty);
  const [error, setError] = useState<ApiError | null>(null);
  const [turns, setTurns] = useState<Turn[]>(readTurns);
  const abort = useRef<AbortController | null>(null);

  const exhausted = rateLimit !== null && rateLimit.remaining <= 0;

  const submit = useCallback(
    async (text: string, statuteSlug: string | null) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;

      setQuestion(text);
      setError(null);
      setState({ ...empty, streaming: true });

      let accumulated = "";
      try {
        await askStream(
          {
            question: text,
            turns: turns.slice(-MAX_TURNS),
            statute_slug: statuteSlug,
          },
          {
            onSources: (sources) => setState((s) => ({ ...s, sources })),
            onToken: (chunk, replacesAll) => {
              accumulated = replacesAll ? chunk : accumulated + chunk;
              setState((s) => ({
                ...s,
                text: accumulated,
                invalidating: false,
              }));
            },
            onInvalidated: () => {
              // The server caught a fabricated citation mid-stream. Everything
              // rendered so far is void; a corrected answer follows.
              accumulated = "";
              setState((s) => ({ ...s, text: "", invalidating: true }));
            },
            onAbstain: (payload) =>
              setState((s) => ({
                ...s,
                abstained: true,
                text: payload.message,
                abstainReason: payload.reason,
                topScore: payload.top_score,
                scoreFloor: payload.score_floor,
              })),
            onDone: (done) => {
              setState((s) => ({
                ...s,
                citedIds: done.cited_section_ids,
                done,
                streaming: false,
              }));
              if (done.answered) {
                const next = [
                  ...turns,
                  { role: "user" as const, content: text },
                  { role: "assistant" as const, content: accumulated },
                ].slice(-MAX_TURNS);
                setTurns(next);
                sessionStorage.setItem(TURNS_KEY, JSON.stringify(next));
              }
            },
            onError: (apiError) => {
              setError(apiError);
              setState((s) => ({ ...s, streaming: false }));
            },
          },
          controller.signal,
        );
      } catch (caught) {
        if (caught instanceof ApiError) setError(caught);
        setState((s) => ({ ...s, streaming: false }));
      }
    },
    [turns],
  );

  return (
    <LegalAssistLayout>
      <div className="mx-auto max-w-[840px] px-5 py-10 sm:px-8">
        <div className="eyebrow mb-3">
          <span className="eyebrow-dot" /> Grounded in retrieved statute text
        </div>
        <h1 className="font-display text-[32px] leading-tight tracking-[-0.02em] text-[hsl(var(--ink))]">
          Ask about Indian statute law
        </h1>
        <p className="mt-2 max-w-[56ch] text-[14px] leading-relaxed text-[hsl(var(--ink-3))]">
          Every assertion is cited to the provision it came from, and the
          citations are checked against what was actually retrieved. When the
          corpus does not cover a question, it says so instead of guessing.
        </p>

        <AskComposer
          className="mt-7"
          onSubmit={submit}
          busy={state.streaming}
          disabled={!signedIn || exhausted}
          disabledHint={
            !signedIn ? (
              <Link
                to="/login"
                className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[hsl(var(--brand))] hover:underline"
              >
                <LockKeyhole size={13} /> Sign in to ask
              </Link>
            ) : (
              <span className="text-[12px] text-[hsl(var(--ink-3))]">
                Hourly limit reached — resets in{" "}
                {Math.ceil((rateLimit?.resetAfter ?? 0) / 60)} min
              </span>
            )
          }
        />

        {rateLimit && signedIn && (
          <p className="mt-2 text-right text-[11px] text-[hsl(var(--ink-4))]">
            {Math.max(0, rateLimit.remaining)} of {rateLimit.limit} questions
            left this hour
          </p>
        )}

        {error && (
          <ErrorNotice error={error} onSettings={() => navigate("/settings")} />
        )}

        {(state.text || state.streaming) && !error && (
          <div className="mt-7">
            <p className="mb-3 text-[13px] font-medium text-[hsl(var(--ink-3))]">
              {question}
            </p>
            <AnswerPanel state={state} />
          </div>
        )}

        {!state.text && !state.streaming && !error && (
          <Suggestions onPick={(q) => submit(q, null)} disabled={!signedIn} />
        )}
      </div>
    </LegalAssistLayout>
  );
}

/**
 * Errors are branched on `code`, never on message text. The 402 is the one
 * that matters: the backend uses that status precisely so a client can offer
 * Settings rather than a generic failure.
 */
function ErrorNotice({
  error,
  onSettings,
}: {
  error: ApiError;
  onSettings: () => void;
}) {
  const needsKey =
    error.code === "missing_provider_key" ||
    error.code === "provider_key_invalid" ||
    error.code === "provider_quota_exceeded";

  return (
    <div className="mt-6 rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-5">
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

const SUGGESTED = [
  "When must a lease of immoveable property be registered?",
  "What notice terminates a lease for agricultural purposes?",
  "Is an agreement in restraint of trade enforceable?",
  "What security safeguards must a data fiduciary put in place?",
];

function Suggestions({
  onPick,
  disabled,
}: {
  onPick: (q: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="mt-8">
      <div className="meta-label mb-3 flex items-center gap-1.5">
        <Sparkles size={12} /> Try one of these
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {SUGGESTED.map((q) => (
          <button
            key={q}
            disabled={disabled}
            onClick={() => onPick(q)}
            className="landing-question-card text-left disabled:cursor-not-allowed disabled:opacity-55"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
