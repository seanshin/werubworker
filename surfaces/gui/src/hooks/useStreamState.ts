/**
 * useStreamState — encapsulates streaming text + reasoning ref-mirror pattern.
 *
 * The WebSocket handler closure captures stale React state; this hook keeps a
 * ref in sync with state so the handler can always read the live value via the
 * ref while React re-renders are driven by the state setter.
 *
 * Delta methods (appendDelta / appendReasoningDelta) accumulate text in refs
 * and coalesce React state updates to at most one per animation frame (~60fps),
 * avoiding per-token re-renders during streaming.
 */
import { useRef, useState, useCallback, useEffect } from "react";

export function useStreamState() {
  const [streaming, _setStreaming] = useState("");
  const streamingRef = useRef("");

  const [reasoning, _setReasoning] = useState("");
  const reasoningRef = useRef("");

  // rAF-based batching: accumulate in refs, flush to state once per frame.
  const rafId = useRef(0);
  const dirty = useRef(false);

  const scheduleFlushToState = useCallback(() => {
    if (dirty.current) return; // already scheduled
    dirty.current = true;
    rafId.current = requestAnimationFrame(() => {
      dirty.current = false;
      _setStreaming(streamingRef.current);
      _setReasoning(reasoningRef.current);
    });
  }, []);

  // Cleanup on unmount.
  useEffect(() => () => cancelAnimationFrame(rafId.current), []);

  /** Append streaming text (called per assistant_delta). Batched via rAF. */
  const appendDelta = useCallback(
    (text: string) => {
      streamingRef.current += text;
      scheduleFlushToState();
    },
    [scheduleFlushToState],
  );

  /** Append reasoning text (called per reasoning_delta). Batched via rAF. */
  const appendReasoningDelta = useCallback(
    (text: string) => {
      reasoningRef.current += text;
      scheduleFlushToState();
    },
    [scheduleFlushToState],
  );

  /** Imperative setter — bypasses batching (used for reset / direct set). */
  const setStreaming = useCallback((value: string | ((s: string) => string)) => {
    streamingRef.current =
      typeof value === "function" ? value(streamingRef.current) : value;
    _setStreaming(streamingRef.current);
  }, []);

  const setReasoning = useCallback((value: string) => {
    reasoningRef.current = value;
    _setReasoning(value);
  }, []);

  const [compacting, setCompacting] = useState(false);

  /** Flush any partial streaming/reasoning into a finalized item shape. */
  const flush = useCallback(() => {
    // Cancel any pending rAF — we're flushing everything now.
    cancelAnimationFrame(rafId.current);
    dirty.current = false;
    const partial = streamingRef.current;
    const thinking = reasoningRef.current;
    streamingRef.current = "";
    reasoningRef.current = "";
    _setStreaming("");
    _setReasoning("");
    if (!partial && !thinking) return null;
    return {
      kind: "assistant" as const,
      text: partial,
      ts: Date.now() / 1000,
      ...(thinking ? { reasoning: thinking } : {}),
    };
  }, []);

  const reset = useCallback(() => {
    cancelAnimationFrame(rafId.current);
    dirty.current = false;
    streamingRef.current = "";
    reasoningRef.current = "";
    _setStreaming("");
    _setReasoning("");
    setCompacting(false);
  }, []);

  return {
    streaming,
    setStreaming,
    streamingRef,
    reasoning,
    setReasoning,
    reasoningRef,
    compacting,
    setCompacting,
    appendDelta,
    appendReasoningDelta,
    flush,
    reset,
  } as const;
}
