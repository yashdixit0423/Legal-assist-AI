import {
  ExternalLink,
  ArrowUpRight,
  ArrowDownLeft,
  FileText,
} from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import type { SectionDetail } from "@/lib/api/types";

/**
 * One section, verbatim.
 *
 * This is the authoritative text, so typography is a feature: serif, generous
 * measure, paragraph breaks preserved. Provenance — the as-of date and the
 * India Code source link — is shown rather than buried, because in a legal
 * product a reader has to be able to check where the words came from.
 *
 * Footnote markers arrive inline as [N] and are left exactly as the source
 * has them. They are not citations and must not be linked.
 */
export function SectionReader({
  section,
  compact = false,
}: {
  section: SectionDetail;
  compact?: boolean;
}) {
  const outbound = section.related.filter((r) => r.direction === "outbound");
  const inbound = section.related.filter((r) => r.direction === "inbound");

  return (
    <article
      className={cn("section-reader", compact && "section-reader-compact")}
    >
      <header className="border-b border-[hsl(var(--line))] pb-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="meta-label">{section.statute_short_title}</span>
          {section.is_omitted && (
            <span className="rounded-full bg-[hsl(var(--muted))] px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-[hsl(var(--ink-3))]">
              Omitted
            </span>
          )}
        </div>
        <h1 className="font-display mt-2 text-[26px] leading-tight tracking-[-0.01em] text-[hsl(var(--ink))]">
          Section {section.section_no}
          {section.marginal_note
            ? ` · ${section.marginal_note.replace(/\.$/, "")}`
            : ""}
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-[hsl(var(--ink-3))]">
          <span>As of {formatDate(section.as_of_date)}</span>
          {section.commenced_on && (
            <span>Commenced {formatDate(section.commenced_on)}</span>
          )}
          <a
            href={section.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[hsl(var(--brand))] hover:underline"
          >
            India Code source <ExternalLink size={11} />
          </a>
        </div>
      </header>

      <div className="mt-5 space-y-4 font-serif text-[15px] leading-[1.75] text-[hsl(var(--ink))]">
        {section.text.split(/\n{2,}/).map((para, index) => (
          <p key={index} className="whitespace-pre-wrap">
            {para}
          </p>
        ))}
      </div>

      {section.amendment_note && (
        <div className="mt-6 rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-4">
          <div className="meta-label mb-1">Amendment note</div>
          <p className="text-[13px] leading-relaxed text-[hsl(var(--ink-2))]">
            {section.amendment_note}
          </p>
        </div>
      )}

      {section.footnotes.length > 0 && (
        <div className="mt-5 border-t border-[hsl(var(--line))] pt-4">
          <div className="meta-label mb-2">Footnotes</div>
          <ol className="space-y-1.5 text-[12px] leading-relaxed text-[hsl(var(--ink-3))]">
            {section.footnotes.map((note, index) => (
              <li key={index} className="flex gap-2">
                <span className="font-semibold text-[hsl(var(--ink-4))]">
                  [{String(note.marker ?? index + 1)}]
                </span>
                <span>{String(note.text ?? "")}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {section.related.length > 0 && (
        <div className="mt-6 grid gap-4 border-t border-[hsl(var(--line))] pt-5 sm:grid-cols-2">
          <RelatedList
            title="Cites"
            hint="Provisions this section refers to"
            icon={<ArrowUpRight size={12} />}
            items={outbound}
          />
          <RelatedList
            title="Cited by"
            hint="Provisions that refer here"
            icon={<ArrowDownLeft size={12} />}
            items={inbound}
          />
        </div>
      )}
    </article>
  );
}

function RelatedList({
  title,
  hint,
  icon,
  items,
}: {
  title: string;
  hint: string;
  icon: React.ReactNode;
  items: SectionDetail["related"];
}) {
  if (items.length === 0) return null;
  return (
    <div>
      <div className="meta-label mb-1 flex items-center gap-1.5">
        {icon} {title}
      </div>
      <p className="mb-2 text-[11px] text-[hsl(var(--ink-4))]">{hint}</p>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={`${item.direction}-${item.id}`}>
            <Link
              to={`/sections/${item.id}`}
              className="text-[13px] text-[hsl(var(--brand))] hover:underline"
            >
              {item.statute_short_title} · s. {item.section_no}
            </Link>
            {item.marginal_note && (
              <span className="ml-1 text-[12px] text-[hsl(var(--ink-4))]">
                — {item.marginal_note.replace(/\.$/, "")}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReaderEmptyState() {
  return (
    <div className="section-reader flex min-h-[280px] flex-col items-center justify-center gap-3 text-center">
      <span className="feature-icon">
        <FileText size={18} />
      </span>
      <p className="max-w-[34ch] text-[13px] leading-relaxed text-[hsl(var(--ink-3))]">
        Select a citation in an answer, or a section from an Act, to read the
        provision in full.
      </p>
    </div>
  );
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
