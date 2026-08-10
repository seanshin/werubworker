/**
 * useInboxState — per-session inbox items + unattended toggle.
 *
 * Encapsulates the ref-mirror for unattended (WS handler reads the ref) and
 * the session-scoped inbox query/resolve cycle.
 */
import { useRef, useState, useCallback } from "react";
import {
  getInbox,
  resolveInboxItem,
  setUnattended,
  announceInboxUnlock,
  type InboxItem,
} from "../api";

export function useInboxState(
  sessionId: string,
  refreshSessions: () => void,
) {
  const [sessionInbox, setSessionInbox] = useState<InboxItem[]>([]);
  const [unattended, _setUnattended] = useState(false);
  const unattendedRef = useRef(false);

  const markUnattended = useCallback((on: boolean) => {
    unattendedRef.current = on;
    _setUnattended(on);
  }, []);

  const toggleUnattended = useCallback(
    async (on: boolean) => {
      await setUnattended(sessionId, on);
      markUnattended(on);
      if (on) announceInboxUnlock();
    },
    [sessionId, markUnattended],
  );

  const resolveSessionInbox = useCallback(
    async (id: string, resolution: string) => {
      await resolveInboxItem(id, resolution);
      getInbox(sessionId, "pending")
        .then(setSessionInbox)
        .catch(() => setSessionInbox([]));
      refreshSessions();
    },
    [sessionId, refreshSessions],
  );

  const refreshInbox = useCallback(() => {
    getInbox(sessionId, "pending")
      .then(setSessionInbox)
      .catch(() => setSessionInbox([]));
  }, [sessionId]);

  return {
    sessionInbox,
    setSessionInbox,
    unattended,
    unattendedRef,
    markUnattended,
    toggleUnattended,
    resolveSessionInbox,
    refreshInbox,
  } as const;
}
