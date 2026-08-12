import { describe, expect, it } from "vitest";
import { streamMode, STREAM_PROMOTE_WORDS } from "./streamGate";
import type { Item } from "./types";

const USER: Item[] = [{ kind: "user", text: "build the dashboard" }];
const AFTER_TOOL: Item[] = [
  ...USER,
  { kind: "tool", id: "t1", name: "read_file", args: { path: "a.md" }, status: "ok" },
];

const words = (n: number) => Array.from({ length: n }, (_, i) => `w${i}`).join(" ");

describe("stream gate (§33 refinement #3 — one rule for all streamed text)", () => {
  it("turn-start under the threshold is HELD (spinner, nothing rendered)", () => {
    expect(streamMode("Checking", USER, true)).toBe("hold");
    expect(streamMode(words(STREAM_PROMOTE_WORDS - 1), USER, true)).toBe("hold");
  });

  it("mid-turn under the threshold is QUIET — it belongs to the live turn group", () => {
    // Short mid-turn narration stays quiet (under 8 words).
    expect(
      streamMode(
        "checking the pages…",
        AFTER_TOOL,
        true,
      ),
    ).toBe("quiet");
  });

  it("longer mid-turn text promotes to answer — no longer hidden", () => {
    // 25 words of mid-turn text now shows as answer (above 8-word threshold).
    expect(
      streamMode(
        "The quote endpoint rate-limited, so I'm checking whether the historical pages expose older pages for January closes.",
        AFTER_TOOL,
        true,
      ),
    ).toBe("answer");
  });

  it("crossing the threshold promotes to the ANSWER bubble — start and mid-turn alike", () => {
    expect(streamMode(words(STREAM_PROMOTE_WORDS), USER, true)).toBe("answer");
    expect(streamMode(words(STREAM_PROMOTE_WORDS), AFTER_TOOL, true)).toBe("answer");
  });

  it("no text → none; not running → answer (never swallow text on a settling session)", () => {
    expect(streamMode("", USER, true)).toBe("none");
    expect(streamMode("short", USER, false)).toBe("answer");
  });

  it("notices are transparent to the turn-position check", () => {
    const items: Item[] = [...AFTER_TOOL, { kind: "notice", tone: "info", text: "fyi" }];
    expect(streamMode("checking…", items, true)).toBe("quiet");
  });
});
