/**
 * eventHandlers — WsEvent dispatch table for App.tsx.
 *
 * Each handler receives the event data and a bag of setters/refs so it can
 * update App state without knowing about the component tree. The handlers
 * are pure functions (no hooks) collected into a lookup table.
 */

import type { Item, WsEvent } from "../types";
import type { MessageSource } from "../api";
import { addTurnUsage } from "../usage";
import { newId, normalizeTodos, FILE_WRITE_TOOLS } from "../appHelpers";

/** All setters/refs that event handlers need to update App state. */
export interface EventHandlerCtx {
  setConnected: (v: boolean) => void;
  setModel: (v: string) => void;
  setMode: (v: string) => void;
  setWorkspace: (fn: (cur: string | null) => string | null) => void;
  setWorkspaceTrustRequest: (v: any) => void;
  setRunning: (v: boolean) => void;
  setStreaming: (v: string | ((s: string) => string)) => void;
  setReasoningStream: (v: string) => void;
  setCompacting: (v: boolean) => void;
  setItems: (fn: (p: Item[]) => Item[]) => void;
  setUsage: (fn: (u: any) => any) => void;
  setTodo: (v: any[]) => void;
  setBrowserRefreshKey: (fn: (k: number) => number) => void;
  appendDelta: (text: string) => void;
  appendReasoningDelta: (text: string) => void;
  flushStream: () => { kind: "assistant"; text: string; ts: number; reasoning?: string } | null;
  unattendedRef: { current: boolean };
  reasoningRef: { current: string };
  activeRunRef: { current: { taskId: string; runId: string; sessionId: string } | null };
  sessionId: string;
  refreshSessions: () => void;
  finalizeAutomationRun: (taskId: string, runId: string) => Promise<any>;
  updateLastTool: (...args: any[]) => Item[];
}

type Handler = (d: Record<string, any>, ctx: EventHandlerCtx) => void;

const flushPartial = (ctx: EventHandlerCtx) => {
  const flushed = ctx.flushStream();
  if (flushed) ctx.setItems((p) => [...p, flushed]);
};

