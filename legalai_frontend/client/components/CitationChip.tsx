import { LoaderCircle, Scale } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import type { SourceBlock } from "@/lib/api/types";

/**
 * An inline citation in an answer.
 *
 * Labelled from the source block the server sent, never from the raw marker:
 * the model may write `[S19(c)]` or `[S18(1)(d), S1107]`, and a reader wants
 * "Registration Act, 1908 · s. 18", not an internal id. Links to the section
 * so the claim can be checked against the text — that is the entire point.
 */
export function CitationChip({
  sectionId,
  source,
  resolving = false,
}: {
  sectionId: number;
  source?: SourceBlock;
  resolving?: boolean;
}) {
  const label = source
    ? `${shortStatute(source.statute)} · s. ${source.section_no}`
    : `Section ${sectionId}`;

  return (
    <Link
      to={`/sections/${sectionId}`}
      className={cn(
        "citation-chip group",
        resolving && "cursor-wait opacity-70",
      )}
      title={source?.marginal_note ?? `Open section ${sectionId}`}
      aria-label={`Open ${label}`}
    >
      {resolving ? (
        <LoaderCircle size={12} className="animate-spin" />
      ) : (
        <Scale size={12} />
      )}
      <span>{label}</span>
    </Link>
  );
}

/** "Transfer of Property Act, 1882" reads better than the full title inline. */
export function shortStatute(title: string): string {
  return title
    .replace(/^(The|Indian)\s+/i, "")
    .replace(/\s+Act,?\s+/i, " Act ");
}
