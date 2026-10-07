import { createContext, useContext, useEffect, useRef, useState } from "react";
import { ArrowUpRight, LoaderCircle, X } from "lucide-react";
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
import { cn } from "@/lib/utils";

/**
 * How a citation inside the conversation opens its section. Provided by the
 * Chat page; absent anywhere else, so chips there stay plain links.
 */
export const SourceOpenContext = createContext<
  ((sectionId: number) => void) | undefined
>(undefined);

export const useOpenSource = () => useContext(SourceOpenContext);

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
  sectionId,
  onClose,
  className,
}: {
  sectionId: number;
  /** Omitted inside the sheet, which brings its own close button. */
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

/** The sheet (tablet) and drawer (phone) forms of the same panel. */
export function SourceOverlay({
  mode,
  sectionId,
  onClose,
  returnFocus,
}: {
  mode: Exclude<PanelMode, "split">;
  sectionId: number | null;
  onClose: () => void;
  returnFocus: () => void;
}) {
  const open = sectionId !== null;
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
          <SheetTitle className="sr-only">Source section</SheetTitle>
          <SheetDescription className="sr-only">
            The verbatim text of the cited section.
          </SheetDescription>
          {sectionId !== null && <SourcePanel sectionId={sectionId} />}
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
        <DrawerTitle className="sr-only">Source section</DrawerTitle>
        <DrawerDescription className="sr-only">
          The verbatim text of the cited section.
        </DrawerDescription>
        {sectionId !== null && (
          <SourcePanel
            sectionId={sectionId}
            onClose={onClose}
            className="min-h-[50dvh]"
          />
        )}
      </DrawerContent>
    </Drawer>
  );
}
