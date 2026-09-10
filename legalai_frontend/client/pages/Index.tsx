import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BookOpenText, Check, ChevronRight, CircleHelp, LockKeyhole, MessageCircle, Search, Sparkles } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { AskComposer } from "@/components/AskComposer";
import { CitationChip } from "@/components/CitationChip";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import { ReaderEmptyState, SectionReader } from "@/components/SectionReader";
import { sections, statutes } from "@/lib/legal-data";
import { useModelConfigurations } from "@/hooks/use-model-configurations";

const suggestedQuestions = [
  "Is a non-compete after employment enforceable in India?",
  "When must a rent agreement be registered?",
  "What notice does the Arbitration Act require before invoking arbitration?",
  "Can an online agreement be treated as a contract?",
];

const answerBeforeCitation = "A post-employment non-compete is generally not enforceable in India. The starting point is Section 27 of the Indian Contract Act, 1872, which makes agreements restraining a lawful profession, trade or business void to that extent.";
const answerAfterCitation = "There is a narrow exception for the sale of goodwill, but it is limited to the boundaries described in the section. The surrounding facts and the exact wording of the agreement still matter.";

function SourceList() {
  return (
    <div className="mt-5 border-t border-[hsl(var(--line))] pt-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-[hsl(var(--ink-3))]">Sources used</div>
        <span className="text-[11px] text-[hsl(var(--ink-4))]">1 section</span>
      </div>
      <div className="divide-y divide-[hsl(var(--line))] rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))]">
        <div className="flex items-start justify-between gap-4 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-[hsl(var(--ink))]">S. 27 · Agreement in restraint of trade</div>
            <div className="mt-1 text-xs text-[hsl(var(--ink-3))]">Indian Contract Act, 1872</div>
          </div>
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.1em] text-[hsl(var(--ink-4))]">31 Mar 2024</span>
        </div>
      </div>
    </div>
  );
}