const handlers: Record<string, Handler> = {
  ready(d, ctx) {
    ctx.setConnected(true);
    if (d.model) ctx.setModel(d.model);
    if (d.mode) ctx.setMode(d.mode);
    if (d.command_trust?.required) ctx.setWorkspaceTrustRequest(d.command_trust);
    if (d.workspace) ctx.setWorkspace((cur) => cur || d.workspace);
  },

  turn_start(d, ctx) {
    ctx.setRunning(true);
    ctx.setStreaming("");
    ctx.setReasoningStream("");
    if (d.source?.connector) {
      const src = d.source as MessageSource;
      ctx.setItems((p) => {
        const last = p[p.length - 1];
        return last && last.kind === "connector" && (last as any).source.ts === src.ts && (last as any).source.text === src.text
          ? p
          : [...p, { kind: "connector", source: src } as any];
      });
    } else if (typeof d.input === "string" && d.input) {
      const shown = (typeof d.display === "string" && d.display) || (d.input as string);
      ctx.setItems((p) => {
        // Search backward (up to 5 recent items) for a matching local echo to dedupe
        for (let i = p.length - 1; i >= Math.max(0, p.length - 5); i--) {
          // Bind before testing: narrowing `p[i].kind` does not carry to a second `p[i]`
          // access when the index is a loop variable, so the `.text` read was unchecked.
          const prev = p[i];
          if (prev.kind === "user" && prev.text === shown) return p;
        }
        return [...p, { kind: "user", text: shown, ts: Date.now() / 1000 }];
      });
    }
  },

  assistant_delta(d, ctx) {
    ctx.appendDelta(d.text || "");
  },

  reasoning_delta(d, ctx) {
    ctx.appendReasoningDelta(d.text || "");
  },

  assistant_message(d, ctx) {
    if (d.usage) ctx.setUsage((u: any) => addTurnUsage(u, d.usage));
    const reasoning = d.reasoning || ctx.reasoningRef.current;
    if (d.text || reasoning)
      ctx.setItems((p) => [
        ...p,
        {
          kind: "assistant",
          text: d.text || "",
          ts: Date.now() / 1000,
          ...(reasoning ? { reasoning } : {}),
        },
      ]);
    ctx.setStreaming("");
    ctx.setReasoningStream("");
  },

  tool_proposed(d, ctx) {
    if (d.name === "todo_write" && (d.arguments?.todos || d.arguments?.items))
      ctx.setTodo(normalizeTodos(d.arguments.todos ?? d.arguments.items));
    ctx.setItems((p) => [
      ...p,
      { kind: "tool", id: newId(), name: d.name, args: d.arguments, status: "…" },
    ]);
  },

  permission_required(d, ctx) {
    if (ctx.unattendedRef.current) return;
    ctx.setItems((p) => [
      ...p,
      {
        kind: "approval",
        name: d.name,
        args: d.arguments,
        reason: d.reason,
        category: d.category,
        standingTarget: d.standing_target || undefined,
      },
    ]);
  },

  directory_requested(d, ctx) {
    if (ctx.unattendedRef.current) return;
    ctx.setItems((p) => [
      ...p,
      { kind: "dirreq", reason: d.reason || "", path: d.path || "", writable: !!d.writable },
    ]);
  },

  plan_proposed(d, ctx) {
    if (ctx.unattendedRef.current) return;
    ctx.setItems((p) => [...p, { kind: "planreq", plan: d.plan || "" }]);
  },

  question_requested(d, ctx) {
    ctx.setItems((p) => [
      ...p,
      {
        kind: "question",
        question: d.question || "",
        options: d.options || [],
        allow_text: d.allow_text !== false,
        multi: !!d.multi,
      },
    ]);
  },

  tool_finished(d, ctx) {
    ctx.setItems((p) =>
      ctx.updateLastTool(
        p,
        d.name,
        d.status,
        d.result_preview || d.reason,
        d.display?.hidden_by_filters,
        d.standing_rule,
      ),
    );
    if (String(d.name || "").startsWith("browser_") || FILE_WRITE_TOOLS.has(d.name)) {
      ctx.setBrowserRefreshKey((k) => k + 1);
    }
  },

  turn_end(d, ctx) {
    if (d.status === "max_iterations_exceeded")
      ctx.setItems((p) => [...p, { kind: "notice", tone: "warn", text: "Stopped: max iterations reached." }]);
  },

  model_changed(d, ctx) {
    if (d.model) ctx.setModel(d.model);
    ctx.setItems((p) => [...p, { kind: "notice", tone: "info", text: d.text || "Model switched" }]);
  },

  compacting(_d, ctx) {
    ctx.setCompacting(true);
  },

  compacted(d, ctx) {
    ctx.setItems((p) => [...p, { kind: "notice", tone: "info", text: d.text || "Context compacted" }]);
  },

  interrupted(_d, ctx) {
    flushPartial(ctx);
    ctx.setItems((p) => [...p, { kind: "notice", tone: "warn", text: "Interrupted." }]);
  },

  error(d, ctx) {
    flushPartial(ctx);
    ctx.setItems((p) => [
      ...p,
      { kind: "notice", tone: "warn", text: "Error: " + (d.error || "unknown"), retriable: true },
    ]);
  },

  input_rejected(d, ctx) {
    ctx.setItems((p) => [
      ...p,
      { kind: "notice", tone: "warn", text: d.error || "That message was rejected." },
    ]);
  },

  turn_done(_d, ctx) {
    ctx.setRunning(false);
    ctx.refreshSessions();
    ctx.setBrowserRefreshKey((k) => k + 1);
    const ar = ctx.activeRunRef.current;
    if (ar && ar.sessionId === ctx.sessionId) {
      ctx.activeRunRef.current = null;
      ctx.finalizeAutomationRun(ar.taskId, ar.runId).catch(() => {});
    }
  },
};

/**
 * Dispatch a WsEvent to the appropriate handler.
 * Returns silently for unknown event types.
 */
export function dispatchEvent(ev: WsEvent, ctx: EventHandlerCtx): void {
  const d = ev.data || {};
  if (ev.type !== "compacting") ctx.setCompacting(false);
  const handler = handlers[ev.type];
  if (handler) handler(d, ctx);
}
