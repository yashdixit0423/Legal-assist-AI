import { useState } from "react";
import { Check, ChevronDown, Copy, ExternalLink, Link2, Share2 } from "lucide-react";
import type { StatuteSection } from "@/lib/legal-data";
import { cn } from "@/lib/utils";

export function AsOfBadge({ date }: { date: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[hsl(var(--ink-3))]">
      As on {date} <span className="mx-1 text-[hsl(var(--ink-4))]">—</span> later amendments not reflected
    </span>
  );
}

export function SectionReader({
  section,
  className,
  compact = false,
}: {
  section: StatuteSection;
  className?: string;
  compact?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const permalink = `legalassist.ai/section/${section.id}`;

  const copyLink = async () => {
    await navigator.clipboard?.writeText(`https://${permalink}`);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <article className={cn("section-reader", compact && "section-reader-compact", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[hsl(var(--line))] px-5 py-4 sm:px-7">
        <div>
          <div className="mb-1 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-[hsl(var(--brand))]">
            <span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--brand))]" />
            Section {section.number}
          </div>
          <h3 className="font-display text-lg text-[hsl(var(--ink))]">{section.heading}</h3>
        </div>
        <AsOfBadge date={section.asOf} />
      </div>

      <div className="px-5 py-6 sm:px-7 sm:py-8">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-[hsl(var(--ink-3))]">
          <span>{section.act}</span>
          <span className="text-[hsl(var(--ink-4))]">/</span>
          <span>S. {section.number}</span>
        </div>
        <blockquote className="statute-quote">“{section.text}”</blockquote>

        <div className="mt-7 border-l-2 border-[hsl(var(--brand-soft))] pl-4 sm:pl-5">
          <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-[hsl(var(--ink-3))]">Explanation</div>
          <p className="max-w-2xl text-sm leading-6 text-[hsl(var(--ink-2))]">{section.explanation}</p>
        </div>

        <div className="mt-8 grid gap-5 border-t border-[hsl(var(--line))] pt-5 sm:grid-cols-[1fr_auto]">
          <div>
            <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-[hsl(var(--ink-3))]">Related provisions</div>
            <div className="flex flex-wrap gap-2">
              {section.related.map((related) => (
                <button key={related} className="inline-flex items-center gap-1.5 rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 py-2 text-xs font-medium text-[hsl(var(--ink-2))] transition hover:border-[hsl(var(--brand))] hover:text-[hsl(var(--brand))]">
                  <Link2 size={12} /> {related}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-end gap-2 sm:justify-end">
            <button onClick={copyLink} className="icon-button" aria-label="Copy permalink" title="Copy permalink">
              {copied ? <Check size={15} /> : <Copy size={15} />}
            </button>
            <button onClick={copyLink} className="inline-flex h-9 items-center gap-2 rounded-lg border border-[hsl(var(--line))] px-3 text-xs font-semibold text-[hsl(var(--ink-2))] transition hover:border-[hsl(var(--brand))] hover:text-[hsl(var(--brand))]">
              <Share2 size={14} /> {copied ? "Copied" : "Share section"}
            </button>
          </div>
        </div>

        <div className="mt-4 border-t border-[hsl(var(--line))] pt-3">
          <button onClick={() => setHistoryOpen((open) => !open)} className="flex w-full items-center justify-between text-left text-xs font-semibold text-[hsl(var(--ink-3))] hover:text-[hsl(var(--ink))]">
            <span>Amendment history & footnotes</span>
            <ChevronDown size={15} className={cn("transition-transform", historyOpen && "rotate-180")} />
          </button>
          {historyOpen && <p className="mt-3 max-w-2xl text-xs leading-5 text-[hsl(var(--ink-3))]">{section.amendment}</p>}
        </div>
      </div>
    </article>
  );
}

export function ReaderEmptyState() {
  return (
    <div className="flex min-h-[420px] flex-col items-center justify-center px-8 text-center">
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] text-[hsl(var(--brand))]">
        <ExternalLink size={20} />
      </div>
      <h3 className="font-display text-xl text-[hsl(var(--ink))]">Open a citation to read the law</h3>
      <p className="mt-2 max-w-xs text-sm leading-6 text-[hsl(var(--ink-3))]">Every cited section opens here with the verbatim text first, so you can verify the answer in one click.</p>
    </div>
  );
}
