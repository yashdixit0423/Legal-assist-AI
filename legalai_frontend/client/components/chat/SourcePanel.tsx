import { createContext, useContext, useEffect, useRef, useState } from "react";
import { ArrowUpRight, FileText, LoaderCircle, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { SectionReader } from "@/components/SectionReader";
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerTitle,
} from "@/components/ui/drawer";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { getSection } from "@/lib/api/corpus";
import type { DocumentSourceBlock } from "@/lib/api/types";
import { locatorLabel } from "@/lib/chat/citations";
import { cn } from "@/lib/utils";

/**
 * How a citation inside the conversation opens its section. Provided by the
 * Chat page; absent anywhere else, so chips there stay plain links.
 */
export const SourceOpenContext = createContext<
  ((sectionId: number) => void) | undefined
>(undefined);

export const useOpenSource = () => useContext(SourceOpenContext);

/** Same idea for a passage of the user's own document. */
export const DocumentOpenContext = createContext<
  ((source: DocumentSourceBlock) => void) | undefined
>(undefined);

export const useOpenDocument = () => useContext(DocumentOpenContext);

/** What the panel is showing: a statute section, or a document passage. */
export type SourceTarget =
  | { kind: "section"; sectionId: number }
  | { kind: "document"; source: DocumentSourceBlock };

export type PanelMode = "split" | "sheet" | "drawer";

/** ≥1280px splits the page; 768–1279px slides a sheet over; below that, a drawer. */
export function usePanelMode(): PanelMode {
  const read = (): PanelMode =>
    window.matchMedia("(min-width: 1280px)").matches
      ? "split"
      : window.matchMedia("(min-width: 768px)").matches
        ? "sheet"
        : "drawer";
  const [mode, setMode] = useState<PanelMode>(read);
  useEffect(() => {
    const queries = ["(min-width: 1280px)", "(min-width: 768px)"].map((q) =>
      window.matchMedia(q),
    );
    const update = () => setMode(read());
    queries.forEach((q) => q.addEventListener("change", update));
    return () =>
      queries.forEach((q) => q.removeEventListener("change", update));
  }, []);
  return mode;
}

/**
 * The verbatim section beside the conversation.
 *
 * Same query key as the Section page, so a section read here is already cached
 * there and vice versa. The statute text keeps `section-reader` styling: it is
 * the authority, and it should look more prominent than the explanation.
 */
export function SourcePanel({
  target,
  onClose,
  className,
}: {
  target: SourceTarget;
  /** Omitted inside the sheet, which brings its own close button. */
  onClose?: () => void;
  className?: string;
}) {
  if (target.kind === "document") {
    return (
      <DocumentPassage
        source={target.source}
        onClose={onClose}
        className={className}
      />
    );
  }
  return (
    <SectionSource
      sectionId={target.sectionId}
      onClose={onClose}
      className={className}
    />
  );
}

