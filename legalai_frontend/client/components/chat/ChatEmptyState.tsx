import { Sparkles } from "lucide-react";

/**
 * One prompt per indexed Act, so every suggestion is one the corpus can
 * actually answer rather than one that would abstain.
 */
const PROMPTS = [
  "What makes an agreement void for want of consideration?",
  "When must a lease of immoveable property be registered?",
  "Which instruments are chargeable with stamp duty?",
  "Within what time must a document be presented for registration?",
  "What is the punishment for identity theft under the IT Act?",
  "When can a data principal withdraw consent?",
];

/**
 * Picking a prompt fills the composer; it never sends. Without `onPick`
 * there is no composer to fill, so the prompts render disabled.
 */
export function ChatEmptyState({
  onPick,
}: {
  onPick?: (prompt: string) => void;
}) {
  return (
    <div className="py-10">
      <div className="eyebrow mb-3">
        <span className="eyebrow-dot" /> Grounded in retrieved statute text
      </div>
      <h2 className="font-display text-[28px] leading-tight tracking-[-0.02em] text-[hsl(var(--ink))]">
        What would you like to work through?
      </h2>
      <p className="mt-2 max-w-[56ch] text-[14px] leading-relaxed text-[hsl(var(--ink-3))]">
        Ask a question and follow up on the answer. Each reply is drawn from the
        indexed Acts and cites the provisions it relies on; when the corpus does
        not cover a question, it says so.
      </p>

      <div className="mt-8">
        <div className="meta-label mb-3 flex items-center gap-1.5">
          <Sparkles size={12} /> Try one of these
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {PROMPTS.map((prompt) => (
            <button
              key={prompt}
              disabled={!onPick}
              onClick={() => onPick?.(prompt)}
              className="landing-question-card text-left disabled:cursor-not-allowed disabled:opacity-55"
            >
              {prompt}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
