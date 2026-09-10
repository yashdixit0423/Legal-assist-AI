import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpenText, ChevronDown, ChevronRight, ExternalLink, FileText, Filter, Search } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import { AsOfBadge, SectionReader } from "@/components/SectionReader";
import { sections, statutes, type Statute } from "@/lib/legal-data";
import { cn } from "@/lib/utils";

function getSection(slug: string, number?: string) {
  const sectionId = slug.startsWith("contract") ? "contract-27" : slug.startsWith("registration") ? "registration-17" : slug.startsWith("arbitration") ? "arbitration-21" : "it-43";
  const section = sections.find((item) => item.id === sectionId) ?? sections[0];
  return number && number !== section.number ? { ...section, number, heading: `Section ${number}`, text: "This section is indexed in the corpus. Open the source portal for the complete provision text.", explanation: "The section reader keeps the exact source text and the explanation in separate layers so the law remains easy to verify." } : section;
}

function CorpusSearch() {
  const [query, setQuery] = useState("");
  const [statuteFilter, setStatuteFilter] = useState("All statutes");
  const [chapterFilter, setChapterFilter] = useState("All chapters");
  const results = useMemo(() => {
    const normalized = query.toLowerCase().trim();
    if (!normalized) return [];
    return sections.filter((section) => {
      const matchesQuery = `${section.act} ${section.heading} ${section.text}`.toLowerCase().includes(normalized);
      const matchesStatute = statuteFilter === "All statutes" || section.act.includes(statuteFilter);
      const matchesChapter = chapterFilter === "All chapters" ||
        (chapterFilter === "Contracts" && section.act.includes("Contract")) ||
        (chapterFilter === "Registrable Documents" && section.act.includes("Registration")) ||
        (chapterFilter === "Arbitration" && section.act.includes("Arbitration"));
      return matchesQuery && matchesStatute && matchesChapter;
    });
  }, [query, statuteFilter, chapterFilter]);

  return (
    <section className="mb-12 rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-5 sm:p-7">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><div className="eyebrow"><Search size={13} /> Corpus search</div><h2 className="mt-2 font-display text-2xl">Find a phrase in the law</h2><p className="mt-1 text-sm text-[hsl(var(--ink-3))]">Search across the indexed statute text. No API key required.</p></div><span className="inline-flex items-center gap-2 text-xs font-semibold text-[hsl(var(--brand))]"><span className="status-dot" /> Search is local to this corpus</span></div>
      <div className="mt-6 flex flex-col gap-2 lg:flex-row"><div className="relative min-w-0 flex-1"><Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[hsl(var(--ink-4))]" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Try “restraint of trade” or “registered”" className="h-11 w-full rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas))] pl-10 pr-4 text-sm text-[hsl(var(--ink))] outline-none placeholder:text-[hsl(var(--ink-4))] focus:border-[hsl(var(--brand))]" /></div><label className="select-wrap"><Filter size={14} /><select value={statuteFilter} onChange={(event) => setStatuteFilter(event.target.value)}><option>All statutes</option>{statutes.map((statute) => <option key={statute.slug}>{statute.shortTitle}</option>)}</select><ChevronDown size={13} /></label><label className="select-wrap hidden sm:flex"><select value={chapterFilter} onChange={(event) => setChapterFilter(event.target.value)}><option>All chapters</option><option>Contracts</option><option>Registrable Documents</option><option>Arbitration</option></select><ChevronDown size={13} /></label></div>
      {query && <div className="mt-5 border-t border-[hsl(var(--line))] pt-4">{results.length ? results.map((result) => <button key={result.id} className="group mb-2 block w-full rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas))] p-4 text-left last:mb-0 hover:border-[hsl(var(--brand))]"><div className="flex items-center justify-between gap-3"><div className="text-xs font-bold text-[hsl(var(--brand))]">S. {result.number} · {result.shortAct}</div><ArrowRight size={14} className="text-[hsl(var(--ink-4))] transition group-hover:translate-x-0.5 group-hover:text-[hsl(var(--brand))]" /></div><div className="mt-1 text-sm font-semibold text-[hsl(var(--ink))]">{result.heading}</div><p className="mt-1 line-clamp-2 text-xs leading-5 text-[hsl(var(--ink-3))]">{result.text}</p></button>) : <p className="text-sm text-[hsl(var(--ink-3))]">No matching section in the indexed corpus. Try a phrase from a statute or clear the filters.</p>}</div>}
    </section>
  );
}

