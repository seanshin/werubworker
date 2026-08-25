import { describe, expect, it } from "vitest";
import i18n from "./index";

// i18next v21+는 복수형 키를 `_one`/`_other`로 찾는다. 예전 v20 형식(`_plural`)은 조용히
// 무시되고 단수형이 그대로 렌더된다 — "3 account" 같은 문구가 화면에 나간다.
describe("복수형 키가 v26 형식인지", () => {
  const cases: [string, string, string][] = [
    ["connectors:gmail.accountCount", "1 account", "3 accounts"],
    ["connectors:hubspot.portalCount", "1 portal", "3 portals"],
    ["session:newRuns", "1 new run", "3 new runs"],
  ];
  it.each(cases)("%s", (key, one, many) => {
    expect(i18n.t(key, { count: 1 })).toBe(one);
    expect(i18n.t(key, { count: 3 })).toBe(many);
  });

  it("로케일 파일에 v20 형식(_plural)이 남아 있지 않다", async () => {
    const mods = import.meta.glob("./locales/*/*.json", { eager: true, query: "?raw", import: "default" });
    for (const [path, raw] of Object.entries(mods)) {
      expect(String(raw), path).not.toContain("_plural");
    }
  });
});
