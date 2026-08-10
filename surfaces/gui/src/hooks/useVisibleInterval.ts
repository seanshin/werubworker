/**
 * useVisibleInterval — setInterval that pauses when the tab is hidden.
 *
 * Saves CPU / network on background tabs. The callback fires once on
 * re-focus so stale data catches up immediately.
 */
import { useEffect, useRef } from "react";

export function useVisibleInterval(callback: () => void, delayMs: number) {
  const savedCb = useRef(callback);
  savedCb.current = callback;

  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (id !== null) return;
      id = setInterval(() => savedCb.current(), delayMs);
    };

    const stop = () => {
      if (id !== null) {
        clearInterval(id);
        id = null;
      }
    };

    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        savedCb.current(); // catch up immediately
        start();
      }
    };

    document.addEventListener("visibilitychange", onVisibility);
    if (!document.hidden) start();

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [delayMs]);
}
