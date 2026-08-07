import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { getSettings, type SurfaceVisibility } from "../api";

interface SettingsContextValue {
  model: string;
  setModel: (m: string) => void;
  models: string[];
  modelLabels: Record<string, string>;
  modelContextWindows: Record<string, number>;
  contextBar: boolean;
  modelReady: boolean;
  surfaces: SurfaceVisibility;
  settingsTab: string;
  setSettingsTab: (tab: string) => void;
  loadSettings: () => Promise<void>;
  setSurfaces: (s: SurfaceVisibility) => void;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function useSettings(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used within SettingsProvider");
  return ctx;
}

export { SettingsContext };

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [model, setModel] = useState("gpt-5.6-sol");
  const [models, setModels] = useState<string[]>([]);
  const [modelLabels, setModelLabels] = useState<Record<string, string>>({});
  const [modelContextWindows, setModelContextWindows] = useState<Record<string, number>>({});
  const [contextBar, setContextBar] = useState(false);
  const [modelReady, setModelReady] = useState(true);
  const [surfaces, setSurfaces] = useState<SurfaceVisibility>({ cowork: true, chat: false, code: false });
  const [settingsTab, setSettingsTab] = useState<string>("appearance");

  const loadSettings = useCallback(async () => {
    try {
      const s = await getSettings();
      setModels(s.models || []);
      setModelLabels(s.model_labels || {});
      setModelContextWindows(s.model_context_windows || {});
      setContextBar(s.context_bar === true);
      setModelReady(s.model_ready);
      if (s.surfaces) setSurfaces(s.surfaces);
    } catch {
      /* swallow */
    }
  }, []);

  const value = useMemo<SettingsContextValue>(
    () => ({
      model,
      setModel,
      models,
      modelLabels,
      modelContextWindows,
      contextBar,
      modelReady,
      surfaces,
      settingsTab,
      setSettingsTab,
      loadSettings,
      setSurfaces,
    }),
    [
      model,
      models,
      modelLabels,
      modelContextWindows,
      contextBar,
      modelReady,
      surfaces,
      settingsTab,
      loadSettings,
    ],
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}
