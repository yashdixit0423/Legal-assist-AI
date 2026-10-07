import { useRef } from "react";
import { Paperclip } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ACCEPT, FORMATS_LABEL } from "@/lib/chat/files";

export function AttachmentButton({
  onFiles,
  disabled = false,
}: {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        tabIndex={-1}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          // Reset so choosing the same file again still fires a change.
          event.target.value = "";
          if (files.length) onFiles(files);
        }}
      />
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => input.current?.click()}
            disabled={disabled}
            className="icon-button h-8 w-8 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={`Attach a document (${FORMATS_LABEL}, up to 10 MB)`}
          >
            <Paperclip size={15} />
          </button>
        </TooltipTrigger>
        <TooltipContent>Attach {FORMATS_LABEL} · up to 10 MB</TooltipContent>
      </Tooltip>
    </>
  );
}
