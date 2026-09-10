import { ChevronDown, LockKeyhole, Settings2 } from "lucide-react";
import { Link } from "react-router-dom";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ModelConfiguration, ModelOption } from "@/lib/model-config";
import { allModelOptions, modelProviders } from "@/lib/model-config";
import { cn } from "@/lib/utils";

export function ModelSelector({
  selectedModelId,
  configuredModels,
  onSelect,
  disabled = false,
  showAllModels = false,
  className,
}: {
  selectedModelId?: string;
  configuredModels: ModelConfiguration[];
  onSelect: (modelId: string) => void;
  disabled?: boolean;
  showAllModels?: boolean;
  className?: string;
}) {
  const availableModels = showAllModels ? allModelOptions : configuredModels;
  const selectedModel = availableModels.find((model) => model.id === selectedModelId) ?? availableModels[0];
  const hasAvailableModels = availableModels.length > 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled || !hasAvailableModels}
          aria-label={selectedModel ? `Selected model: ${selectedModel.providerName} ${selectedModel.name}` : "Configure a model in Settings"}
          className={cn(
            "inline-flex h-9 min-w-0 max-w-full items-center gap-2 rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 text-xs font-semibold text-[hsl(var(--ink-2))] outline-none transition hover:border-[hsl(var(--brand))] hover:text-[hsl(var(--brand))] focus-visible:ring-2 focus-visible:ring-[hsl(var(--brand)/.35)] disabled:cursor-not-allowed disabled:opacity-60",
            className,
          )}
        >
          {selectedModel ? <span className="truncate"><span className="hidden sm:inline">{selectedModel.providerName} · </span>{selectedModel.name}</span> : <span className="truncate">Configure a model</span>}
          <ChevronDown size={13} className="shrink-0 text-[hsl(var(--ink-3))]" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" sideOffset={8} className="w-[280px] border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-1.5 text-[hsl(var(--ink))] shadow-xl">
        <DropdownMenuLabel className="px-2.5 py-2 text-[10px] font-bold uppercase tracking-[0.16em] text-[hsl(var(--ink-3))]">Models for this chat</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={selectedModel?.id} onValueChange={onSelect}>
          {modelProviders.map((provider) => {
            const models = (showAllModels ? allModelOptions : configuredModels).filter((model) => model.providerId === provider.id);
            if (models.length === 0) return null;
            return (
              <div key={provider.id}>
                <DropdownMenuLabel className="px-2.5 pb-1 pt-2 text-xs font-semibold text-[hsl(var(--ink-2))]">{provider.name}</DropdownMenuLabel>
                {models.map((model) => <ModelRadioItem key={model.id} model={model} configured={configuredModels.some((configuredModel) => configuredModel.id === model.id)} />)}
              </div>
            );
          })}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator className="my-1.5 bg-[hsl(var(--line))]" />
        <DropdownMenuLabel className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-[11px] font-medium text-[hsl(var(--ink-3))]">
          <span className="inline-flex min-w-0 items-center gap-1.5"><LockKeyhole size={12} /> Configure more models</span>
          <Link to="/settings" className="inline-flex shrink-0 items-center gap-1 font-bold text-[hsl(var(--brand))] hover:underline"><Settings2 size={12} /> Settings</Link>
        </DropdownMenuLabel>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ModelRadioItem({ model, configured }: { model: ModelOption | ModelConfiguration; configured: boolean }) {
  return (
    <DropdownMenuRadioItem
      value={model.id}
      className="min-h-12 rounded-lg py-2 pl-8 pr-2 text-[hsl(var(--ink-2))] focus:bg-[hsl(var(--brand-soft))] focus:text-[hsl(var(--ink))]"
    >
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-xs font-semibold">{model.name}</span>
        <span className="truncate text-[10px] text-[hsl(var(--ink-3))]">{model.description}{!configured && <span className="ml-1.5 text-[hsl(var(--ink-4))]">· Not configured</span>}</span>
      </span>
    </DropdownMenuRadioItem>
  );
}
