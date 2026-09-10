export type ModelOption = {
  id: string;
  providerId: string;
  providerName: string;
  providerDescription: string;
  name: string;
  description: string;
};

export type ModelConfiguration = ModelOption & {
  maskedKey: string;
  verified: boolean;
};

export const modelProviders = [
  {
    id: "openai",
    name: "OpenAI",
    description: "Use GPT models for grounded answers.",
    models: [
      { id: "openai-gpt-4o-mini", name: "GPT-4o mini", description: "Fast, focused answers" },
      { id: "openai-gpt-4o", name: "GPT-4o", description: "More capable reasoning" },
    ],
  },
  {
    id: "anthropic",
    name: "Anthropic",
    description: "Use Claude models for grounded answers.",
    models: [
      { id: "anthropic-claude-3-5-haiku", name: "Claude 3.5 Haiku", description: "Quick, concise answers" },
      { id: "anthropic-claude-3-5-sonnet", name: "Claude 3.5 Sonnet", description: "Detailed reasoning" },
    ],
  },
] as const;

export const allModelOptions: ModelOption[] = modelProviders.flatMap((provider) =>
  provider.models.map((model) => ({
    ...model,
    providerId: provider.id,
    providerName: provider.name,
    providerDescription: provider.description,
  })),
);

const storageKey = "legalassist-model-configurations";

export function maskApiKey(value: string) {
  const suffix = value.slice(-6);
  return `••••••••••••••••••••${suffix}`;
}

function parseConfigurations(value: string | null): ModelConfiguration[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is ModelConfiguration =>
      typeof item === "object" &&
      item !== null &&
      typeof (item as ModelConfiguration).id === "string" &&
      typeof (item as ModelConfiguration).providerId === "string" &&
      typeof (item as ModelConfiguration).providerName === "string" &&
      typeof (item as ModelConfiguration).name === "string" &&
      typeof (item as ModelConfiguration).maskedKey === "string" &&
      (item as ModelConfiguration).verified === true,
    );
  } catch {
    return [];
  }
}

export function readModelConfigurations() {
  if (typeof window === "undefined") return [];
  const current = parseConfigurations(window.localStorage.getItem(storageKey));
  if (current.length > 0) return current;

  const legacyKey = window.localStorage.getItem("legalassist-api-key");
  const legacyProvider = window.localStorage.getItem("legalassist-provider");
  if (legacyKey !== "saved" || !legacyProvider) return [];

  const legacyModel = allModelOptions.find((model) => model.providerId === legacyProvider);
  if (!legacyModel) return [];
  return [{ ...legacyModel, maskedKey: "••••••••••••••••••••••••", verified: true }];
}

export function writeModelConfigurations(configurations: ModelConfiguration[]) {
  window.localStorage.setItem(storageKey, JSON.stringify(configurations));
  window.localStorage.removeItem("legalassist-api-key");
  window.localStorage.removeItem("legalassist-provider");
  window.dispatchEvent(new Event("legalassist-model-configurations-updated"));
}

export function findModelOption(id: string) {
  return allModelOptions.find((model) => model.id === id);
}