function StatuteList() {
  const [query, setQuery] = useState("");
  const [jurisdiction, setJurisdiction] = useState("All jurisdictions");
  const [tier, setTier] = useState("All tiers");
  const filtered = statutes.filter((statute) => statute.title.toLowerCase().includes(query.toLowerCase()) && (jurisdiction === "All jurisdictions" || statute.jurisdiction === jurisdiction) && (tier === "All tiers" || statute.tier === tier));

  return (
    <section>
      <div className="mb-5 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><div className="eyebrow"><BookOpenText size={13} /> Statute list</div><h2 className="mt-2 font-display text-3xl">The indexed corpus</h2></div><span className="text-xs text-[hsl(var(--ink-3))]">{filtered.length} of {statutes.length} Acts</span></div>
      <div className="mb-4 flex flex-col gap-2 sm:flex-row"><div className="relative min-w-0 flex-1"><Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[hsl(var(--ink-4))]" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search Act titles" className="h-10 w-full rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] pl-9 pr-3 text-sm outline-none placeholder:text-[hsl(var(--ink-4))] focus:border-[hsl(var(--brand))]" /></div><label className="select-wrap"><select value={jurisdiction} onChange={(event) => setJurisdiction(event.target.value)}><option>All jurisdictions</option><option>India</option></select><ChevronDown size={13} /></label><label className="select-wrap"><select value={tier} onChange={(event) => setTier(event.target.value)}><option>All tiers</option><option>Central</option></select><ChevronDown size={13} /></label></div>
      <div className="overflow-hidden rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))]"><div className="hidden grid-cols-[minmax(0,1.5fr)_110px_120px_130px_120px] gap-4 border-b border-[hsl(var(--line))] px-5 py-3 text-[10px] font-bold uppercase tracking-[0.15em] text-[hsl(var(--ink-4))] md:grid"><span>Act</span><span>Jurisdiction</span><span>Sections</span><span>As of</span><span /></div>{filtered.map((statute) => <Link to={`/browse/${statute.slug}`} key={statute.slug} className="group grid gap-3 border-b border-[hsl(var(--line))] px-5 py-4 last:border-b-0 hover:bg-[hsl(var(--canvas))] md:grid-cols-[minmax(0,1.5fr)_110px_120px_130px_120px] md:items-center md:gap-4"><div><div className="flex flex-wrap items-center gap-2"><span className="font-display text-lg text-[hsl(var(--ink))] group-hover:text-[hsl(var(--brand))]">{statute.shortTitle}</span>{statute.repealed && <span className="rounded-full border border-[hsl(var(--line-strong))] px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.12em] text-[hsl(var(--ink-3))]">Repealed</span>}</div><div className="mt-1 text-xs text-[hsl(var(--ink-3))]">{statute.year} · {statute.actNumber}</div></div><div className="text-xs text-[hsl(var(--ink-2))] md:block"><span className="mr-2 text-[10px] uppercase tracking-wider text-[hsl(var(--ink-4))] md:hidden">Jurisdiction</span>{statute.jurisdiction}</div><div className="text-xs text-[hsl(var(--ink-2))]"><span className="mr-2 text-[10px] uppercase tracking-wider text-[hsl(var(--ink-4))] md:hidden">Sections</span>{statute.sections}</div><div className="text-xs text-[hsl(var(--ink-3))]"><span className="mr-2 text-[10px] uppercase tracking-wider text-[hsl(var(--ink-4))] md:hidden">As of</span>{statute.asOf}</div><div className="flex items-center gap-2 text-xs font-bold text-[hsl(var(--brand))] md:justify-end">View Act <ChevronRight size={14} className="transition group-hover:translate-x-0.5" /></div></Link>)}</div>
    </section>
  );
}

function BrowseIndex() {
  return <LegalAssistLayout><div className="mx-auto max-w-[1440px] px-5 pb-16 pt-10 sm:px-8 lg:px-10 lg:pt-14"><div className="mb-10 flex flex-col justify-between gap-5 border-b border-[hsl(var(--line))] pb-8 lg:flex-row lg:items-end"><div><div className="eyebrow"><span className="eyebrow-dot" /> Reading room · no key required</div><h1 className="mt-3 font-display text-5xl tracking-[-0.045em]">Browse the law.</h1><p className="mt-3 max-w-xl text-sm leading-6 text-[hsl(var(--ink-2))]">Explore the indexed Acts, search their text, and open any section with its source text front and centre.</p></div><div className="flex items-center gap-2 text-xs text-[hsl(var(--ink-3))]"><FileText size={14} className="text-[hsl(var(--brand))]" /> {statutes.length} central Acts indexed</div></div><CorpusSearch /><StatuteList /></div></LegalAssistLayout>;
}