function SectionSource({
  sectionId,
  onClose,
  className,
}: {
  sectionId: number;
  onClose?: () => void;
  className?: string;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["section", sectionId],
    queryFn: () => getSection(sectionId),
  });
  const heading = useRef<HTMLDivElement>(null);

  // Focus moves into the panel when it opens or shows another section.
  useEffect(() => {
    heading.current?.focus();
  }, [sectionId]);

  return (
    <section
      aria-label="Source"
      className={cn("flex h-full min-h-0 flex-col", className)}
    >
      <div
        ref={heading}
        tabIndex={-1}
        className={cn(
          "flex items-center justify-between gap-3 border-b border-[hsl(var(--line))] px-5 py-3 outline-none",
          !onClose && "pr-12",
        )}
      >
        <span className="meta-label">Source</span>
        <div className="flex items-center gap-2">
          <a
            href={`/sections/${sectionId}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[12px] font-semibold text-[hsl(var(--brand))] hover:underline"
          >
            Open full page <ArrowUpRight size={13} />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="icon-button h-8 w-8"
              aria-label="Close source"
            >
              <X size={15} />
            </button>
          )}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 py-3 sm:px-3">
        {isLoading && (
          <p className="flex items-center gap-2 px-3 py-6 text-[13px] text-[hsl(var(--ink-3))]">
            <LoaderCircle size={14} className="animate-spin" /> Loading the
            section text…
          </p>
        )}
        {error && (
          <p className="px-3 py-6 text-[13px] text-[hsl(var(--ink-3))]">
            {(error as Error).message || "The section could not be loaded."}
          </p>
        )}
        {data && <SectionReader section={data} compact />}
      </div>
    </section>
  );
}

/**
 * A passage from the user's own document. Labelled as theirs, set apart from
 * the statute text, and never presented as law.
 */
function DocumentPassage({
  source,
  onClose,
  className,
}: {
  source: DocumentSourceBlock;
  onClose?: () => void;
  className?: string;
}) {
  const heading = useRef<HTMLDivElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [source.citation_id]);

  return (
    <section
      aria-label="Source"
      className={cn("flex h-full min-h-0 flex-col", className)}
    >
      <div
        ref={heading}
        tabIndex={-1}
        className={cn(
          "flex items-center justify-between gap-3 border-b border-[hsl(var(--line))] px-5 py-3 outline-none",
          !onClose && "pr-12",
        )}
      >
        <span className="meta-label">Your document</span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="icon-button h-8 w-8"
            aria-label="Close source"
          >
            <X size={15} />
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5">
        <div className="flex items-start gap-3">
          <span className="feature-icon shrink-0">
            <FileText size={16} />
          </span>
          <div className="min-w-0">
            <h2 className="font-display break-words text-[22px] leading-tight tracking-[-0.01em] text-[hsl(var(--ink))]">
              {source.filename}
            </h2>
            <p className="mt-1 text-[12px] text-[hsl(var(--ink-3))]">
              {source.locator_kind === "page" ? "Page" : "Paragraph"}{" "}
              {source.locator} · cited as{" "}
              {locatorLabel(source.locator_kind, source.locator)}
            </p>
          </div>
        </div>
        <blockquote className="mt-5 whitespace-pre-wrap border-l-2 border-[hsl(var(--line-strong))] pl-4 font-serif text-[15px] leading-[1.75] text-[hsl(var(--ink-2))]">
          {source.excerpt}
        </blockquote>
        <p className="mt-4 text-[11.5px] leading-relaxed text-[hsl(var(--ink-4))]">
          An excerpt of the passage the answer drew on, from the file you
          attached. It is not law. Documents are processed temporarily and not
          stored.
        </p>
      </div>
    </section>
  );
}

/** The sheet (tablet) and drawer (phone) forms of the same panel. */
export function SourceOverlay({
  mode,
  target,
  onClose,
  returnFocus,
}: {
  mode: Exclude<PanelMode, "split">;
  target: SourceTarget | null;
  onClose: () => void;
  returnFocus: () => void;
}) {
  const open = target !== null;
  const onOpenChange = (next: boolean) => {
    if (!next) onClose();
  };
  const onCloseAutoFocus = (event: Event) => {
    event.preventDefault();
    returnFocus();
  };

  if (mode === "sheet") {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="right"
          className="flex w-full flex-col gap-0 border-[hsl(var(--line))] bg-[hsl(var(--canvas))] p-0 sm:max-w-[560px]"
          onCloseAutoFocus={onCloseAutoFocus}
        >
          <SheetTitle className="sr-only">Source</SheetTitle>
          <SheetDescription className="sr-only">
            The text the cited passage came from.
          </SheetDescription>
          {target !== null && <SourcePanel target={target} />}
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent
        className="max-h-[85dvh] border-[hsl(var(--line))] bg-[hsl(var(--canvas))]"
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <DrawerTitle className="sr-only">Source</DrawerTitle>
        <DrawerDescription className="sr-only">
          The text the cited passage came from.
        </DrawerDescription>
        {target !== null && (
          <SourcePanel
            target={target}
            onClose={onClose}
            className="min-h-[50dvh]"
          />
        )}
      </DrawerContent>
    </Drawer>
  );
}
