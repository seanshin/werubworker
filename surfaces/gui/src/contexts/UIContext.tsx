import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { NAV_COLLAPSED_KEY } from "../appHelpers";

export type Surface = "session" | "scheduled" | "integrations" | "audit" | "inbox" | "persona" | "settings" | "about" | "ops" | "dev" | "database" | "services" | "wiki" | "monitoring";

interface UIContextValue {
  surface: Surface;
  setSurface: (s: Surface) => void;
  navCollapsed: boolean;
  toggleNav: () => void;
  navPeek: boolean;
  setNavPeek: (v: boolean) => void;
  railHidden: boolean;
  setRailHidden: (v: boolean | ((h: boolean) => boolean)) => void;
  searchOpen: boolean;
  setSearchOpen: (v: boolean) => void;
  accessKey: number;
  openAccess: () => void;
  personaViewId: string;
  setPersonaViewId: (v: string) => void;
  personaViewReturn: "session" | "settings";
  setPersonaViewReturn: (v: "session" | "settings") => void;
  openPersona: (id: string, from?: "session" | "settings") => void;
  scheduledOpenId: string | null;
  setScheduledOpenId: (v: string | null) => void;
  gateCreate: boolean;
  setGateCreate: (v: boolean) => void;
  onArtifactPreview: (open: boolean) => void;
}

const UIContext = createContext<UIContextValue | null>(null);

export function useUI(): UIContextValue {
  const ctx = useContext(UIContext);
  if (!ctx) throw new Error("useUI must be used within UIProvider");
  return ctx;
}

export { UIContext };

export function UIProvider({ children }: { children: ReactNode }) {
  const [surface, setSurface] = useState<Surface>("session");
  const [navCollapsed, setNavCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem(NAV_COLLAPSED_KEY) === "1"; } catch { return false; }
  });
  const [navPeek, setNavPeek] = useState(false);
  const [railHidden, setRailHidden] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [accessKey, setAccessKey] = useState(0);
  const [personaViewId, setPersonaViewId] = useState<string>("");
  const [personaViewReturn, setPersonaViewReturn] = useState<"session" | "settings">("session");
  const [scheduledOpenId, setScheduledOpenId] = useState<string | null>(null);
  const [gateCreate, setGateCreate] = useState(false);

  // While an artifact preview is open we auto-collapse the nav (#3). Remember the pre-preview
  // collapse state so we can restore it on close — unless the user re-opened the nav meanwhile.
  const navBeforePreview = useRef<boolean | null>(null);

  const setNavCollapsedPersist = useCallback((v: boolean) => {
    setNavCollapsed(v);
    try { localStorage.setItem(NAV_COLLAPSED_KEY, v ? "1" : "0"); } catch { /* best effort */ }
  }, []);

  const toggleNav = useCallback(() => {
    setNavPeek(false);
    navBeforePreview.current = null; // a manual toggle takes control from the artifact auto-collapse
    setNavCollapsedPersist(!navCollapsed);
  }, [navCollapsed, setNavCollapsedPersist]);

  // #3: collapse the nav while a full artifact preview is open, restore it on close (unless the
  // user manually toggled meanwhile). The collapse is transient — it never overwrites the pref.
  const onArtifactPreview = useCallback((open: boolean) => {
    if (open) {
      if (navBeforePreview.current === null) navBeforePreview.current = navCollapsed;
      setNavPeek(false);
      setNavCollapsed(true);
    } else if (navBeforePreview.current !== null) {
      setNavCollapsed(navBeforePreview.current);
      navBeforePreview.current = null;
    }
  }, [navCollapsed]);

  const openAccess = useCallback(() => {
    setRailHidden(false);
    setAccessKey((k) => k + 1);
  }, []);

  const openPersona = useCallback((id: string, from: "session" | "settings" = "session") => {
    setPersonaViewReturn(from);
    setPersonaViewId(id);
    setSurface("persona");
  }, []);

  // Keyboard shortcuts (Cmd+B, Cmd+,)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleNav();
      }
      // ⌘, — the platform Settings shortcut (advertised in the account menu, §26).
      if ((e.metaKey || e.ctrlKey) && e.key === ",") {
        e.preventDefault();
        setSurface("settings");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleNav]);

  // A remembered Scheduled-detail target must not outlive the surface
  useEffect(() => {
    if (surface !== "scheduled") setScheduledOpenId(null);
  }, [surface]);

  // §34 (UX-016): clicking an artifact chip in the transcript must land somewhere visible
  useEffect(() => {
    const show = () => setRailHidden(false);
    window.addEventListener("ocw-open-artifact", show);
    return () => window.removeEventListener("ocw-open-artifact", show);
  }, []);

  const value = useMemo<UIContextValue>(
    () => ({
      surface,
      setSurface,
      navCollapsed,
      toggleNav,
      navPeek,
      setNavPeek,
      railHidden,
      setRailHidden,
      searchOpen,
      setSearchOpen,
      accessKey,
      openAccess,
      personaViewId,
      setPersonaViewId,
      personaViewReturn,
      setPersonaViewReturn,
      openPersona,
      scheduledOpenId,
      setScheduledOpenId,
      gateCreate,
      setGateCreate,
      onArtifactPreview,
    }),
    [
      surface,
      navCollapsed,
      toggleNav,
      navPeek,
      railHidden,
      searchOpen,
      accessKey,
      openAccess,
      personaViewId,
      personaViewReturn,
      openPersona,
      scheduledOpenId,
      gateCreate,
      onArtifactPreview,
    ],
  );

  return <UIContext.Provider value={value}>{children}</UIContext.Provider>;
}
