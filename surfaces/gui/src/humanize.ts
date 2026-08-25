// UX-015 (§33): tool calls render as English one-liners. The model does NOT emit a purpose
// per call — the stream is name+args+result — so the sentence is synthesized here from
// per-tool templates. `run_shell` is the exception: its optional `description` argument is
// model-written intent and is preferred when present. Fallback: "Used <tool> — <short args>".

import type { TFunction } from "i18next";

import { shortArgs } from "./components/ApprovalCard";

// A one-line sentence in three segments so the UI can emphasize the object:
// "Read " + <b>runbook.md</b> + " from the shared folder".
export interface HumanLine {
  pre: string;
  obj?: string;
  post?: string;
}

// Where the object sits inside the sentence. Splitting the rendered translation on a sentinel
// (rather than hardcoding pre/post) is what lets a language put the object first: English
// "Read {{obj}}" yields pre="Read ", post=""; Korean "{{obj}} 읽음" yields pre="", post=" 읽음".
// Both renderers just concatenate the three segments, so word order stays a translator's call.
const H = "humanize:";
const OBJ = "\u0000";

function line(t: TFunction, key: string, obj: string, vars: Record<string, unknown> = {}): HumanLine {
  const text = String(t(key, { ...vars, obj: OBJ }));
  const at = text.indexOf(OBJ);
  if (at < 0) return { pre: text, obj };  // translation dropped the placeholder
  return { pre: text.slice(0, at), obj, post: text.slice(at + OBJ.length) };
}

const trunc = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const baseName = (p: string) => p.replace(/\/+$/, "").split("/").pop() || p;

// send_message targets are "platform:chat" or "platform:chat:thread" — show the platform
// by name and the last human-ish segment of the chat id.
function messageTarget(target: string): { platform: string; tail: string } {
  const [platform, ...rest] = String(target).split(":");
  const chat = rest[0] || "";
  const tail = chat.includes("/") ? chat.split("/").pop() || chat : chat;
  const names: Record<string, string> = { slack: "Slack", telegram: "Telegram" };
  return { platform: names[platform] || platform, tail };
}

export function humanizeTool(name: string, args: any, t: TFunction): HumanLine {
  const a = args && typeof args === "object" ? args : {};
  const L = (key: string, obj: string, vars?: Record<string, unknown>) =>
    line(t, H + key, obj, vars);
  switch (name) {
    case "run_shell": {
      const cmd = trunc(String(a.command ?? ""), 60);
      const desc = typeof a.description === "string" && a.description.trim() ? a.description.trim() : "";
      const base = L(a.run_in_background ? "tool.startedBg" : "tool.ran", cmd);
      // The description is the model's own words — never translated, only appended.
      return desc
        ? { ...base, post: `${base.post ?? ""} — ${desc.charAt(0).toLowerCase()}${desc.slice(1)}` }
        : base;
    }
    case "shell_task_output":
      return { pre: t(H + "tool.checkedBg") };
    case "shell_task_kill":
      return { pre: t(H + "tool.stoppedBg") };
    case "read_file":
      return L("tool.read", baseName(String(a.path ?? t(H + "tool.aFile"))));
    case "write_file":
      return L("tool.wrote", baseName(String(a.path ?? t(H + "tool.aFile"))));
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff":
      return L("tool.edited", a.path ? baseName(String(a.path)) : t(H + "tool.files"));
    case "grep":
      return L("tool.searchedCode", `“${trunc(String(a.pattern ?? ""), 40)}”`);
    case "git_log":
      return { pre: t(H + "tool.gitLog") };
    case "todo_write": {
      // `todos` is current; `items` renders histories from before the rename (the old
      // key breaks Together's GLM-5.2 chat template — see coworker/tools/todo.py).
      const items = Array.isArray(a.todos) ? a.todos : Array.isArray(a.items) ? a.items : [];
      if (items.length === 1) {
        const it = items[0] || {};
        const status = String(it.status || "").replace(/_/g, " ");
        const base = L("tool.updatedPlanOne", `“${trunc(String(it.content ?? ""), 70)}”`);
        return status ? { ...base, post: `${base.post ?? ""} → ${status}` } : base;
      }
      return { pre: t(H + "tool.updatedPlanItems", { count: items.length }) };
    }
    case "send_message": {
      const { platform, tail } = messageTarget(String(a.target ?? ""));
      if (!tail) return { pre: t(H + "tool.sentMessageGeneric") };
      return L("tool.sentMessage", tail, { platform });
    }
    case "web_search":
      return L("tool.searchedWeb", `“${trunc(String(a.query ?? ""), 60)}”`);
    case "web_fetch": {
      let host = String(a.url ?? "");
      try {
        host = new URL(host).host || host;
      } catch {
        /* keep raw */
      }
      return L("tool.readWebPage", trunc(host, 50));
    }
    case "explore":
      return L("tool.sentSubAgent", `“${trunc(String(a.task ?? a.prompt ?? ""), 60)}”`);
    case "load_skill":
      // SKILLS-SPEC §4.1 #4 — the trust line: the transcript always shows the moment a
      // skill's instructions were picked up, model-invoked or forced via /skill.
      return L("tool.usedSkill", String(a.name ?? ""));
    case "ask_user":
      return { pre: t(H + "tool.askedQuestion") };
    case "propose_plan":
      return { pre: t(H + "tool.proposedPlan") };
    case "request_directory":
      return L("tool.askedFolderAccess", String(a.path ?? ""));
    default: {
      const rest = trunc(shortArgs(a), 80);
      return {
        pre: t(H + "tool.usedTool", { name }),
        ...(rest ? { post: ` — ${rest}` } : {}),
      };
    }
  }
}

