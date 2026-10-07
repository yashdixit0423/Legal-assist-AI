import { CitationChip } from "@/components/CitationChip";
import { parseAnswer } from "@/lib/api/ask";
import type { SourceBlock } from "@/lib/api/types";

/** Answer prose with each `[S<id>]` marker rendered as the shared citation chip. */
export function AnswerText({
  text,
  sources,
}: {
  text: string;
  sources: SourceBlock[];
}) {
  const byId = new Map(sources.map((source) => [source.section_id, source]));
  return (
    <>
      {parseAnswer(text).map((part, index) =>
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
    </>
  );
}
