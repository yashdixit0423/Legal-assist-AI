import { useRef, useState } from "react";
import { FileUp } from "lucide-react";
import { FORMATS_LABEL } from "@/lib/chat/files";

const carriesFiles = (event: React.DragEvent) =>
  Array.from(event.dataTransfer.types).includes("Files");

/**
 * Drop target over the conversation. `dragenter`/`dragleave` fire for every
 * child crossed, so a depth counter — not the last event — decides whether
 * the overlay shows; otherwise it flickers as the pointer moves.
 */
export function DocumentDropZone({
  onFiles,
  disabled = false,
  children,
}: {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const depth = useRef(0);
  const [active, setActive] = useState(false);

  if (disabled) return <>{children}</>;

  return (
    <div
      className="relative flex min-h-0 flex-1 flex-col"
      onDragEnter={(event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        depth.current += 1;
        setActive(true);
      }}
      onDragOver={(event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={(event) => {
        if (!carriesFiles(event)) return;
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setActive(false);
      }}
      onDrop={(event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        depth.current = 0;
        setActive(false);
        const files = Array.from(event.dataTransfer.files);
        if (files.length) onFiles(files);
      }}
    >
      {children}
      {active && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-2 z-20 flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-[hsl(var(--line-strong))] bg-[hsl(var(--brand-soft)/.85)] text-center"
        >
          <FileUp size={22} className="text-[hsl(var(--brand))]" />
          <p className="text-[14px] font-semibold text-[hsl(var(--ink))]">
            Drop your legal document here
          </p>
          <p className="text-[12px] text-[hsl(var(--ink-3))]">
            {FORMATS_LABEL} up to 10 MB
          </p>
        </div>
      )}
    </div>
  );
}