// The approval card's headline (§35): the ask, phrased as the action being decided.
// run_shell leads with the model's own description ("Run a command — fetch stock data").
export function humanizeApprovalTitle(name: string, args: any, t: TFunction): HumanLine {
  const a = args && typeof args === "object" ? args : {};
  const L = (key: string, obj: string, vars?: Record<string, unknown>) =>
    line(t, H + key, obj, vars);
  switch (name) {
    case "write_file":
      return L("approval.writeObj", baseName(String(a.path ?? t(H + "tool.aFile"))));
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff":
      return L("approval.editObj", a.path ? baseName(String(a.path)) : t(H + "tool.files"));
    case "run_shell": {
      const desc = typeof a.description === "string" && a.description.trim() ? a.description.trim() : "";
      return {
        pre: t(H + "approval.runCommand"),
        ...(desc ? { post: ` — ${desc.charAt(0).toLowerCase()}${desc.slice(1)}` } : {}),
      };
    }
    case "send_message": {
      const { tail } = messageTarget(String(a.target ?? ""));
      return tail ? L("approval.sendMessage", tail) : { pre: t(H + "approval.sendMessageGeneric") };
    }
    case "send_file": {
      const { tail } = messageTarget(String(a.target ?? ""));
      return tail ? L("approval.sendFile", tail) : { pre: t(H + "approval.sendFileGeneric") };
    }
    case "create_scheduled_task":
      return a.title
        ? L("approval.createAutomation", `“${trunc(String(a.title), 60)}”`)
        : { pre: t(H + "approval.createAutomationGeneric") };
    case "save_skill":
      // SKILLS-SPEC §5.2/§7: "Add", never "install"; destination is "your skills".
      return a.name
        ? L("approval.addSkill", String(a.name))
        : { pre: t(H + "approval.addSkillGeneric") };
    default:
      return { pre: t(H + "approval.useTool", { name }) };
  }
}

// Approvals with no executed tool call (typically declined): the ask, phrased as intent.
export function humanizeAsk(name: string, args: any, t: TFunction): HumanLine {
  const a = args && typeof args === "object" ? args : {};
  const L = (key: string, obj: string, vars?: Record<string, unknown>) =>
    line(t, H + key, obj, vars);
  switch (name) {
    case "run_shell":
      return L("denied.wantedToRun", trunc(String(a.command ?? ""), 60));
    case "write_file":
      return L("denied.wantedToWrite", baseName(String(a.path ?? t(H + "tool.aFile"))));
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff":
      return L("denied.wantedToEdit", a.path ? baseName(String(a.path)) : t(H + "tool.files"));
    case "send_message": {
      const { platform, tail } = messageTarget(String(a.target ?? ""));
      if (!tail) return { pre: t(H + "denied.wantedToSendMessage") };
      return L("denied.wantedToMessage", tail, { platform });
    }
    default:
      return { pre: t(H + "denied.wantedToUse", { name }) };
  }
}
