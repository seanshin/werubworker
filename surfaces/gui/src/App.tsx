import { lazy, Suspense, useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  finalizeAutomationRun,
  getArtifacts,
  getHealth,
  getRecentWorkspaces,
  getSessionMessages,
  getSessions,
  announceAutomationsChanged,
  connectEvents,
  getSettings,
  getPersonas,
  getUnattended,
  PERSONAS_CHANGED,
  deleteSession,
  renameSession,
  runAutomation,
  setSessionFlags,
  Session,
  type Persona,
  type RecentWorkspace,
} from "./api";
import type {
  ApprovalDecision,
  Attachment,
  Item,
  SessionInfo,
  WsEvent,
} from "./types";
import { isProjectScoped } from "./personaScope";
import { baseName } from "./paths";
import { itemsFromMessages } from "./itemsFromMessages";
import { emptyUsage, usageFromMessages } from "./usage";
import { streamMode } from "./streamGate";
import { InboxItemCard } from "./components/InboxItemCard";
import { isTauri, platformOS, startWindowDrag } from "./tauri";
import { Icon } from "./components/Icon";
import { Sidebar } from "./components/Sidebar";
import { ThinkingBlock, Transcript } from "./components/Transcript";
import { Composer } from "./components/Composer";
import { Markdown } from "./components/Markdown";
import { SearchModal } from "./components/SearchModal";
import { SessionIntro } from "./components/SessionIntro";
import { FolderGate } from "./components/FolderGate";
import { Onboarding } from "./components/Onboarding";
import { UpdateBanner } from "./components/UpdateBanner";
import { RightRail } from "./components/RightRail";

// Lazy-loaded views — only fetched when the user navigates to that surface.
const ScheduledView = lazy(() => import("./components/ScheduledView").then(m => ({ default: m.ScheduledView })));
const IntegrationsView = lazy(() => import("./components/IntegrationsView").then(m => ({ default: m.IntegrationsView })));
const SettingsView = lazy(() => import("./components/SettingsView").then(m => ({ default: m.SettingsView })));
const PersonaView = lazy(() => import("./components/PersonaView").then(m => ({ default: m.PersonaView })));
const AuditView = lazy(() => import("./components/AuditView").then(m => ({ default: m.AuditView })));
const InboxView = lazy(() => import("./components/InboxView").then(m => ({ default: m.InboxView })));
const AboutView = lazy(() => import("./components/AboutView").then(m => ({ default: m.AboutView })));
const OpsView = lazy(() => import("./components/OpsView").then(m => ({ default: m.OpsView })));
const DevView = lazy(() => import("./components/DevView").then(m => ({ default: m.DevView })));
const DatabaseView = lazy(() => import("./components/DatabaseView").then(m => ({ default: m.DatabaseView })));
const ServiceConfigView = lazy(() => import("./components/ServiceConfigView").then(m => ({ default: m.ServiceConfigView })));
const WikiView = lazy(() => import("./components/WikiView").then(m => ({ default: m.WikiView })));
import { ApprovalCard } from "./components/ApprovalCard";
import { DirectoryRequestCard } from "./components/DirectoryRequestCard";
import { PlanCard } from "./components/PlanCard";
import { WorkspaceTrustPrompt } from "./components/WorkspaceTrustPrompt";
import { ErrorBoundary } from "./components/ErrorBoundary";
import {
  newId,
  needsWorkspaceFallback,
  gatesWorkspaceFallback,
  rememberLastSession,
  resumeTargetForAgent,
  fallbackWorkspace,
} from "./appHelpers";
import { SettingsProvider, useSettings } from "./contexts/SettingsContext";
import { UIProvider, useUI } from "./contexts/UIContext";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { LoginView } from "./components/LoginView";
import { useStreamState } from "./hooks/useStreamState";
import { useInboxState } from "./hooks/useInboxState";
import { useVisibleInterval } from "./hooks/useVisibleInterval";
import { useSessionState } from "./hooks/useSessionState";
import { dispatchEvent, type EventHandlerCtx } from "./hooks/eventHandlers";

export function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}

/** Shows the login/setup screen when locked; otherwise renders the normal app. */
function AuthGate() {
  const { checking, authenticated } = useAuth();

  if (checking) return null; // still resolving auth status

  if (!authenticated) return <LoginView />;

  return (
    <SettingsProvider>
      <UIProvider>
        <AppInner />
      </UIProvider>
    </SettingsProvider>
  );
}

