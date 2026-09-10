import { useEffect, useState } from "react";
import { Check, Eye, EyeOff, KeyRound, LockKeyhole, ShieldCheck, Trash2 } from "lucide-react";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import { ModelSelector } from "@/components/ModelSelector";
import { Button } from "@/components/ui/button";
import {
  allModelOptions,
  maskApiKey,
  modelProviders,
  readModelConfigurations,
  writeModelConfigurations,
  type ModelConfiguration,
} from "@/lib/model-config";

const selectedModelStorageKey = "legalassist-settings-model";

export default function Settings() {
  const [configuredModels, setConfiguredModels] = useState<ModelConfiguration[]>(() => readModelConfigurations());
  const [selectedModelId, setSelectedModelId] = useState(() => localStorage.getItem(selectedModelStorageKey) || allModelOptions[0].id);
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [editingKey, setEditingKey] = useState(false);

  useEffect(() => {
    const refresh = () => setConfiguredModels(readModelConfigurations());
    window.addEventListener("legalassist-model-configurations-updated", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("legalassist-model-configurations-updated", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const selectedModel = allModelOptions.find((model) => model.id === selectedModelId) ?? allModelOptions[0];
  const selectedConfiguration = configuredModels.find((configuration) => configuration.id === selectedModel.id);
  const selectedProvider = modelProviders.find((provider) => provider.id === selectedModel.providerId);

  const selectModel = (modelId: string) => {
    setSelectedModelId(modelId);
    localStorage.setItem(selectedModelStorageKey, modelId);
    setEditingKey(false);
    setKey("");
    setShowKey(false);
  };

  const saveKey = () => {
    const trimmedKey = key.trim();
    if (trimmedKey.length < 8) return;
    const nextConfiguration: ModelConfiguration = {
      ...selectedModel,
      maskedKey: maskApiKey(trimmedKey),
      verified: true,
    };
    const nextConfigurations = [
      ...configuredModels.filter((configuration) => configuration.id !== selectedModel.id),
      nextConfiguration,
    ];
    setConfiguredModels(nextConfigurations);
    writeModelConfigurations(nextConfigurations);
    setKey("");
    setShowKey(false);
    setEditingKey(false);
  };

  const removeConfiguration = () => {
    const nextConfigurations = configuredModels.filter((configuration) => configuration.id !== selectedModel.id);
    setConfiguredModels(nextConfigurations);
    writeModelConfigurations(nextConfigurations);
    setEditingKey(false);
    setKey("");
  };

  return (
    <LegalAssistLayout>
      <div className="mx-auto max-w-[1000px] px-5 pb-16 pt-10 sm:px-8 lg:pt-14">
        <div className="mb-10 border-b border-[hsl(var(--line))] pb-8">
          <div className="eyebrow"><span className="eyebrow-dot" /> Your connection</div>
          <h1 className="mt-3 font-display text-5xl tracking-[-0.045em]">Settings</h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-[hsl(var(--ink-2))]">Connect a model provider to ask questions. Your key is encrypted and never leaves the server.</p>
        </div>

        <div className="grid gap-8 lg:grid-cols-[1fr_280px]">
          <section>
            <div className="mb-4 text-[11px] font-bold uppercase tracking-[0.16em] text-[hsl(var(--ink-3))]">LLM providers / models</div>
            <div className="settings-card settings-card-active">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="provider-mark">{selectedModel.providerName.slice(0, 1)}</span>
                    <span className="font-display text-xl">{selectedModel.providerName}</span>
                  </div>
                  <p className="mt-2 text-sm text-[hsl(var(--ink-3))]">{selectedProvider?.description}</p>
                </div>
                {selectedConfiguration && !editingKey && <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-[hsl(var(--brand-soft))] px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.12em] text-[hsl(var(--brand))]"><Check size={11} /> Verified</span>}
              </div>

              <div className="mt-5 border-t border-[hsl(var(--line))] pt-5">
                <label className="meta-label">Select a model</label>
                <ModelSelector
                  configuredModels={configuredModels}
                  selectedModelId={selectedModel.id}
                  onSelect={selectModel}
                  showAllModels
                  className="mt-2 h-11 w-full justify-between sm:max-w-[340px]"
                />
                <p className="mt-2 text-xs text-[hsl(var(--ink-3))]">{selectedModel.description}. Configure a key below to make it available in Ask.</p>
              </div>

              <div className="mt-5 border-t border-[hsl(var(--line))] pt-5">
                <label className="meta-label">API key</label>
                {selectedConfiguration && !editingKey ? (
                  <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center">
                    <div className="flex h-11 min-w-0 flex-1 items-center gap-3 rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 text-sm text-[hsl(var(--ink-2))]">
                      <KeyRound size={15} className="shrink-0 text-[hsl(var(--brand))]" />
                      <span className="truncate">{selectedConfiguration.maskedKey}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <button onClick={() => setEditingKey(true)} className="text-xs font-bold text-[hsl(var(--brand))] hover:underline">Update key</button>
                      <button onClick={removeConfiguration} className="inline-flex items-center gap-1 text-xs font-bold text-[hsl(var(--ink-3))] hover:text-[hsl(var(--ink))]"><Trash2 size={13} /> Remove</button>
                    </div>
                  </div>
                ) : (
                  <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                    <div className="relative flex-1">
                      <KeyRound size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[hsl(var(--ink-4))]" />
                      <input type={showKey ? "text" : "password"} value={key} onChange={(event) => setKey(event.target.value)} onKeyDown={(event) => event.key === "Enter" && saveKey()} placeholder="Paste your provider key" className="h-11 w-full rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] pl-10 pr-10 text-sm outline-none placeholder:text-[hsl(var(--ink-4))] focus:border-[hsl(var(--brand))]" />
                      <button onClick={() => setShowKey((value) => !value)} className="absolute right-3 top-1/2 -translate-y-1/2 text-[hsl(var(--ink-3))]" aria-label={showKey ? "Hide key" : "Show key"}>{showKey ? <EyeOff size={15} /> : <Eye size={15} />}</button>
                    </div>
                    <Button onClick={saveKey} disabled={key.trim().length < 8} className="h-11 rounded-lg bg-[hsl(var(--brand))] px-4 text-[hsl(var(--brand-foreground))] hover:bg-[hsl(var(--brand-strong))]"><ShieldCheck size={15} /> Verify & save</Button>
                  </div>
                )}
              </div>
            </div>

            {configuredModels.length > 0 && (
              <div className="mt-7">
                <div className="mb-3 flex items-center justify-between"><span className="meta-label">Configured models</span><span className="text-xs text-[hsl(var(--ink-3))]">{configuredModels.length} enabled</span></div>
                <div className="divide-y divide-[hsl(var(--line))] rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))]">
                  {configuredModels.map((configuration) => (
                    <button key={configuration.id} onClick={() => selectModel(configuration.id)} className="group flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition hover:bg-[hsl(var(--canvas))]">
                      <span className="flex min-w-0 items-center gap-3"><span className="provider-mark h-7 w-7 shrink-0 rounded-md text-xs">{configuration.providerName.slice(0, 1)}</span><span className="min-w-0"><span className="block truncate text-sm font-semibold text-[hsl(var(--ink-2))]">{configuration.providerName} · {configuration.name}</span><span className="mt-0.5 block truncate text-xs text-[hsl(var(--ink-3))]">{configuration.maskedKey}</span></span></span>
                      <span className="inline-flex shrink-0 items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-[hsl(var(--brand))]"><Check size={12} /> Verified</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </section>

          <aside>
            <div className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] p-5">
              <div className="feature-icon"><LockKeyhole size={17} /></div>
              <h2 className="mt-4 font-display text-xl">Your key, your control</h2>
              <p className="mt-2 text-sm leading-6 text-[hsl(var(--ink-3))]">Keys are encrypted at rest and used only to generate your requests. LegalAssist never stores your questions or answers.</p>
              <div className="mt-5 space-y-3 border-t border-[hsl(var(--line))] pt-4 text-xs text-[hsl(var(--ink-3))]">
                <div className="flex items-center gap-2"><Check size={13} className="text-[hsl(var(--brand))]" /> Corpus browsing stays free</div>
                <div className="flex items-center gap-2"><Check size={13} className="text-[hsl(var(--brand))]" /> No provider account sharing</div>
                <div className="flex items-center gap-2"><Check size={13} className="text-[hsl(var(--brand))]" /> Remove your key anytime</div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </LegalAssistLayout>
  );
}
