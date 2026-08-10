/**
 * useSessionState — session-scoped state that persists across WS reconnects.
 *
 * Groups the "identity" state of the active session: workspace, branch, agent,
 * mode, running flag, connected flag, usage, and trust prompts.
 */
import { useState, useCallback } from "react";
import type { SessionUsage, TodoItem } from "../types";
import type { WorkspaceCommandTrust } from "../api";
import { emptyUsage } from "../usage";
import { newId } from "../appHelpers";
import type { Attachment } from "../types";

export function useSessionState() {
  const [workspace, setWorkspace] = useState<string | null>(null);
  const [branch, setBranch] = useState<string | null>(null);
  const [agent, setAgent] = useState("cowork");
  const [mode, setMode] = useState("interactive");
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);
  const [sessionId, setSessionId] = useState<string>(newId());
  const [usage, setUsage] = useState<SessionUsage>(emptyUsage());
  const [todo, setTodo] = useState<TodoItem[]>([]);
  const [showGate, setShowGate] = useState(false);
  const [workspaceTrustRequest, setWorkspaceTrustRequest] =
    useState<WorkspaceCommandTrust | null>(null);
  const [runContext, setRunContext] = useState<{ id: string; title: string } | null>(null);
  const [composerPrefill, setComposerPrefill] = useState<{
    text: string;
    attachments?: Attachment[];
    nonce: number;
  }>();

  const resetSession = useCallback(
    (newId: string, opts?: { agent?: string; workspace?: string | null }) => {
      setSessionId(newId);
      setConnected(false);
      setRunning(false);
      setUsage(emptyUsage());
      setTodo([]);
      setWorkspaceTrustRequest(null);
      setRunContext(null);
      setComposerPrefill(undefined);
      if (opts?.agent) setAgent(opts.agent);
      if (opts?.workspace !== undefined) setWorkspace(opts.workspace);
      setBranch(null);
    },
    [],
  );

  return {
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
    resetSession,
  } as const;
}
