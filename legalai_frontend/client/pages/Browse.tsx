import { BookOpenText, LoaderCircle } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import { formatDate } from "@/components/SectionReader";
import { getStatute, listStatutes } from "@/lib/api/corpus";
import { cn } from "@/lib/utils";

export default function Browse() {
  const { slug } = useParams();
  return (
    <LegalAssistLayout>
      {slug ? <ActView slug={slug} /> : <ActList />}
    </LegalAssistLayout>
  );
}

function ActList() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["statutes"],
    queryFn: listStatutes,
    staleTime: 5 * 60 * 1000,
  });

  return (
    <div className="mx-auto max-w-[1000px] px-5 py-10 sm:px-8">
      <div className="eyebrow mb-3">
        <span className="eyebrow-dot" /> The indexed corpus
      </div>
      <h1 className="font-display text-[32px] leading-tight tracking-[-0.02em]">
        Browse the law
      </h1>
      <p className="mt-2 max-w-[58ch] text-[14px] leading-relaxed text-[hsl(var(--ink-3))]">
        Every Act here was fetched from India Code, checked for continuity and
        stored with its source URL and as-of date. Nothing else is in scope.
      </p>

      {isLoading && <Loading />}
      {error && (
        <p className="mt-6 text-[13px] text-[hsl(var(--ink-3))]">
          Could not load the Acts.
        </p>
      )}

      <div className="mt-7 grid gap-3">
        {data?.map((statute) => (
          <Link
            key={statute.slug}
            to={`/browse/${statute.slug}`}
            className="list-card flex flex-wrap items-start justify-between gap-4"
          >
            <div className="min-w-0">
              <h2 className="font-display text-[19px] tracking-[-0.01em] text-[hsl(var(--ink))]">
                {statute.short_title}
              </h2>
              {statute.long_title && (
                <p className="mt-1 max-w-[62ch] text-[12.5px] leading-relaxed text-[hsl(var(--ink-3))]">
                  {statute.long_title}
                </p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[hsl(var(--ink-4))]">
                {statute.act_number && (
                  <span>Act no. {statute.act_number}</span>
                )}
                <span>{statute.jurisdiction}</span>
                {statute.ministry && (
                  <span className="truncate">{statute.ministry}</span>
                )}
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-[13px] font-semibold text-[hsl(var(--ink))]">
                {statute.section_count} sections
              </div>
              <div className="mt-0.5 text-[11px] text-[hsl(var(--ink-4))]">
                as of {formatDate(statute.as_of_date)}
              </div>
              {statute.is_repealed && (
                <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.1em] text-[hsl(var(--ink-3))]">
                  Repealed
                </div>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function ActView({ slug }: { slug: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["statute", slug],
    queryFn: () => getStatute(slug),
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading)
    return (
      <div className="mx-auto max-w-[1000px] px-5 py-10">
        <Loading />
      </div>
    );
  if (error || !data) {
    return (
      <div className="mx-auto max-w-[1000px] px-5 py-10 sm:px-8">
        <p className="text-[13px] text-[hsl(var(--ink-3))]">
          No indexed Act with that slug.{" "}
          <Link
            to="/browse"
            className="text-[hsl(var(--brand))] hover:underline"
          >
            Back to the list
          </Link>
          .
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1000px] px-5 py-10 sm:px-8">
      <Link
        to="/browse"
        className="text-[12px] text-[hsl(var(--brand))] hover:underline"
      >
        ← All Acts
      </Link>
      <h1 className="font-display mt-3 text-[30px] leading-tight tracking-[-0.02em]">
        {data.short_title}
      </h1>
      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-[11.5px] text-[hsl(var(--ink-3))]">
        <span>
          {data.sections_in_force} in force · {data.sections_total} held
        </span>
        <span>as of {formatDate(data.as_of_date)}</span>
        <a
          href={data.source_url}
          target="_blank"
          rel="noreferrer"
          className="text-[hsl(var(--brand))] hover:underline"
        >
          India Code source
        </a>
      </div>

      {/*
        parts_available is false for every Act: India Code's API exposes no
        per-section chapter field and the headings are not in the text either.
        The tree is genuinely unknown, so no navigation is rendered — an empty
        chapter list would read as "this Act has no chapters", which is false.
      */}
      {data.parts_available && data.parts.length > 0 && (
        <nav className="chapter-nav mt-6">
          {data.parts.map((part) => (
            <span key={part.id} className="chapter-link">
              {part.kind} {part.number} {part.heading}
            </span>
          ))}
        </nav>
      )}

      <div className="meta-label mt-8 mb-3">Sections</div>
      <div className="divide-y divide-[hsl(var(--line))] overflow-hidden rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))]">
        {/* Already in legal citation order from the API — never re-sorted here. */}
        {data.sections.map((section) => (
          <Link
            key={section.id}
            to={`/sections/${section.id}`}
            className="flex items-baseline gap-4 px-4 py-2.5 transition-colors hover:bg-[hsl(var(--brand-soft))]"
          >
            <span
              className={cn(
                "w-16 shrink-0 font-mono text-[12px] font-semibold",
                section.is_omitted
                  ? "text-[hsl(var(--ink-4))]"
                  : "text-[hsl(var(--brand))]",
              )}
            >
              {section.section_no}
            </span>
            <span
              className={cn(
                "min-w-0 flex-1 truncate text-[13.5px]",
                section.is_omitted
                  ? "text-[hsl(var(--ink-4))] line-through"
                  : "text-[hsl(var(--ink))]",
              )}
            >
              {section.marginal_note?.replace(/\.$/, "") ?? "—"}
            </span>
            {section.is_omitted && (
              <span className="shrink-0 text-[10px] font-bold uppercase tracking-[0.1em] text-[hsl(var(--ink-4))]">
                omitted
              </span>
            )}
          </Link>
        ))}
      </div>
      <p className="mt-3 text-[11.5px] leading-relaxed text-[hsl(var(--ink-4))]">
        Omitted provisions are kept so the numbering stays continuous. They are
        excluded from search and never used to answer a question.
      </p>
    </div>
  );
}

function Loading() {
  return (
    <div className="mt-8 flex items-center gap-2 text-[13px] text-[hsl(var(--ink-3))]">
      <LoaderCircle size={14} className="animate-spin" /> Loading the corpus…
    </div>
  );
}

export { BookOpenText };
