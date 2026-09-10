import { LoaderCircle, Scale } from "lucide-react";
import type { StatuteSection } from "@/lib/legal-data";
import { citationLabel } from "@/lib/legal-data";
import { cn } from "@/lib/utils";

export function CitationChip({
  section,
  onClick,
  resolving = false,
}: {
  section: StatuteSection;
  onClick: () => void;
  resolving?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "citation-chip group",
        resolving && "cursor-wait opacity-70",
      )}
      aria-label={`Open ${citationLabel(section)}`}
    >
      {resolving ? <LoaderCircle size={12} className="animate-spin" /> : <Scale size={12} />}
      <span>{citationLabel(section)}</span>
    </button>
  );
}
