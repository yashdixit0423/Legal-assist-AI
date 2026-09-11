import { useEffect, useState } from "react";
import { LoaderCircle, Search as SearchIcon } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import { listStatutes, search } from "@/lib/api/corpus";

/**
 * Corpus search. Public — no key, no token, no model.
 *
 * The query lives in the URL so a result page can be linked and shared, which
 * is why the backend exposes a GET form alongside the POST one.
 */
export default function Search() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const slug = params.get("act") ?? "";
  const includeOmitted = params.get("omitted") === "1";
  const [draft, setDraft] = useState(q);

  // Debounced: search is ~80ms warm, so typing can drive it.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (draft !== q) {
        const next = new URLSearchParams(params);
        draft ? next.set("q", draft) : next.delete("q");
        setParams(next, { replace: true });
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [draft]);

  const { data: statutes } = useQuery({
    queryKey: ["statutes"],
    queryFn: listStatutes,
    staleTime: 5 * 60 * 1000,
  });

  const { data, isFetching, error } = useQuery({
    queryKey: ["search", q, slug, includeOmitted],
    queryFn: () =>
      search({
        q,
        statute_slug: slug || null,
        include_omitted: includeOmitted,
        limit: 25,
      }),
    enabled: q.trim().length >= 2,
  });

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    value ? next.set(key, value) : next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <LegalAssistLayout>
      <div className="mx-auto max-w-[900px] px-5 py-10 sm:px-8">
        <h1 className="font-display text-[30px] leading-tight tracking-[-0.02em]">
          Search the corpus
        </h1>
        <p className="mt-2 max-w-[58ch] text-[14px] leading-relaxed text-[hsl(var(--ink-3))]">
          Meaning and keywords together, over every section of the six indexed
          Acts. No model is called, so this costs nothing and needs no key.
        </p>

        <div className="ask-composer mt-6 flex items-center gap-3">
          <SearchIcon size={16} className="shrink-0 text-[hsl(var(--ink-4))]" />
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="restraint of trade, registration of leases, security safeguards…"
            className="w-full bg-transparent text-[15px] text-[hsl(var(--ink))] outline-none placeholder:text-[hsl(var(--ink-4))]"
          />
          {isFetching && (
            <LoaderCircle
              size={14}
              className="animate-spin text-[hsl(var(--ink-4))]"
            />
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <div className="select-wrap">
            <select
              value={slug}
              onChange={(event) => setParam("act", event.target.value)}
              className="bg-transparent text-[12px] font-medium text-[hsl(var(--ink-2))] outline-none"
              aria-label="Restrict to one Act"
            >
              <option value="">All indexed Acts</option>
              {statutes?.map((statute) => (
                <option key={statute.slug} value={statute.slug}>
                  {statute.short_title}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 text-[12px] text-[hsl(var(--ink-3))]">
            <input
              type="checkbox"
              checked={includeOmitted}
              onChange={(event) =>
                setParam("omitted", event.target.checked ? "1" : "")
              }
            />
            Include repealed provisions
          </label>
        </div>

        {error && (
          <p className="mt-6 text-[13px] text-[hsl(var(--ink-3))]">
            That search failed.
          </p>
        )}

        {data && (
          <>
            <div className="mt-7 flex items-center justify-between">
              <div className="meta-label">
                {data.total} {data.total === 1 ? "section" : "sections"}
              </div>
              {/*
                `reranked: false` is the server telling us search skips the
                cross-encoder to stay fast. So results are fusion order, and
                this must not be sold as "best match".
              */}
              <span className="text-[11px] text-[hsl(var(--ink-4))]">
                ranked by combined keyword and meaning
              </span>
            </div>
            <div className="mt-3 grid gap-2">
              {data.hits.map((hit) => (
                <Link
                  key={hit.section_id}
                  to={`/sections/${hit.section_id}`}
                  className="list-card"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 className="text-[15px] font-semibold text-[hsl(var(--ink))]">
                      s. {hit.section_no}
                      {hit.marginal_note
                        ? ` · ${hit.marginal_note.replace(/\.$/, "")}`
                        : ""}
                    </h2>
                    <span className="text-[11px] text-[hsl(var(--ink-4))]">
                      {hit.statute}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-[hsl(var(--ink-2))]">
                    {hit.snippet}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-3 text-[10.5px] uppercase tracking-[0.08em] text-[hsl(var(--ink-4))]">
                    {hit.dense_rank !== null && (
                      <span>meaning #{hit.dense_rank}</span>
                    )}
                    {hit.sparse_rank !== null && (
                      <span>keyword #{hit.sparse_rank}</span>
                    )}
                  </div>
                </Link>
              ))}
            </div>
            {data.total === 0 && (
              <p className="mt-6 text-[13px] leading-relaxed text-[hsl(var(--ink-3))]">
                Nothing in the six indexed Acts matched that. The corpus holds
                no case law, no state amendments and no rules or notifications.
              </p>
            )}
          </>
        )}
      </div>
    </LegalAssistLayout>
  );
}