function AskPage() {
  const location = useLocation();
  const configuredModels = useModelConfigurations();
  const initialQuestion = (location.state as { question?: string } | null)?.question ?? "";
  const [selectedModelId, setSelectedModelId] = useState(() => sessionStorage.getItem("legalassist-chat-model") || configuredModels[0]?.id);
  const [selectedSection, setSelectedSection] = useState<null | typeof sections[number]>(null);
  const [question, setQuestion] = useState(() => configuredModels.length > 0 ? initialQuestion : "");
  const [streamedLength, setStreamedLength] = useState(0);
  const [isStreaming, setIsStreaming] = useState(false);
  const hasKey = configuredModels.length > 0;
  const selectedModel = configuredModels.find((model) => model.id === selectedModelId);
  const totalAnswerLength = answerBeforeCitation.length + answerAfterCitation.length;
  const hasQuestion = Boolean(question);
  const isAbstention = question.toLowerCase().includes("immigration") || question.toLowerCase().includes("criminal bail");

  useEffect(() => {
    if (selectedModelId && configuredModels.some((model) => model.id === selectedModelId)) return;
    const nextModelId = configuredModels[0]?.id;
    setSelectedModelId(nextModelId);
    if (nextModelId) sessionStorage.setItem("legalassist-chat-model", nextModelId);
  }, [configuredModels, selectedModelId]);

  useEffect(() => {
    if (!question || isAbstention) return;
    setStreamedLength(0);
    setIsStreaming(true);
    const timer = window.setInterval(() => {
      setStreamedLength((current) => {
        if (current >= totalAnswerLength) {
          window.clearInterval(timer);
          setIsStreaming(false);
          return totalAnswerLength;
        }
        return Math.min(current + 4, totalAnswerLength);
      });
    }, 24);
    return () => window.clearInterval(timer);
  }, [question, isAbstention, totalAnswerLength]);

  const before = answerBeforeCitation.slice(0, Math.min(streamedLength, answerBeforeCitation.length));
  const after = streamedLength > answerBeforeCitation.length ? answerAfterCitation.slice(0, streamedLength - answerBeforeCitation.length) : "";
  const citationReady = streamedLength >= answerBeforeCitation.length;

  const selectModel = (modelId: string) => {
    setSelectedModelId(modelId);
    sessionStorage.setItem("legalassist-chat-model", modelId);
  };

  const submitQuestion = (value: string, modelId?: string) => {
    if (modelId) selectModel(modelId);
    setSelectedSection(null);
    setQuestion(value);
  };

  return (
    <LegalAssistLayout>
      <div className="mx-auto max-w-[1440px] px-5 pb-12 pt-10 sm:px-8 lg:px-10 lg:pt-14">
        <div className="mb-8 flex flex-col justify-between gap-5 border-b border-[hsl(var(--line))] pb-7 lg:flex-row lg:items-end">
          <div>
            <div className="eyebrow"><span className="eyebrow-dot" /> Fixed corpus · Indian law</div>
            <h1 className="mt-3 max-w-2xl font-display text-4xl leading-[1.06] tracking-[-0.045em] text-[hsl(var(--ink))] sm:text-5xl">Ask the law.<br /><span className="text-[hsl(var(--brand))]">See the source.</span></h1>
            <p className="mt-4 max-w-xl text-sm leading-6 text-[hsl(var(--ink-2))]">LegalAssist answers from a fixed corpus of Indian statutes, with the exact provision one click away. No black boxes between you and the text.</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-[hsl(var(--ink-3))]">
            <span className="status-dot" /> Corpus indexed through 31 Mar 2024
            <Link to="/browse" className="font-bold text-[hsl(var(--brand))] hover:underline">Explore <ArrowRight size={13} className="ml-1 inline" /></Link>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.12fr)_minmax(360px,.88fr)]">
          <section className="min-w-0">
            <AskComposer hasKey={hasKey} configuredModels={configuredModels} selectedModelId={selectedModelId} onModelSelect={selectModel} initialValue={hasKey ? initialQuestion : ""} onSubmit={submitQuestion} />
            <div className="mt-3 flex items-center gap-2 text-[11px] text-[hsl(var(--ink-3))]"><LockKeyhole size={12} /> This conversation isn&apos;t saved. Reloading starts a new one.</div>

            {!hasQuestion ? (
              <div className="mt-14">
                <div className="mb-5 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-[hsl(var(--ink-3))]"><Sparkles size={14} className="text-[hsl(var(--brand))]" /> Try a question</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {suggestedQuestions.map((suggestion) => (
                    <button key={suggestion} onClick={() => hasKey && submitQuestion(suggestion)} disabled={!hasKey} className="suggestion-card group text-left disabled:cursor-not-allowed disabled:opacity-65">
                      <span>{suggestion}</span><ChevronRight size={15} className="shrink-0 text-[hsl(var(--ink-4))] transition group-hover:translate-x-0.5 group-hover:text-[hsl(var(--brand))]" />
                    </button>
                  ))}
                </div>
                {!hasKey && <p className="mt-4 flex items-center gap-2 text-xs text-[hsl(var(--ink-3))]"><CircleHelp size={14} className="text-[hsl(var(--brand))]" /> Add your own key to start asking. Browsing the corpus never requires a key.</p>}
              </div>
            ) : isAbstention ? (
              <AbstentionNotice />
            ) : (
              <div className="mt-12">
                <div className="mb-4 flex items-center justify-between gap-4 text-[11px] text-[hsl(var(--ink-3))]"><span className="font-bold uppercase tracking-[0.16em]">Answer</span><span className="inline-flex min-w-0 items-center gap-1.5"><MessageCircle size={13} /> <span className="truncate">{question}</span>{selectedModel && <span className="hidden shrink-0 text-[hsl(var(--ink-4))] sm:inline">via {selectedModel.name}</span>}</span></div>
                <div className="answer-card">
                  <div className="mb-4 flex items-center gap-2 text-xs font-semibold text-[hsl(var(--brand))]"><span className="h-5 w-5 rounded-md bg-[hsl(var(--brand-soft))]" /> LegalAssist explanation</div>
                  <p className="text-[15px] leading-7 text-[hsl(var(--ink-2))]">
                    {before}
                    {citationReady && <>{" "}<CitationChip section={sections[0]} resolving={isStreaming} onClick={() => !isStreaming && setSelectedSection(sections[0])} /></>}
                    {" "}{after}
                    {isStreaming && <span className="stream-caret" />}
                  </p>
                  <SourceList />
                </div>
              </div>
            )}
          </section>

          <aside className="min-w-0">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-[hsl(var(--ink-3))]"><BookOpenText size={14} className="text-[hsl(var(--brand))]" /> Section reader</div>
              {selectedSection && <button onClick={() => setSelectedSection(null)} className="text-xs font-semibold text-[hsl(var(--ink-3))] hover:text-[hsl(var(--ink))]">Clear</button>}
            </div>
            <div className="section-panel lg:sticky lg:top-[96px]">
              {selectedSection ? <SectionReader section={selectedSection} compact /> : <ReaderEmptyState />}
            </div>
          </aside>
        </div>
      </div>
    </LegalAssistLayout>
  );
}

