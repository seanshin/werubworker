// SKILLS-SPEC §4.6 GUI — the transcript trust line: a load_skill tool call always renders
// as a human-readable "Used skill: X" step, whether model-invoked or forced via /skill.
import { describe, expect, it } from "vitest";
import i18n from "./i18n";
import { humanizeTool } from "./humanize";

const t = i18n.t.bind(i18n);

describe("humanizeTool(load_skill)", () => {
  it("renders the Used-skill line with the skill name", () => {
    const line = humanizeTool("load_skill", { name: "incident-summary" }, t);
    expect(line.pre).toBe("Used skill: ");
    expect(line.obj).toBe("incident-summary");
  });

  it("stays safe on null/missing args", () => {
    expect(humanizeTool("load_skill", null, t).obj).toBe("");
    expect(humanizeTool("load_skill", {}, t).obj).toBe("");
  });
});