function ActPage({ statute }: { statute: Statute }) {
  const [selectedNumber, setSelectedNumber] = useState(statute.chapters[0].sections[0]);
  const selected = getSection(statute.slug, selectedNumber);
  return <LegalAssistLayout><div className="mx-auto max-w-[1440px] px-5 pb-16 pt-8 sm:px-8 lg:px-10 lg:pt-10"><Link to="/browse" className="mb-6 inline-flex items-center gap-2 text-xs font-bold text-[hsl(var(--ink-3))] hover:text-[hsl(var(--brand))]"><ArrowLeft size={14} /> All indexed Acts</Link><section className="statute-header"><div className="flex flex-col justify-between gap-6 lg:flex-row"><div><div className="eyebrow"><span className="eyebrow-dot" /> {statute.tier} statute · {statute.year}</div><h1 className="mt-3 max-w-3xl font-display text-4xl leading-tight tracking-[-0.04em] sm:text-5xl">{statute.title}</h1><p className="mt-4 max-w-2xl text-sm leading-6 text-[hsl(var(--ink-2))]">{statute.longTitle}</p></div><div className="flex shrink-0 flex-col items-start gap-2 text-xs text-[hsl(var(--ink-3))] lg:items-end"><AsOfBadge date={statute.asOf} /><span>{statute.sections} sections indexed</span></div></div><div className="mt-7 grid gap-4 border-t border-[hsl(var(--line))] pt-5 text-xs sm:grid-cols-3"><div><div className="meta-label">Act number</div><div className="mt-1 font-semibold text-[hsl(var(--ink-2))]">{statute.actNumber}</div></div><div><div className="meta-label">Issuing ministry</div><div className="mt-1 font-semibold text-[hsl(var(--ink-2))]">{statute.ministry}</div></div><a href={statute.sourceUrl} target="_blank" rel="noreferrer" className="group flex items-center gap-1.5 font-bold text-[hsl(var(--brand))] hover:underline">Original source portal <ExternalLink size={13} className="transition group-hover:translate-x-0.5" /></a></div></section><div className="mt-8 grid gap-7 lg:grid-cols-[260px_minmax(0,1fr)]"><aside className="chapter-nav"><div className="mb-3 flex items-center justify-between"><span className="meta-label">Contents</span><span className="text-[10px] text-[hsl(var(--ink-4))]">{statute.sections} §§</span></div>{statute.chapters.map((chapter) => <div key={chapter.label} className="mb-4"><div className="mb-1 flex items-center gap-1 text-[11px] font-bold text-[hsl(var(--ink-2))]"><ChevronDown size={13} /> {chapter.label}</div>{chapter.sections.map((number) => <button key={number} onClick={() => setSelectedNumber(number)} className={cn("chapter-link", selectedNumber === number && "chapter-link-active")}><span>S. {number}</span><span className="truncate text-[hsl(var(--ink-3))]">{number === "27" ? "Restraint of trade" : number === "17" ? "Compulsory registration" : number === "21" ? "Arbitral proceedings" : "Provision text"}</span></button>)}</div>)}</aside><div className="min-w-0"><div className="mb-3 flex items-center justify-between"><div className="eyebrow"><BookOpenText size={13} /> Section reader</div><span className="text-xs text-[hsl(var(--ink-3))]">Verbatim source</span></div><SectionReader section={selected} /><div className="mt-8"><h2 className="font-display text-2xl">Related provisions</h2><div className="mt-4 grid gap-2 sm:grid-cols-2">{selected.related.map((related) => <button key={related} className="flex items-center justify-between rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-4 py-3 text-left text-sm font-semibold text-[hsl(var(--ink-2))] hover:border-[hsl(var(--brand))] hover:text-[hsl(var(--brand))]"><span>{related}</span><ChevronRight size={15} /></button>)}</div></div></div></div></div></LegalAssistLayout>;
}

export default function Browse() {
  const { slug } = useParams();
  const statute = statutes.find((item) => item.slug === slug);
  return statute ? <ActPage statute={statute} /> : <BrowseIndex />;
}
