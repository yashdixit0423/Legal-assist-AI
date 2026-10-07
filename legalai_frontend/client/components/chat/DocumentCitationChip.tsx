import { FileText } from "lucide-react";
import type { DocumentSourceBlock } from "@/lib/api/types";
import { displayName } from "@/lib/chat/files";
import { locatorLabel } from "@/lib/chat/citations";

/**
 * A citation to the user's own document. Same chip surface as a statute
 * citation, but a document icon instead of the scales, so the two kinds are
 * told apart without relying on colour.
 */
export function DocumentCitationChip({
  citationId,
  source,
  onOpen,
}: {
  citationId: string;
  source?: DocumentSourceBlock;
  onOpen?: (source: DocumentSourceBlock) => void;
}) {
  const label = source
    ? `${displayName(source.filename, 24)} · ${locatorLabel(source.locator_kind, source.locator)}`
    : citationId;
  return (
    <button
      type="button"
      onClick={() => source && onOpen?.(source)}
      disabled={!source}
      className="citation-chip group"
      title={source ? `Your document: ${source.filename}` : citationId}
      aria-label={`Open ${label} from your document`}
    >
      <FileText size={12} />
      <span>{label}</span>
    </button>
  );
}
