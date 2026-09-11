import { LoaderCircle } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import { SectionReader } from "@/components/SectionReader";
import { getSection, getSectionByNumber } from "@/lib/api/corpus";

/**
 * Where a citation chip lands. Deep-linkable by id, and by Act + section
 * number — the API resolves 21A, 21-A and 21 a to the same provision, so a
 * reader typing the form they saw in a judgment does not get a 404.
 */
export default function Section() {
  const { sectionId, slug, sectionNo } = useParams();
  const byId = sectionId !== undefined;

  const { data, isLoading, error } = useQuery({
    queryKey: byId ? ["section", sectionId] : ["section", slug, sectionNo],
    queryFn: () =>
      byId
        ? getSection(Number(sectionId))
        : getSectionByNumber(slug!, sectionNo!),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <LegalAssistLayout>
      <div className="mx-auto max-w-[840px] px-5 py-10 sm:px-8">
        {data && (
          <Link
            to={`/browse/${data.statute_slug}`}
            className="mb-4 inline-block text-[12px] text-[hsl(var(--brand))] hover:underline"
          >
            ← {data.statute_short_title}
          </Link>
        )}
        {isLoading && (
          <div className="flex items-center gap-2 text-[13px] text-[hsl(var(--ink-3))]">
            <LoaderCircle size={14} className="animate-spin" /> Loading the
            provision…
          </div>
        )}
        {error && (
          <p className="text-[13px] text-[hsl(var(--ink-3))]">
            That section is not in the corpus.{" "}
            <Link
              to="/browse"
              className="text-[hsl(var(--brand))] hover:underline"
            >
              Browse the Acts
            </Link>
            .
          </p>
        )}
        {data && <SectionReader section={data} />}
      </div>
    </LegalAssistLayout>
  );
}
