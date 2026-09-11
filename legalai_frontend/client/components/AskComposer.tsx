import { useEffect, useState } from "react";
import { ArrowUp, LoaderCircle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { listStatutes } from "@/lib/api/corpus";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The question input.
 *
 * The statute filter is populated from GET /v1/statutes, not a literal list.
 * The previous version offered the Arbitration and Conciliation Act, which is
 * not in the corpus — a filter for an Act we do not hold returns nothing and
 * looks like a bug.
 *
 * There is no language selector: the backend accepts `lang: "en"` only and
 * Hindi is deferred. Offering a control the server rejects is worse than
 * offering none.
 */
export function AskComposer({
  onSubmit,
  initialValue = "",
  busy = false,
  disabled = false,
  disabledHint,
  className,
  compact = false,
}: {
  onSubmit: (question: string, statuteSlug: string | null) => void;
  initialValue?: string;
  busy?: boolean;
  disabled?: boolean;
  disabledHint?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  const [value, setValue] = useState(initialValue);
  const [slug, setSlug] = useState<string>("");
  const { data: statutes } = useQuery({
    queryKey: ["statutes"],
    queryFn: listStatutes,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => setValue(initialValue), [initialValue]);

  const canSend = value.trim().length >= 3 && !busy && !disabled;

  const submit = () => {
    if (!canSend) return;
    onSubmit(value.trim(), slug || null);
  };

  return (
    <div
      className={cn(
        "ask-composer",
        disabled && "ask-composer-disabled",
        className,
      )}
    >
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        rows={compact ? 2 : 3}
        maxLength={2000}
        disabled={disabled}
        placeholder="Ask about the indexed Acts — for example, when a lease of immoveable property must be registered."
        className="w-full resize-none bg-transparent text-[15px] leading-relaxed text-[hsl(var(--ink))] outline-none placeholder:text-[hsl(var(--ink-4))]"
      />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-[hsl(var(--line))] pt-3">
        <div className="select-wrap">
          <select
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            disabled={disabled}
            className="bg-transparent text-[12px] font-medium text-[hsl(var(--ink-2))] outline-none"
            aria-label="Restrict the search to one Act"
          >
            <option value="">All indexed Acts</option>
            {statutes?.map((statute) => (
              <option key={statute.slug} value={statute.slug}>
                {statute.short_title}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-3">
          {disabled && disabledHint}
          <Button
            onClick={submit}
            disabled={!canSend}
            size="sm"
            className="gap-1.5"
          >
            {busy ? (
              <>
                <LoaderCircle size={14} className="animate-spin" /> Reading
              </>
            ) : (
              <>
                Ask <ArrowUp size={14} />
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
