import { useEffect, useState } from "react";
import { readModelConfigurations, type ModelConfiguration } from "@/lib/model-config";

const updateEvent = "legalassist-model-configurations-updated";

export function useModelConfigurations() {
  const [configurations, setConfigurations] = useState<ModelConfiguration[]>(() => readModelConfigurations());

  useEffect(() => {
    const refresh = () => setConfigurations(readModelConfigurations());
    window.addEventListener(updateEvent, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(updateEvent, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  return configurations;
}