function AbstentionNotice() {
  return (
    <div className="mt-12 rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-6 sm:p-7">
      <div className="mb-4 flex h-9 w-9 items-center justify-center rounded-xl bg-[hsl(var(--brand-soft))] text-[hsl(var(--brand))]"><CircleHelp size={18} /></div>
      <div className="eyebrow">Outside this corpus</div>
      <h2 className="mt-2 font-display text-2xl text-[hsl(var(--ink))]">That topic isn&apos;t indexed yet.</h2>
      <p className="mt-3 max-w-xl text-sm leading-6 text-[hsl(var(--ink-2))]">LegalAssist currently covers selected central Indian statutes, including contracts, registration, arbitration and information technology. Try asking about a provision in one of those Acts, or browse the full corpus.</p>
      <Link to="/browse" className="mt-5 inline-flex items-center gap-2 text-sm font-bold text-[hsl(var(--brand))] hover:underline">Search the corpus <ArrowRight size={15} /></Link>
    </div>
  );
}

function LandingPage() {
  const [question, setQuestion] = useState("");
  const configuredModels = useModelConfigurations();
  const hasKey = configuredModels.length > 0;
  const corpus = useMemo(() => statutes.slice(0, 4), []);

  return (
    <LegalAssistLayout>
      <section className="landing-hero">
        <div className="mx-auto grid max-w-[1440px] items-center gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[1.05fr_.95fr] lg:px-10 lg:py-24">
          <div>
            <div className="eyebrow"><span className="eyebrow-dot" /> Grounded in the law, not just language</div>
            <h1 className="mt-5 max-w-3xl font-display text-5xl leading-[.98] tracking-[-0.055em] text-[hsl(var(--ink))] sm:text-7xl">A clearer way to<br /><span className="text-[hsl(var(--brand))]">read the law.</span></h1>
            <p className="mt-6 max-w-xl text-base leading-7 text-[hsl(var(--ink-2))]">Ask questions about Indian law and get an explanation anchored to the exact statute text. Every answer shows you where it comes from.</p>
            <div className="mt-9 flex flex-wrap items-center gap-4">
              <Link to="/ask" className="inline-flex h-11 items-center gap-2 rounded-xl bg-[hsl(var(--brand))] px-5 text-sm font-bold text-[hsl(var(--brand-foreground))] shadow-[0_8px_20px_hsl(var(--brand)/.18)] transition hover:bg-[hsl(var(--brand-strong))]">Ask a question <ArrowRight size={16} /></Link>
              <Link to="/browse" className="inline-flex h-11 items-center gap-2 rounded-xl border border-[hsl(var(--line-strong))] px-5 text-sm font-bold text-[hsl(var(--ink-2))] transition hover:border-[hsl(var(--brand))] hover:text-[hsl(var(--brand))]">Browse the law</Link>
            </div>
            <div className="mt-7 flex items-center gap-2 text-xs text-[hsl(var(--ink-3))]"><Check size={14} className="text-[hsl(var(--brand))]" /> A focused corpus, current as of 31 March 2024.</div>
          </div>
          <div className="landing-question-card">
            <div className="mb-5 flex items-center justify-between"><div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-[hsl(var(--ink-3))]"><MessageCircle size={15} className="text-[hsl(var(--brand))]" /> Start with a question</div><span className="rounded-full bg-[hsl(var(--brand-soft))] px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-[hsl(var(--brand))]">Example</span></div>
            <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Is a non-compete after employment enforceable in India?" className="min-h-[150px] w-full resize-none rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-4 text-sm leading-6 text-[hsl(var(--ink))] outline-none transition placeholder:text-[hsl(var(--ink-3))] focus:border-[hsl(var(--brand))]" />
            <div className="mt-4 flex items-center justify-between gap-4"><span className="text-[11px] leading-5 text-[hsl(var(--ink-3))]">Answers cite verbatim sections from the indexed corpus.</span><Link to="/ask" state={{ question }} className="inline-flex h-10 shrink-0 items-center gap-2 rounded-lg bg-[hsl(var(--brand))] px-3.5 text-xs font-bold text-[hsl(var(--brand-foreground))]">Continue <ArrowRight size={14} /></Link></div>
            {!hasKey && <div className="mt-4 flex items-center gap-2 border-t border-[hsl(var(--line))] pt-4 text-xs text-[hsl(var(--ink-3))]"><LockKeyhole size={13} className="text-[hsl(var(--brand))]" /> Bring your own API key in Settings to ask.</div>}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-[1440px] px-5 py-16 sm:px-8 lg:px-10 lg:py-24">
        <div className="grid gap-10 lg:grid-cols-[.8fr_1.2fr]">
          <div><div className="eyebrow">What&apos;s inside</div><h2 className="mt-3 max-w-md font-display text-4xl leading-tight tracking-[-0.04em]">A small corpus, read properly.</h2><p className="mt-4 max-w-md text-sm leading-6 text-[hsl(var(--ink-2))]">Phase 1.1 is intentionally focused: a fixed set of central statutes, indexed with their source text and section structure.</p><Link to="/browse" className="mt-6 inline-flex items-center gap-2 text-sm font-bold text-[hsl(var(--brand))] hover:underline">See all indexed Acts <ArrowRight size={15} /></Link></div>
          <div className="divide-y divide-[hsl(var(--line))] rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))]">{corpus.map((statute, index) => <Link to={`/browse/${statute.slug}`} key={statute.slug} className="group flex items-center justify-between gap-5 px-5 py-5 transition hover:bg-[hsl(var(--canvas))] sm:px-7"><div className="flex items-start gap-4"><span className="font-mono text-xs text-[hsl(var(--ink-4))]">0{index + 1}</span><div><div className="font-display text-lg text-[hsl(var(--ink))] group-hover:text-[hsl(var(--brand))]">{statute.shortTitle}</div><div className="mt-1 text-xs text-[hsl(var(--ink-3))]">{statute.sections} sections · As of {statute.asOf}</div></div></div><ArrowRight size={16} className="shrink-0 text-[hsl(var(--ink-4))] transition group-hover:translate-x-1 group-hover:text-[hsl(var(--brand))]" /></Link>)}</div>
        </div>
      </section>

      <section className="border-y border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))]"><div className="mx-auto grid max-w-[1440px] gap-10 px-5 py-16 sm:px-8 lg:grid-cols-3 lg:px-10 lg:py-20"><div><div className="feature-icon"><BookOpenText size={18} /></div><h3 className="mt-4 font-display text-2xl">The statute is the hero</h3><p className="mt-2 text-sm leading-6 text-[hsl(var(--ink-2))]">Explanations stay subordinate. The exact words of the law are always the focal point.</p></div><div><div className="feature-icon"><Search size={18} /></div><h3 className="mt-4 font-display text-2xl">Verify in one click</h3><p className="mt-2 text-sm leading-6 text-[hsl(var(--ink-2))]">Citations open the exact section, with as-of dates and related provisions alongside it.</p></div><div><div className="feature-icon"><LockKeyhole size={18} /></div><h3 className="mt-4 font-display text-2xl">Bring your own key</h3><p className="mt-2 text-sm leading-6 text-[hsl(var(--ink-2))]">Your provider key is encrypted and never leaves the server. Reading the corpus is always free.</p></div></div></section>

      <section className="mx-auto max-w-[1440px] px-5 py-14 text-center sm:px-8 lg:px-10"><p className="mx-auto max-w-2xl text-xs leading-5 text-[hsl(var(--ink-3))]"><strong className="font-bold text-[hsl(var(--ink-2))]">Important:</strong> LegalAssist AI provides information grounded in the indexed statute corpus for educational purposes. It is not legal advice and does not replace advice from a qualified legal professional.</p></section>
    </LegalAssistLayout>
  );
}

export default function Index() {
  return <LandingPage />;
}

export { AskPage };