function AppInner() {
  const { t } = useTranslation(["session", "common"]);
  // Consume contexts
  const {
    model, setModel, models, modelLabels, modelContextWindows,
    contextBar, modelReady, surfaces, settingsTab, setSettingsTab,
    loadSettings,
  } = useSettings();
  const {
    surface, setSurface,
    navCollapsed, toggleNav, navPeek, setNavPeek,
    railHidden, setRailHidden,
    searchOpen, setSearchOpen,
    accessKey, openAccess,
    personaViewId,
    personaViewReturn,
    openPersona,
    scheduledOpenId, setScheduledOpenId,
    gateCreate, setGateCreate,
    onArtifactPreview,
  } = useUI();
  // openSettings bridges both contexts (needs setSettingsTab from Settings + setSurface from UI).
  const openSettings = useCallback(
    (tab: string = "appearance") => {
      setSettingsTab(tab);
      setSurface("settings");
    },
    [setSettingsTab, setSurface],
  );

  // Stable surface-navigation callbacks for Sidebar (memo'd) — avoids recreation on every render.
  const openManage = useCallback(() => openSettings("appearance"), [openSettings]);
  const openManagePersonas = useCallback(() => openSettings("personas"), [openSettings]);
  const openScheduled = useCallback(() => setSurface("scheduled"), [setSurface]);
  const openIntegrations = useCallback(() => setSurface("integrations"), [setSurface]);
  const openAudit = useCallback(() => setSurface("audit"), [setSurface]);
  const openAbout = useCallback(() => setSurface("about"), [setSurface]);
  const openInbox = useCallback(() => setSurface("inbox"), [setSurface]);
  const openOps = useCallback(() => setSurface("ops"), [setSurface]);
  const openDev = useCallback(() => setSurface("dev"), [setSurface]);
  const openDatabase = useCallback(() => setSurface("database"), [setSurface]);
  const openServices = useCallback(() => setSurface("services"), [setSurface]);
  const openWiki = useCallback(() => setSurface("wiki"), [setSurface]);
  const onPeekLeave = useCallback(() => setNavPeek(false), [setNavPeek]);
  const onOpenPersonaFromSidebar = useCallback(
    (id: string) => openPersona(id, "session"),
    [openPersona],
  );
  const onOpenAutomation = useCallback(
    (id: string) => { setScheduledOpenId(id); setSurface("scheduled"); },
    [setScheduledOpenId, setSurface],
  );

  const {
    workspace, setWorkspace,
    branch, setBranch,
    agent, setAgent,
    mode, setMode,
    connected, setConnected,
    running, setRunning,
    sessionId, setSessionId,
    usage, setUsage,
    todo, setTodo,
    showGate, setShowGate,
    workspaceTrustRequest, setWorkspaceTrustRequest,
    runContext, setRunContext,
    composerPrefill, setComposerPrefill,
  } = useSessionState();
  const [items, setItems] = useState<Item[]>([]);
  // Moved out of UIContext — only used in App, avoids triggering UIContext consumers
  // (Sidebar etc.) on every tool_finished / turn_done refresh.
  const [browserRefreshKey, setBrowserRefreshKey] = useState(0);
  const [artifactCount, setArtifactCount] = useState(0);
  const {
    streaming, setStreaming,
    reasoning: reasoningStream, setReasoning: setReasoningStream, reasoningRef,
    compacting, setCompacting,
    appendDelta, appendReasoningDelta,
    flush: flushStream,
  } = useStreamState();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [projects, setProjects] = useState<RecentWorkspace[]>([]);

  // Persona metadata drives workspace behavior by FAMILY, not by hardcoded id (so a DevOps/SecOps
  // code-family persona gates a folder like Code, and a knowledge persona starts orphan like Cowork).
  const [personas, setPersonas] = useState<Persona[] | null>(null);
  useEffect(() => {
    getPersonas().then(setPersonas).catch(() => {});
  }, []);
  const personaOf = (a: string) => personas?.find((p) => p.id === a);

  // Shows a working-area chip / project grouping. Persona's needs_workspace; fallback before load.
  const needsWorkspace = (a: string) => personaOf(a)?.needs_workspace ?? needsWorkspaceFallback(a);
  // MUST pick a folder before starting — project-scoped personas (git-bound Code, project-bound
  // Ops). Scratch/deliverable personas start orphan: the server auto-provisions a per-conversation
  // scratch dir and reports it in the `ready` event.
  const gatesWorkspace = (a: string) => {
    const p = personaOf(a);
    return p ? isProjectScoped(p) : gatesWorkspaceFallback(a);
  };

  // The desktop tray's "Settings" item dispatches this on the window.
  useEffect(() => {
    const open = () => openSettings("appearance");
    window.addEventListener("coworker:open-settings", open);
    return () => window.removeEventListener("coworker:open-settings", open);
  }, []);

  // "Run setup again" (from Settings) re-opens the wizard.
  useEffect(() => {
    const open = () => {
      setOnboarding(true);
    };
    window.addEventListener("coworker:open-onboarding", open);
    return () => window.removeEventListener("coworker:open-onboarding", open);
  }, []);

  const sessionRef = useRef<Session | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // A prompt to auto-send once the next session connects (used by "Run now").
  const pendingPromptRef = useRef<string | null>(null);
  // The in-flight manual run to finalize after its first turn ({taskId, runId, sessionId}).
  const activeRunRef = useRef<{ taskId: string; runId: string; sessionId: string } | null>(null);

  // Fetch ALL sessions + known projects so the sidebar can group them.
  const refreshSessions = useCallback(() => {
    getSessions().then(setSessions).catch(() => setSessions([]));
    getRecentWorkspaces().then(setProjects).catch(() => setProjects([]));
  }, []);

  const {
    sessionInbox, setSessionInbox,
    unattended, unattendedRef, markUnattended,
    toggleUnattended, resolveSessionInbox, refreshInbox,
  } = useInboxState(sessionId, refreshSessions);

  // initial: adopt the server's seed workspace if any, else force the gate.
  // Retry health for a while: the desktop shell starts its sidecar in parallel, so the
  // server may not answer for a second or two. Only fall back to the gate once it's truly up.
  const [booting, setBooting] = useState(true);
  const [onboarding, setOnboarding] = useState(false);
  // True once we've resumed a prior conversation on boot (drives the splash wording).
  const [resumedExisting, setResumedExisting] = useState(false);
  // Latched: keep the boot splash up until the restored session is actually CONNECTED (not just
  // until `booting` clears), so an early click can't land on a session that's still settling.
  const [uiReady, setUiReady] = useState(false);

  // On boot with no seeded workspace, reopen the last thing the user had — most recent
  // conversation (restores its folder + agent + transcript), else the most recent project
  // folder. Only a true first run (nothing to resume) falls through to the folder gate.
  const resumeLastOrGate = async () => {
    let loadedSessions: SessionInfo[] = [];
    try {
      loadedSessions = (await getSessions()).filter((s) => s.session_id && !s.session_id.startsWith("__"));
      setSessions(loadedSessions);
      const sess = loadedSessions;
      const ts = (s: SessionInfo) => Date.parse(s.updated_at || "") || Number(s.updated_at) || 0;
      const last = [...sess].sort((a, b) => ts(b) - ts(a))[0];
      if (last) {
        setResumedExisting(true);
        if (last.agent) setAgent(last.agent);
        if (last.workspace) {
          setWorkspace(last.workspace);
          setBranch(null);
        }
        try {
          const messages = await getSessionMessages(last.session_id);
          setItems(itemsFromMessages(messages));
          setUsage(usageFromMessages(messages));
        } catch {
          setItems([]);
          setUsage(emptyUsage());
        }
        setSessionId(last.session_id);
        setShowGate(false);
        return;
      }
    } catch {
      /* fall through */
    }
    try {
      const recents = await getRecentWorkspaces();
      setProjects(recents);
      // Only auto-adopt a recent folder for gated surfaces (Code). Cowork starts orphan.
      if (gatesWorkspace(agent)) {
        const ws = recents.find((w) => w.exists) || recents[0];
        if (ws) {
          setWorkspace(ws.path);
          setShowGate(false);
          return;
        }
      }
    } catch {
      /* fall through */
    }
    setShowGate(gatesWorkspace(agent)); // only Code forces a first-run folder gate
  };

  useEffect(() => {
    let cancelled = false;
    const attempt = (tries: number) => {
      getHealth()
        .then(async (h) => {
          if (cancelled) return;
          setModel(h.model);
          // First-run setup wizard (desktop): show until the user completes/dismisses it.
          if (isTauri()) {
            getSettings()
              .then((s) => !cancelled && !s.onboarded && setOnboarding(true))
              .catch(() => {});
          }
          // Settle the active session BEFORE clearing `booting` (which unblocks the connection
          // effect). resumeLastOrGate is async — if we cleared `booting` first, the throwaway
          // initial sessionId would connect against an empty/stale workspace and the server
          // would provision a junk per-conversation scratch dir for it before resume could
          // flip to the real session. Cowork ignores default_workspace (a Code concept).
          if (h.default_workspace && gatesWorkspace(agent)) setWorkspace(h.default_workspace);
          else await resumeLastOrGate();
          // The mount-time loadSettings races the sidecar boot and swallows its failure —
          // on a cold start that left "Loading models…" stuck until the user visited
          // Settings (owner-hit 2026-07-23). Health just answered, so this one lands.
          loadSettings();
          if (!cancelled) setBooting(false);
        })
        .catch(() => {
          if (cancelled) return;
          if (tries <= 0) {
            setBooting(false);
            setShowGate(true);
          } else {
            setTimeout(() => attempt(tries - 1), 500);
          }
        });
    };
    attempt(40); // ~20s of 500ms retries
    return () => {
      cancelled = true;
    };
  }, []);

  // Reveal the UI once boot has settled AND the restored session is connected (or we're showing
  // the folder gate). Latched, so later reconnects never flash the splash again.
  useEffect(() => {
    if (uiReady || booting) return;
    if (connected || showGate) setUiReady(true);
  }, [uiReady, booting, connected, showGate]);
  // Safety net: if the restored session never reports connected (backend slow/unreachable), reveal
  // the UI anyway. Boot already passed the health check, so a live connect is sub-second; this only
  // bites in the failure case, so keep it short.
  useEffect(() => {
    if (uiReady || booting) return;
    const t = setTimeout(() => setUiReady(true), 1500);
    return () => clearTimeout(t);
  }, [uiReady, booting]);

  // Open Settings → Configure Models (from the composer's "No model connected" chip).
  const openModelSetup = () => openSettings("models");

  // Leaving the Settings page: pick up any model/surface changes for the composer (the modal used to
  // do this on close).
  useEffect(() => {
    if (surface !== "settings") loadSettings();
  }, [surface, loadSettings]);

  useEffect(() => {
    refreshSessions();
    loadSettings(); // selectable models + which session surfaces are visible
  }, [refreshSessions, loadSettings]);

  // The session list is now primarily updated via server push (sessions_changed event).
  // This slow poll (30s) is a fallback for missed pushes or edge cases.
  useVisibleInterval(refreshSessions, 30000);

  // Persona toggles can archive sessions server-side (disable-archives, §18): refetch on the
  // personas-changed event so the sidebar section disappears immediately, not on the next poll.
  useEffect(() => {
    const onPersonas = () => refreshSessions();
    window.addEventListener(PERSONAS_CHANGED, onPersonas);
    return () => window.removeEventListener(PERSONAS_CHANGED, onPersonas);
  }, [refreshSessions]);

  // If the active surface isn't visible (hidden in Settings, or a resumed session landed on a
  // hidden surface), fall back to Cowork (always visible). Watches both agent and surfaces so it
  // corrects regardless of which settled last.
  useEffect(() => {
    if ((agent === "chat" && !surfaces.chat) || (agent === "code" && !surfaces.code)) {
      switchAgent("cowork");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent, surfaces]);

  useEffect(() => {
    if (surface === "session") rememberLastSession(agent, sessionId, workspace);
  }, [surface, agent, sessionId, workspace]);

  // (re)connect when workspace, session, or agent changes
  useEffect(() => {
    if (booting) return; // wait until boot/resume settles the session before connecting
    if (gatesWorkspace(agent) && !workspace) return; // Code needs a folder (gate handles it)
    const eventCtx: EventHandlerCtx = {
      setConnected, setModel, setMode, setWorkspace, setWorkspaceTrustRequest,
      setRunning, setStreaming, setReasoningStream, setCompacting,
      setItems, setUsage, setTodo, setBrowserRefreshKey,
      appendDelta, appendReasoningDelta, flushStream,
      unattendedRef, reasoningRef, activeRunRef,
      sessionId, refreshSessions, finalizeAutomationRun, updateLastTool,
    };
    const handleEvent = (ev: WsEvent) => {
      dispatchEvent(ev, eventCtx);
    };

    const session = new Session(sessionId, workspace || "", agent, {
      onEvent: handleEvent,
      onOpen: () => {
        setConnected(true);
        // Auto-send the task prompt once a "Run now" session connects.
        const p = pendingPromptRef.current;
        if (p) {
          pendingPromptRef.current = null;
          setItems((prev) => [...prev, { kind: "user", text: p, ts: Date.now() / 1000 }]);
          sessionRef.current?.userMessage(p);
        }
      },
      onClose: () => setConnected(false),
    });
    sessionRef.current = session;
    return () => session.close();
    // NOTE: `workspace` is intentionally NOT a dependency. Every real workspace change
    // (pick folder, select/switch session, new session) is paired with a `sessionId`
    // change, so the socket still reconnects when it should. The one workspace-only change
    // is the `ready` handler adopting the server's provisioned Cowork scratch dir — listing
    // `workspace` here made that adoption tear down and rebuild the socket immediately after
    // first connect, dropping the user's first message (the "send twice" bug). The scratch
    // dir is deterministic from `sessionId` server-side, so skipping that reconnect is safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [booting, sessionId, agent, refreshSessions]);

  // Stream-following (FB-004): auto-scroll only while the user is AT the bottom, so scrolling
  // up to read during a streaming turn sticks. `atBottomRef` is the live truth (per scroll
  // event, no re-render); `following` mirrors it into state for the jump-to-latest pill.
  // Programmatic smooth-scrolls fire scroll events of their own — while one is in flight
  // (`autoScrollingRef`) they must not read as "the user scrolled up", or every stream tick
  // would disengage its OWN follow. The animation only moves down, so a decreasing scrollTop
  // mid-flight can only be the user taking over.
  const atBottomRef = useRef(true);
  const autoScrollingRef = useRef(false);
  const lastScrollTopRef = useRef(0);
  const [following, setFollowing] = useState(true);
  const scrollDebounceRef = useRef<ReturnType<typeof requestAnimationFrame> | null>(null);
  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    // Debounce: coalesce multiple scroll requests into one per frame.
    // Prevents competing smooth-scroll animations during rapid streaming.
    if (scrollDebounceRef.current) return;
    scrollDebounceRef.current = requestAnimationFrame(() => {
      scrollDebounceRef.current = null;
      if (!scrollRef.current) return;
      autoScrollingRef.current = true;
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  }, []);
  const followLatest = useCallback(() => {
    atBottomRef.current = true;
    setFollowing(true);
    scrollToBottom();
  }, [scrollToBottom]);
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const top = el.scrollTop;
    const atBottom = el.scrollHeight - top - el.clientHeight < 48;
    if (autoScrollingRef.current) {
      if (atBottom) autoScrollingRef.current = false; // landed
      else if (top >= lastScrollTopRef.current) {
        lastScrollTopRef.current = top; // still animating down — not the user
        return;
      } else autoScrollingRef.current = false; // moved UP mid-flight — user takeover
    }
    lastScrollTopRef.current = top;
    atBottomRef.current = atBottom;
    setFollowing(atBottom);
  }, []);
  // A different session is a fresh viewport — never inherit a scrolled-up state. Declared
  // BEFORE the auto-scroll effect: when a session switch and its hydrated items land in one
  // commit, the reset must run first or the stale ref would skip the initial bottom-scroll.
  useEffect(() => {
    atBottomRef.current = true;
    setFollowing(true);
  }, [sessionId]);
  // Auto-scroll on new items (messages, tool results). Streaming text changes
  // are NOT a dependency — they fire every rAF frame and would cause competing
  // scroll animations. Instead, streaming scroll is handled by the streaming
  // ref length check below.
  useEffect(() => {
    if (atBottomRef.current) scrollToBottom();
  }, [items, scrollToBottom]);
  // Streaming scroll: check periodically during active streaming via the
  // existing rAF cycle. The streamingRef update in useStreamState already
  // triggers re-renders via _setStreaming; we piggyback on those renders.
  const prevStreamLenRef = useRef(0);
  useEffect(() => {
    const len = streaming.length;
    // Only scroll when streaming grows significantly (every ~200 chars)
    if (atBottomRef.current && len > 0 && len - prevStreamLenRef.current > 200) {
      prevStreamLenRef.current = len;
      scrollToBottom();
    }
    if (len === 0) prevStreamLenRef.current = 0;
  }, [streaming, scrollToBottom]);

  // Track produced-file count for the topbar "Artifacts" affordance (works even when the rail is
  // hidden, where the rail itself doesn't fetch). Cowork only; refreshes on file writes/turn end.
  useEffect(() => {
    if (agent !== "cowork" || surface !== "session") {
      setArtifactCount(0);
      return;
    }
    getArtifacts(sessionId).then((a) => setArtifactCount(a.length)).catch(() => {});
  }, [agent, surface, sessionId, browserRefreshKey]);

  // Keep the active session's pending Inbox items fresh (answer-in-context card). Loads on session
  // change + after each turn, plus a slow poll so an unattended agent's new question surfaces.
  useEffect(() => {
    if (surface !== "session") return;
    const load = () => {
      if (document.hidden) return; // skip poll when tab is hidden
      refreshInbox();
      getUnattended(sessionId).then(markUnattended).catch(() => markUnattended(false));
    };
    load();
    const t = setInterval(load, 15000); // push-first; slow poll as fallback
    return () => clearInterval(t);
  }, [surface, sessionId, browserRefreshKey, markUnattended, refreshInbox]);

  const send = (text: string, attachments?: Attachment[], skill?: string) => {
    // Force-run shows exactly what the user typed: "/name rest". Must match the server's
    // `display` sidecar formula so the turn_start dedupe recognizes the local echo.
    const shown = skill ? `/${skill}${text ? ` ${text}` : ""}` : text;
    setItems((p) => [...p, { kind: "user", text: shown, attachments, ts: Date.now() / 1000 }]);
    // The visible model rides along with the message (single source of truth per turn).
    sessionRef.current?.userMessage(text, attachments, model, skill);
    followLatest(); // sending always re-engages stream-following, wherever the user had scrolled
  };
  // Resolving a LIVE prompt also resolves its parked Inbox mirror server-side, but the polled
  // `sessionInbox` copy stays "pending" for up to a poll cycle — long enough for the docked
  // answer-in-context card to flash the SAME request again right after the user answered it
  // (tester catch 2026-07-12: a Slack send "asked twice"). Drop the mirror optimistically;
  // the 4s poll restores anything genuinely still pending.
  const dropSessionInbox = (kind: string) =>
    setSessionInbox((cur) => cur.filter((it) => it.kind !== kind));
  const approve = (decision: ApprovalDecision) => {
    setItems((p) => resolveLastApproval(p, decision));
    dropSessionInbox("approval");
    sessionRef.current?.approve(decision);
  };
  const respondPlan = (approved: boolean, mode?: string, feedback?: string) => {
    setItems((p) => resolveLastPlan(p, approved ? "approved" : "rejected"));
    dropSessionInbox("plan");
    sessionRef.current?.respondPlan(approved, mode, feedback);
    if (approved && mode) setMode(mode); // the server flips the live engine to this mode
  };
  const respondDirectory = (granted: boolean, path?: string, writable?: boolean) => {
    setItems((p) => resolveLastDirReq(p, granted ? "granted" : "denied"));
    dropSessionInbox("directory");
    sessionRef.current?.respondDirectory(granted, path, writable);
  };
  const answerQuestion = (answer: string) => {
    setItems((p) => resolveLastQuestion(p, answer));
    dropSessionInbox("question");
    sessionRef.current?.respondQuestion(answer);
  };
  const prefillComposer = (text: string, attachments?: Attachment[]) =>
    setComposerPrefill((p) => ({ text, attachments, nonce: (p?.nonce ?? 0) + 1 }));
  const interrupt = () => sessionRef.current?.interrupt();
  const retry = () => {
    // Optimistic running: turn_start confirms; a rejected retry still ends in turn_done.
    setRunning(true);
    sessionRef.current?.retry();
  };
  const changeMode = (m: string) => {
    setMode(m);
    sessionRef.current?.setMode(m);
  };
  const changeModel = (m: string) => {
    if (running) return; // the server refuses mid-turn rebinds — don't let the header lie
    setModel(m);
    sessionRef.current?.setModel(m);
  };

  const startNewSession = (forAgent?: string) => {
    const target = forAgent || agent;
    setSurface("session"); // return to the conversation view if we were on a sub-view
    setItems([]);
    setUsage(emptyUsage());
    setStreaming("");
    setTodo([]);
    setRunning(false);
    // "New session" under a browsed persona switches to it (expand≠switch: the header alone
    // doesn't switch; this explicit action does).
    if (target !== agent) {
      setAgent(target);
      if (gatesWorkspace(target)) {
        // Never inherit the previous persona's folder — it may be a scratch dir. Clearing it
        // also blocks the connection effect, so nothing can chat behind the open gate.
        setWorkspace(null);
        setBranch(null);
        setShowGate(true);
      } else setShowGate(false);
    }
    // Knowledge family: a new conversation starts fresh (orphan) — clear the workspace so the
    // server provisions a NEW scratch dir for the new session id. Code keeps its repo.
    if (!gatesWorkspace(target)) setWorkspace(null);
    setSessionId(newId());
  };
  // Inbox → session: the item carries its session's workspace/agent, so open it directly.
  // UX-026: 5s top-right toast when a SCHEDULED automation run starts (never for
  // manual Run-now — the user is already watching). Rides the app-wide /ws/events
  // stream; View run opens the run's live session.
  const [runToast, setRunToast] = useState<{
    title: string; sessionId: string; workspace: string; agent: string; time: string;
  } | null>(null);
  useEffect(() => {
    const stop = connectEvents((msg) => {
      if (msg.type === "sessions_changed") {
        refreshSessions();
        return;
      }
      if (msg.type === "inbox_changed") {
        refreshInbox();
        return;
      }
      if (msg.type !== "automation_run_started") return;
      const d = (msg.data ?? {}) as Record<string, string>;
      setRunToast({
        title: d.task_title || "Automation",
        sessionId: d.session_id || "",
        workspace: d.workspace || "",
        agent: d.agent || "cowork",
        time: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
      });
      announceAutomationsChanged(); // the Scheduled band's badge is now stale
    });
    return stop;
  }, [refreshSessions, refreshInbox]);
  useEffect(() => {
    if (!runToast) return;
    const t = window.setTimeout(() => setRunToast(null), 5000);
    return () => window.clearTimeout(t);
  }, [runToast]);

  const openSessionFromInbox = (sid: string, ws: string, ag: string) => selectSession(sid, ws, ag);
  const selectSession = async (id: string, ws: string, ag: string) => {
    setSurface("session"); // selecting a conversation always returns to the conversation view
    setTodo([]);
    setStreaming("");
    setRunning(false);
    if (ag) setAgent(ag);
    if (!gatesWorkspace(ag)) setShowGate(false);
    if (ws && ws !== workspace) {
      setWorkspace(ws); // switch project to the session's folder
      setBranch(null);
    }
    setSessionId(id);
    try {
      const messages = await getSessionMessages(id);
      setItems(itemsFromMessages(messages));
      setUsage(usageFromMessages(messages));
    } catch {
      setItems([]);
      setUsage(emptyUsage());
    }
  };
  const switchAgent = async (name: string) => {
    setSurface("session");
    if (name === agent) return;
    rememberLastSession(agent, sessionId, workspace);
    const knownSessions = sessions.length ? sessions : await getSessions().catch(() => []);
    const knownProjects = projects.length ? projects : await getRecentWorkspaces().catch(() => []);
    const target = resumeTargetForAgent(name, knownSessions);

    setAgent(name);
    setItems([]);
    setUsage(emptyUsage());
    setStreaming("");
    setTodo([]);
    setRunning(false);

    // The live workspace is only a valid fallback for a gated persona if it came from
    // another gated persona — a knowledge persona's workspace is a scratch dir, and a
    // code-family session must never adopt one. (`agent` is still the previous persona here.)
    const inheritable = gatesWorkspace(agent) ? workspace : null;

    if (target) {
      // Code falls back to a recent folder; Cowork resumes its scratch (target.workspace) or
      // starts orphan ("" → server provisions). Chat has no workspace.
      const targetWorkspace = gatesWorkspace(name)
        ? target.workspace || fallbackWorkspace(inheritable, knownProjects)
        : needsWorkspace(name)
          ? target.workspace || ""
          : "";
      if (targetWorkspace && targetWorkspace !== workspace) {
        setWorkspace(targetWorkspace);
        setBranch(null);
      } else if (!targetWorkspace) {
        setWorkspace(null); // orphan cowork: clear so the next `ready` adopts a fresh scratch
      }
      if (!gatesWorkspace(name)) setShowGate(false);
      else if (targetWorkspace) setShowGate(false);
      else setShowGate(true);
      setSessionId(target.sessionId);
      try {
        const messages = await getSessionMessages(target.sessionId);
        setItems(itemsFromMessages(messages));
        setUsage(usageFromMessages(messages));
      } catch {
        setItems([]);
        setUsage(emptyUsage());
      }
      return;
    }

    const id = newId();
    const fallback = gatesWorkspace(name) ? fallbackWorkspace(inheritable, knownProjects) : "";
    if (fallback && fallback !== workspace) {
      setWorkspace(fallback);
      setBranch(null);
    } else if (!fallback && needsWorkspace(name)) {
      setWorkspace(null); // orphan cowork: server provisions a fresh scratch on connect
    }
    setSessionId(id);
    rememberLastSession(name, id, fallback);
    if (!gatesWorkspace(name)) setShowGate(false);
    else setShowGate(!fallback);
  };
  const chooseWorkspace = (path: string, b?: string | null) => {
    setWorkspace(path);
    setBranch(b ?? null);
    setShowGate(false);
    setGateCreate(false);
    setItems([]);
    setUsage(emptyUsage());
    setStreaming("");
    setTodo([]);
    setSessionId(newId());
    getRecentWorkspaces().then(setProjects).catch(() => {});
  };
  // "New project" lives under a project-scoped persona's accordion. Switch to that persona, start a
  // fresh session with no folder yet, and open the gate in create mode — so the gate's
  // surface==="session" && gatesWorkspace(agent) guard passes even if the active session was Chat/Cowork.
  const newProject = (forAgent?: string) => {
    const target = forAgent || agent;
    setSurface("session");
    setItems([]);
    setUsage(emptyUsage());
    setStreaming("");
    setTodo([]);
    setRunning(false);
    if (target !== agent) setAgent(target);
    setWorkspace(null);
    setBranch(null);
    setSessionId(newId());
    setGateCreate(true);
    setShowGate(true);
  };
  const renameConversation = async (id: string, title: string) => {
    const res = await renameSession(id, title);
    if (res.ok) refreshSessions();
  };
  const togglePinned = async (id: string, pinned: boolean) => {
    await setSessionFlags(id, { pinned });
    refreshSessions();
  };
  const toggleArchived = async (id: string, archived: boolean) => {
    await setSessionFlags(id, { archived });
    refreshSessions();
    // Archiving the open chat: leave it and start fresh (it moves to the Archived section).
    if (archived && id === sessionId) {
      setItems([]);
      setUsage(emptyUsage());
      setStreaming("");
      setTodo([]);
      setRunning(false);
      setSessionId(newId());
    }
  };
  const deleteConversation = async (id: string) => {
    const res = await deleteSession(id);
    if (!res.ok) return;
    refreshSessions();
    if (id === sessionId) {
      setItems([]);
      setUsage(emptyUsage());
      setStreaming("");
      setTodo([]);
      setRunning(false);
      setSessionId(newId());
    }
  };

  // "Run now": prepare a manual run, open its session, and auto-send the task so the agent
  // runs LIVE in the main view; finalize it in history once the first turn finishes.
  const openRunSession = (
    sessionId: string,
    ws: string,
    ag: string,
    task?: { id: string; title: string },
  ) => {
    setRunContext(task ?? null);
    setSurface("session");
    setShowGate(false);
    selectSession(sessionId, ws, ag);
  };
  const runTaskNow = async (taskId: string, title?: string) => {
    const r = await runAutomation(taskId);
    if (!r || !r.ok) return;
    pendingPromptRef.current = r.prompt;
    activeRunRef.current = { taskId, runId: r.run_id, sessionId: r.session_id };
    openRunSession(r.session_id, r.workspace, r.agent, { id: taskId, title: title || "" });
  };

  const idle = items.length === 0 && !streaming;
  const pendingApproval = [...items].reverse().find((i) => i.kind === "approval" && !i.resolved);
  const pendingDirReq = [...items].reverse().find((i) => i.kind === "dirreq" && !i.resolved);
  const pendingPlan = [...items].reverse().find((i) => i.kind === "planreq" && !i.resolved);
  const pendingQuestion = [...items].reverse().find((i) => i.kind === "question" && !i.resolved);
  // Facts subtitle (§22): the session's FIXED facts, not controls — model (+ the
  // workspace folder for project-scoped sessions). Renders only once the session has history;
  // until then the model is still choosable in the composer, so there's no locked fact to state.
  const hasHistory = items.length > 0;
  // Curated labels read "Claude Opus 4.8 · Anthropic" — the provider suffix is dropdown context,
  // noise in a facts line. Fall back to the raw id without its provider prefix.
  const modelDisplay =
    modelLabels[model]?.split(" · ")[0] ||
    (model.includes(":") ? model.split(":").slice(1).join(":") : model);
  // Persona name dropped for this release (owner ask 2026-07-22): personas are hidden,
  // so "Coworker" read as noise. The model (+ project folder) are the real fixed facts.
  const subtitleParts = [modelDisplay];
  if (isProjectScoped(personaOf(agent)) && workspace) subtitleParts.push(baseName(workspace));
  const activeInfo = sessions.find((s) => s.session_id === sessionId);
  const activeTitle = activeInfo?.title || "New session";

  const desktop = isTauri();
  // Dev-only: `?overlay=1` simulates the desktop overlay layout in the browser (adds the
  // tauri-overlay class + draws fake traffic lights at the real position) so the top-left can be
  // tuned in the preview without a DMG build. Never active in the real app (isTauri() short-circuits).
  const simOverlay = !desktop && new URLSearchParams(window.location.search).has("overlay");
  // Overlay layout is macOS-ONLY: Windows/Linux keep the native title bar, so the mac
  // compensations (traffic-light insets, lowered top strips) must not apply there —
  // they rendered as misalignments under Windows' native bar (caught 2026-07-21).
  const overlay = (desktop && platformOS() === "macos") || simOverlay;
  const beginWindowDrag = (event: PointerEvent) => {
    if (!desktop || event.button !== 0) return;
    startWindowDrag();
  };

  if (booting || !uiReady) {
    return (
      <div className={"app boot-splash" + (overlay ? " tauri-overlay" : "")}>
        {/* overlay (not desktop): ?overlay=1 previews the splash's top-left in the browser
            too — the wordmark/traffic-light alignment is exactly what it exists to tune. */}
        {overlay && (
          <div className="titlebar-drag" data-tauri-drag-region>
            <span className="titlebar-brand brand-wordmark">
              <Icon name="logo" size={13} className="mark" /> {t("session:title")}<span className="beta-tag">{t("session:beta")}</span>
            </span>
          </div>
        )}
        {simOverlay && (
          <div className="sim-traffic-lights" aria-hidden="true">
            <span /><span /><span />
          </div>
        )}
        {/* The real WeruBWorker mark (6-point star, same as the app/tray icon) — the old
            ✦ text glyph was a 4-point sparkle that read as another product's logo. */}
        <div className="boot-mark">
          <Icon name="logo" size={38} />
        </div>
        <div className="boot-text">
          {resumedExisting ? t("session:restoringSession") : t("session:startingUp")}
          <span className="beta-tag">{t("session:beta")}</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={
        "app" +
        (overlay ? " tauri-overlay" : "") +
        (navCollapsed ? " nav-collapsed" : "") +
        (navCollapsed && navPeek ? " nav-peek" : "")
      }
    >
      {/* Dev-only fake traffic lights so ?overlay=1 previews the real desktop top-left. */}
      {simOverlay && (
        <div className="sim-traffic-lights" aria-hidden="true">
          <span /><span /><span />
        </div>
      )}
      {/* Desktop-only auto-update prompt (15s after boot, then every 30 min; inert in browser). */}
      <UpdateBanner />
      {/* UX-026: automation-start toast — quiet panel, neutral dot/drain, accent only
          on the action (rev 2); auto-dismisses with the 5s drain bar. */}
      {runToast && (
        <div
          className="fixed top-3 right-3 z-[45] w-[290px] bg-panel border border-line rounded-xl shadow-lg px-3.5 pt-3 pb-2.5"
          data-testid="automation-toast"
        >
          <div className="flex items-center gap-2 text-[12.5px] font-semibold">
            <span className="w-[7px] h-[7px] rounded-full bg-faint toast-pulse" />
            {t("session:automationStarted")}
          </div>
          <div className="text-[12.5px] text-muted mt-0.5 ml-[15px] truncate">
            {runToast.title} · {runToast.time} run
          </div>
          <div className="flex items-center justify-between ml-[15px] mt-1.5">
            <button
              className="text-[12.5px] text-accent font-medium"
              data-testid="toast-view-run"
              onClick={() => {
                selectSession(runToast.sessionId, runToast.workspace, runToast.agent);
                setRunToast(null);
              }}
            >
              {t("session:viewRun")}
            </button>
            <button
              className="text-[12px] text-faint px-0.5"
              data-testid="toast-dismiss"
              title="Dismiss"
              onClick={() => setRunToast(null)}
            >
              ✕
            </button>
          </div>
          <div className="absolute left-3 right-3 bottom-1 h-[2px] rounded bg-line overflow-hidden">
            <span className="block h-full bg-faint toast-drain" />
          </div>
        </div>
      )}
      {/* When collapsed, a thin left-edge zone peeks the nav back as a floating overlay. */}
      {navCollapsed && (
        <div
          className="nav-hover-zone"
          onMouseEnter={() => setNavPeek(true)}
          aria-hidden="true"
        />
      )}
      {/* Explicit reveal affordance while collapsed (alongside hover-peek + ⌘B) — on every
          surface EXCEPT the session view, whose topbar carries the [sidebar][+][search] cluster
          instead (§22; no duplicate reveal buttons). */}
      {navCollapsed && !navPeek && surface !== "session" && (
        <button
          className="nav-reveal-btn"
          onClick={toggleNav}
          onMouseEnter={() => setNavPeek(true)}
          title={t("session:showSidebarShortcut")}
          aria-label={t("session:showSidebar")}
        >
          <Icon name="sidebar" size={16} />
        </button>
      )}
      {onboarding && (
        <Onboarding
          onDone={(next) => {
            setOnboarding(false);
            getHealth().then((h) => setModel(h.model)).catch(() => {});
            loadSettings(); // pick up a model connected during setup (clears the composer chip)
            if (next === "gallery") {
              // The specialists tip: land on Settings ▸ Personas, where the Gallery link lives.
              openSettings("personas");
            } else if (next === "automations") {
              // "Create your first automation" (§29) lands on the Automations quickstart.
              setSurface("scheduled");
            } else if (next === "work") {
              // "Start working" teaches by landing (§24, §32): a fresh session with the rail's
              // Access section expanded. Bump after the session switch settles.
              startNewSession();
              setTimeout(openAccess, 80);
            }
          }}
        />
      )}
      <ErrorBoundary>
      <Sidebar
        agent={agent}
        workspace={workspace || ""}
        surfaces={surfaces}
        sessions={sessions}
        projects={projects}
        activeSession={sessionId}
        onSwitchAgent={switchAgent}
        onNewSession={startNewSession}
        onSelectSession={selectSession}
        onNewProject={newProject}
        onRenameSession={renameConversation}
        onDeleteSession={deleteConversation}
        onArchiveSession={toggleArchived}
        onTogglePin={togglePinned}
        onManage={openManage}
        onOpenPersona={onOpenPersonaFromSidebar}
        onManagePersonas={openManagePersonas}
        onOpenScheduled={openScheduled}
        onOpenAutomation={onOpenAutomation}
        onOpenIntegrations={openIntegrations}
        onOpenAudit={openAudit}
        onOpenAbout={openAbout}
        onOpenInbox={openInbox}
        onOpenOps={openOps}
        onOpenDev={openDev}
        onOpenDatabase={openDatabase}
        onOpenServices={openServices}
        onOpenWiki={openWiki}
        opsActive={surface === "ops"}
        devActive={surface === "dev"}
        databaseActive={surface === "database"}
        servicesActive={surface === "services"}
        wikiActive={surface === "wiki"}
        scheduledActive={surface === "scheduled"}
        integrationsActive={surface === "integrations"}
        auditActive={surface === "audit"}
        aboutActive={surface === "about"}
        inboxActive={surface === "inbox"}
        collapsed={navCollapsed}
        onCollapse={toggleNav}
        onPeekLeave={onPeekLeave}
      />
      </ErrorBoundary>
      <Suspense fallback={<div className="surface-loading" />}>
      {surface === "scheduled" ? (
        <ScheduledView
          onOpenRun={openRunSession}
          onRunNow={runTaskNow}
          initialOpenId={scheduledOpenId}
        />
      ) : surface === "integrations" ? (
        <IntegrationsView />
      ) : surface === "settings" ? (
        <SettingsView
          key={settingsTab}
          initialTab={settingsTab as any}
          onOpenPersona={(id) => openPersona(id, "settings")}
          onCreateSkill={(description) => {
            // The Skills doorway (SKILLS-SPEC §5.2): creation is a conversation. Fresh
            // session, description in the composer — the user reads and hits send. With
            // no description, the prefill invites them to finish the sentence there.
            startNewSession();
            prefillComposer(
              description
                ? `Build a new skill for me: ${description}`
                : "Build a new skill for me: (describe what the skill should do)",
            );
          }}
        />
      ) : surface === "audit" ? (
        <AuditView />
      ) : surface === "inbox" ? (
        <InboxView onOpenSession={openSessionFromInbox} />
      ) : surface === "about" ? (
        <AboutView />
      ) : surface === "ops" ? (
        <OpsView />
      ) : surface === "dev" ? (
        <DevView />
      ) : surface === "database" ? (
        <DatabaseView />
      ) : surface === "services" ? (
        <ServiceConfigView />
      ) : surface === "wiki" ? (
        <WikiView />
      ) : surface === "persona" ? (
        <PersonaView
          personaId={personaViewId || agent}
          onBack={() =>
            personaViewReturn === "settings" ? openSettings("personas") : setSurface("session")
          }
          onOpenIntegrations={() => setSurface("integrations")}
        />
      ) : null}
      </Suspense>
      {surface === "session" && (
      <ErrorBoundary>
      <div className={"main" + (surface === "session" && agent !== "chat" && !railHidden ? " rail-open" : "")}>
        <div className="main-topbar">
          {/* Left: the contextual cluster — [sidebar] [+ new session] [search] — rendered ONLY
              while the sidebar is collapsed (§22; the expanded sidebar already owns those
              actions). Clicks must not start a window drag. */}
          <div className="main-topbar-side" onPointerDown={beginWindowDrag}>
            {navCollapsed && (
              <div
                className="flex items-center gap-1"
                data-testid="topbar-cluster"
                onPointerDown={(e) => e.stopPropagation()}
              >
                <button
                  className="topbar-icon-btn"
                  onClick={toggleNav}
                  aria-label={t("session:showSidebar")}
                  title={t("session:showSidebarShortcut")}
                >
                  <Icon name="sidebar" size={16} />
                </button>
                <button
                  className="topbar-icon-btn"
                  onClick={() => startNewSession()}
                  aria-label={t("session:newSession")}
                  title={t("session:newSession")}
                >
                  <Icon name="plus" size={16} />
                </button>
                <button
                  className="topbar-icon-btn"
                  onClick={() => setSearchOpen(true)}
                  aria-label="Search"
                  title="Search"
                >
                  <Icon name="search" size={16} />
                </button>
              </div>
            )}
            {/* §32: no session-settings row up here anymore — the §23 rest/hover/click glance
                machinery retired with the drawer. "What can this touch" lives permanently on
                the rail's Access section header; the panel toggle is the one entry. */}
          </div>
          {/* Center: title + facts subtitle (§22, amended: the ⋯ menu removed — the nav row's
              hover cluster owns pin/rename/archive/delete). The title stays: with the sidebar
              collapsed it is the only session identifier, and it anchors the subtitle. */}
          <div className="main-title" onPointerDown={beginWindowDrag}>
            <span
              className={"main-title-text" + (activeInfo ? "" : " title-ghost")}
              title={activeTitle}
            >
              {activeTitle}
            </span>
            {/* Plain facts, no affordance: the persona page it used to open is hidden for
                this release (owner ask 2026-07-22). */}
            {hasHistory && (
              <span className="title-sub" data-testid="session-subtitle">
                {subtitleParts.join(" · ")}
              </span>
            )}
          </div>
          {/* Right: session-settings icon (§23) + panel toggle. Model/mode/persona chrome is
              gone — the facts live in the subtitle, the controls in the composer (§22). */}
          <div className="main-topbar-side main-topbar-actions" onPointerDown={beginWindowDrag}>
            {agent === "cowork" && railHidden && artifactCount > 0 && (
              <button
                className="topbar-artifacts-btn"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => setRailHidden(false)}
                title="Show files this conversation produced"
              >
                <Icon name="file" size={14} />
                <span>Artifacts</span>
                <span className="topbar-artifacts-count">{artifactCount}</span>
              </button>
            )}
            {/* §32: the panel toggle is the ONE session-panel entry, for every non-chat persona
                (the rail now carries Access, so code-family gets it too). */}
            {agent !== "chat" && (
              <button
                className="topbar-icon-btn"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => setRailHidden((h) => !h)}
                aria-label={railHidden ? "Show side panel" : "Hide side panel"}
                title={railHidden ? "Show side panel" : "Hide side panel"}
              >
                <Icon name="sidebarRight" size={16} />
              </button>
            )}
          </div>
        </div>
        <div className={"main-workspace" + (railHidden ? " rail-hidden" : "")}>
          <div className="main-chat">
            {/* Automation-run context (owner ask 2026-07-04): a __run__ session looked like any
                other chat with no way back to the runs list. Lives INSIDE the chat column (which
                is padded to clear the absolute glass topbar — rendering above .main-workspace put
                it underneath the topbar; owner-reported CSS bug). */}
            {sessionId.startsWith("__run__") && (
              <div
                className="flex items-center gap-2 px-4 py-2 mb-1 rounded-lg text-[12.5px] border border-line bg-accentSoft/40"
                data-testid="run-banner"
              >
                <Icon name="clock" size={14} className="text-accent shrink-0" />
                <span className="truncate text-muted">
                  Scheduled run
                  {runContext?.title ? (
                    <>
                      {" — "}
                      <span className="text-ink font-medium">{runContext.title}</span>
                    </>
                  ) : null}{" "}
                  · started by an automation
                </span>
                <button
                  className="ml-auto shrink-0 text-accent font-medium hover:underline"
                  onClick={() => {
                    if (runContext) setScheduledOpenId(runContext.id);
                    setSurface("scheduled");
                  }}
                >
                  ← Back to runs
                </button>
              </div>
            )}
            <div className="main-scroll" ref={scrollRef} onScroll={handleScroll}>
              {idle ? (
                agent === "cowork" ? (
                  <SessionIntro
                    sessionId={sessionId}
                    onOpenSessionSettings={openAccess}
                    onPrefill={prefillComposer}
                  />
                ) : (
                  <div className="hero">
                    <h1 className="greeting">
                      <span className="mark">✦</span>
                      {agent === "chat" ? "How can I help?" : t("session:letsBuild")}
                    </h1>
                    {needsWorkspace(agent) && (
                      <div className="suggestions">
                        <div className="suggest-head">{t("session:tryTask")}</div>
                        {[
                          { ico: "\u2699", text: t("session:suggestions.runTests") },
                          { ico: "\u2726", text: t("session:suggestions.readProject") },
                          { ico: "\u21BB", text: t("session:suggestions.fixBuild") },
                        ].map((s, i) => (
                          <div className="suggest" key={i} onClick={() => workspace && send(s.text)}>
                            <span className="ico">{s.ico}</span>
                            {s.text}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              ) : (
                <>
                  <Transcript
                    items={items}
                    onApprove={approve}
                    running={running}
                    onRetry={retry}
                    // §33 ref #3: sub-threshold streamed text renders INSIDE the live turn
                    // group (header when collapsed, quiet line when expanded) — never as a
                    // floating paragraph.
                    streamingText={streamMode(streaming, items, running) === "quiet" ? streaming : undefined}
                  />
                  {/* Live thinking (reasoning models): a quiet collapsed block that streams the
                      trace for anyone who expands it; folds into the answer's disclosure when
                      the message finalizes. */}
                  {running && reasoningStream && !streaming && (
                    <div className="transcript">
                      <ThinkingBlock text={reasoningStream} live />
                    </div>
                  )}
                  {/* Compaction runs between provider turns (nothing streams during it), so
                      the transient takes over the waiting slot with a specific label. */}
                  {running && compacting && <WaitingForAgent label="Compacting context…" />}
                  {running &&
                    !compacting &&
                    !reasoningStream &&
                    (!streaming || streamMode(streaming, items, running) === "hold") &&
                    !lastItemIsAssistant(items) && <WaitingForAgent />}
                  {streaming && streamMode(streaming, items, running) === "answer" && (
                    <div className="transcript">
                      <div className="bubble-assistant">
                        <div className="who">assistant</div>
                        <Markdown text={streaming} />
                        <span className="stream-cursor">▍</span>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Scrolled up while the transcript is still growing → offer the way back down.
                Zero-height strip keeps the pill floating over the scroll area, above the
                composer, without reserving layout space. */}
            {!following && (running || !!streaming) && (
              <div className="relative h-0 z-10">
                <button
                  className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-line bg-panel shadow-md text-[12px] text-muted hover:text-ink cursor-pointer whitespace-nowrap"
                  data-testid="jump-to-latest"
                  onClick={followLatest}
                >
                  <Icon name="chevronDown" size={13} />
                  {t("session:jumpToLatest")}
                </button>
              </div>
            )}

            <Composer
              mode={mode}
              model={model}
              models={models}
              modelLabels={modelLabels}
              running={running}
              connected={connected}
              modelReady={modelReady}
              onConnectModel={openModelSetup}
              onConfigureVoiceInput={() => openSettings("voice")}
              onSend={send}
              onInterrupt={interrupt}
              onModeChange={changeMode}
              onModelChange={changeModel}
              sessionId={sessionId}
              workspace={needsWorkspace(agent) ? workspace || "" : undefined}
              unattended={unattended}
              onUnattendedChange={agent !== "chat" ? toggleUnattended : undefined}
              prefill={composerPrefill}
              resetKey={sessionId}
              usage={usage}
              contextWindow={modelContextWindows[model]}
              contextBar={contextBar}
              placeholder={
                agent === "code"
                  ? "Ask the coder to build, fix, or explain…  (drop or paste files)"
                  : agent === "chat"
                    ? "Ask anything…  (drop or paste files)"
                    : "Ask the coworker…  (drop or paste files)"
              }
              approvalSlot={
                // Live inline cards are for ATTENDED sessions only; when Unattended the prompt is
                // parked in the Inbox and surfaced via the answer-in-context card below.
                !unattended && pendingPlan?.kind === "planreq" ? (
                  <PlanCard item={pendingPlan} onRespond={respondPlan} />
                ) : !unattended && pendingDirReq?.kind === "dirreq" ? (
                  <DirectoryRequestCard item={pendingDirReq} onRespond={respondDirectory} />
                ) : !unattended && pendingApproval?.kind === "approval" ? (
                  <ApprovalCard item={pendingApproval} onApprove={approve} runTask={runContext} compact />
                ) : !unattended && pendingQuestion?.kind === "question" ? (
                  // Live ask_user in an attended session — answer inline (reuses the Inbox card UI).
                  <InboxItemCard
                    item={{
                      id: "live-question",
                      session_id: sessionId,
                      kind: "question",
                      title: pendingQuestion.question,
                      body: "",
                      state: "pending",
                      resolution: null,
                      inbox: "default",
                      created_at: "",
                      resolved_at: null,
                      options: pendingQuestion.options,
                      allow_text: pendingQuestion.allow_text,
                      multi: pendingQuestion.multi,
                    }}
                    onResolve={(_id, answer) => answerQuestion(answer)}
                    compact
                  />
                ) : sessionInbox[0] ? (
                  // Unattended session blocked on an Inbox item — answer it in context.
                  <InboxItemCard item={sessionInbox[0]} onResolve={resolveSessionInbox} compact />
                ) : undefined
              }
            />
                  </div>
          <RightRail
            active={surface === "session" && agent !== "chat" && !railHidden}
            sessionId={sessionId}
            refreshKey={browserRefreshKey}
            toolNames={items.filter((i) => i.kind === "tool").map((i: any) => i.name)}
            todo={todo}
            running={running}
            onPreviewChange={onArtifactPreview}
            showArtifacts={agent === "cowork"}
            personaId={agent}
            projectScoped={isProjectScoped(personaOf(agent))}
            workspace={workspace || undefined}
            branch={branch}
            scratchPrimary={agent === "cowork"}
            openAccessKey={accessKey}
            onOpenIntegrations={() => setSurface("integrations")}
          />
        </div>
      </div>
      </ErrorBoundary>
      )}

      {/* Search from the collapsed-sidebar topbar cluster (the sidebar's own instance is
          unreachable while it's collapsed). */}
      {searchOpen && (
        <SearchModal
          sessions={sessions}
          personas={personas ?? undefined}
          onSelect={(id, ws, ag) => {
            setSearchOpen(false);
            selectSession(id, ws, ag);
          }}
          onClose={() => setSearchOpen(false)}
        />
      )}

      {showGate && surface === "session" && gatesWorkspace(agent) && (
        <FolderGate
          create={gateCreate}
          onChoose={chooseWorkspace}
          onCancel={
            workspace
              ? () => {
                  setShowGate(false);
                  setGateCreate(false);
                }
              : undefined
          }
        />
      )}
      {workspaceTrustRequest && (
        <WorkspaceTrustPrompt
          request={workspaceTrustRequest}
          onClose={() => setWorkspaceTrustRequest(null)}
        />
      )}
    </div>
  );
}

function lastItemIsAssistant(items: Item[]): boolean {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item.kind === "notice") continue;
    return item.kind === "assistant";
  }
  return false;
}

function WaitingForAgent({ label }: { label?: string }) {
  const { t } = useTranslation(["session"]);
  return (
    <div className="waiting-transcript">
      <div className="waiting-row" aria-live="polite">
        <span className="waiting-spinner" />
        <span>{label || t("session:waitingForAgent")}</span>
      </div>
    </div>
  );
}

function updateLastTool(
  items: Item[],
  name: string,
  status: string,
  preview?: string,
  hidden?: number,
  standingRule?: string,
): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const it = copy[i];
    if (it.kind === "tool" && it.name === name && it.status === "…") {
      copy[i] = {
        ...it,
        status,
        preview,
        ...(hidden ? { hidden } : {}),
        ...(standingRule ? { standingRule } : {}),
      };
      break;
    }
  }
  return copy;
}

function resolveLastApproval(items: Item[], decision: ApprovalDecision): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const it = copy[i];
    if (it.kind === "approval" && !it.resolved) {
      copy[i] = { ...it, resolved: decision };
      break;
    }
  }
  return copy;
}

function resolveLastDirReq(items: Item[], resolved: "granted" | "denied"): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const it = copy[i];
    if (it.kind === "dirreq" && !it.resolved) {
      copy[i] = { ...it, resolved };
      break;
    }
  }
  return copy;
}

function resolveLastPlan(items: Item[], resolved: "approved" | "rejected"): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const it = copy[i];
    if (it.kind === "planreq" && !it.resolved) {
      copy[i] = { ...it, resolved };
      break;
    }
  }
  return copy;
}

function resolveLastQuestion(items: Item[], answer: string): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const it = copy[i];
    if (it.kind === "question" && !it.resolved) {
      copy[i] = { ...it, resolved: answer };
      break;
    }
  }
  return copy;
}
