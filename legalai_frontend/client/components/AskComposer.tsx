import { useState } from "react";
import { ArrowUp, ChevronDown, LockKeyhole, SlidersHorizontal } from "lucide-react";
import { Link } from "react-router-dom";
import { ModelSelector } from "@/components/ModelSelector";
import type { ModelConfiguration } from "@/lib/model-config";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const statuteOptions = [
  "All indexed Acts",
  "Indian Contract Act, 1872",
  "Registration Act, 1908",
  "Arbitration and Conciliation Act, 1996",
];

export function AskComposer({
  hasKey,
  onSubmit,
  initialValue = "",
  configuredModels,
  selectedModelId,
  onModelSelect,
  className,
  compact = false,
}: {
  hasKey: boolean;
  onSubmit: (question: string, modelId?: string) => void;
  initialValue?: string;
  configuredModels: ModelConfiguration[];
  selectedModelId?: string;
  onModelSelect: (modelId: string) => void;
  className?: string;
  compact?: boolean;
}) {
  const [value, setValue] = useState(initialValue);
  const [language, setLanguage] = useState<"English" | "हिंदी">("English");
  const [statute, setStatute] = useState(statuteOptions[0]);

  const submit = () => {
    if (value.trim() && hasKey) {
      onSubmit(value.trim(), selectedModelId);
      setValue("");
    }
  };

  return (
    <div className={cn("ask-composer", compact && "ask-composer-compact", !hasKey && "ask-composer-disabled", className)}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-[hsl(var(--ink-3))]">
          <span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--brand))]" /> Ask the corpus
        </div>
        <div className="flex rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-0.5 text-xs font-semibold">
          {(["English", "हिंदी"] as const).map((item) => (
            <button key={item} disabled={!hasKey} onClick={() => setLanguage(item)} className={cn("rounded-md px-2.5 py-1.5 transition", language === item ? "bg-[hsl(var(--canvas))] text-[hsl(var(--brand))] shadow-sm" : "text-[hsl(var(--ink-3))] hover:text-[hsl(var(--ink))]", !hasKey && "cursor-not-allowed opacity-60")}>
              {item}
            </button>
          ))}
        </div>
      </div>

      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit();
        }}
        disabled={!hasKey}
        placeholder={hasKey ? "Ask a question about Indian law…" : "Add an API key in Settings to ask the corpus"}
        className="min-h-[138px] w-full resize-none border-0 bg-transparent text-[17px] leading-7 text-[hsl(var(--ink))] outline-none placeholder:text-[hsl(var(--ink-4))] disabled:cursor-not-allowed"
      />

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[hsl(var(--line))] pt-3">
        <ModelSelector
          configuredModels={configuredModels}
          selectedModelId={selectedModelId}
          onSelect={onModelSelect}
          disabled={!hasKey}
          className="max-w-[190px]"
        />
        <label className={cn("inline-flex min-w-0 items-center gap-2 rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 py-2 text-xs font-semibold text-[hsl(var(--ink-2))]", !hasKey && "opacity-60")}>
          <SlidersHorizontal size={13} className="shrink-0 text-[hsl(var(--brand))]" />
          <select disabled={!hasKey} value={statute} onChange={(event) => setStatute(event.target.value)} className="max-w-[145px] appearance-none truncate bg-transparent pr-1 outline-none">
            {statuteOptions.map((option) => <option key={option}>{option}</option>)}
          </select>
          <ChevronDown size={13} className="shrink-0" />
        </label>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-[11px] text-[hsl(var(--ink-4))] sm:inline">⌘ ↵ to send</span>
          <Button onClick={submit} disabled={!hasKey || !value.trim() || !selectedModelId} className="h-9 rounded-lg bg-[hsl(var(--brand))] px-3 text-[hsl(var(--brand-foreground))] hover:bg-[hsl(var(--brand-strong))]">
            <ArrowUp size={16} />
          </Button>
        </div>
      </div>

      {!hasKey && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 py-2.5 text-xs text-[hsl(var(--ink-3))]">
          <LockKeyhole size={14} className="shrink-0 text-[hsl(var(--brand))]" />
          <span>Your key stays private and is only used for your requests.</span>
          <Link to="/settings" className="ml-auto shrink-0 font-bold text-[hsl(var(--brand))] hover:underline">Go to Settings</Link>
        </div>
      )}
    </div>
  );
}
