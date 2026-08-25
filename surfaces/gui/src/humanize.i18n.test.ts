import { afterEach, describe, expect, it } from "vitest";
import i18n from "./i18n";
import { humanizeApprovalTitle, humanizeAsk, humanizeTool } from "./humanize";

// humanize.ts는 t가 없는 순수 모듈이라 영어 문장을 직접 조립했다. 이제 t를 받는다.
// 핵심은 어순 — HumanLine은 pre + <강조>obj</강조> + post 세 조각을 이어 붙이므로,
// 번역문의 {{obj}} 위치가 목적어가 문장 어디에 놓일지를 정한다.

const t = () => i18n.t.bind(i18n);

afterEach(async () => {
  await i18n.changeLanguage("en");
});

describe("humanize 어순", () => {
  it("영어는 동사가 앞, 목적어가 뒤", () => {
    const line = humanizeTool("read_file", { path: "/srv/runbook.md" }, t());
    expect(line.pre).toBe("Read ");
    expect(line.obj).toBe("runbook.md");
    expect(line.post).toBe("");
  });

  it("한국어는 목적어가 앞, 동사가 뒤로 간다", async () => {
    i18n.addResourceBundle("ko", "humanize", { tool: { read: "{{obj}} 읽음" } });
    await i18n.changeLanguage("ko");

    const line = humanizeTool("read_file", { path: "/srv/runbook.md" }, t());
    // 목적어가 문장 맨 앞 — pre가 비고 동사가 post로 넘어간다.
    expect(line.pre).toBe("");
    expect(line.obj).toBe("runbook.md");
    expect(line.post).toBe(" 읽음");
    // 어느 언어에서든 세 조각을 이으면 완전한 문장이 된다.
    expect(line.pre + line.obj + line.post).toBe("runbook.md 읽음");
  });

  it("목적어가 없는 줄도 번역된다", async () => {
    i18n.addResourceBundle("ko", "humanize", { tool: { askedQuestion: "질문함" } });
    await i18n.changeLanguage("ko");
    expect(humanizeTool("ask_user", {}, t()).pre).toBe("질문함");
  });

  it("승인 제목과 거절 줄도 번역된다", async () => {
    i18n.addResourceBundle("ko", "humanize", {
      approval: { writeObj: "{{obj}} 쓰기" },
      denied: { wantedToRun: "{{obj}} 실행하려 함" },
    });
    await i18n.changeLanguage("ko");

    const title = humanizeApprovalTitle("write_file", { path: "a/b/report.md" }, t());
    expect(title.pre + title.obj + title.post).toBe("report.md 쓰기");

    const ask = humanizeAsk("run_shell", { command: "ls -al" }, t());
    expect(ask.pre + ask.obj + ask.post).toBe("ls -al 실행하려 함");
  });

  it("모델이 쓴 description은 번역하지 않고 덧붙인다", () => {
    const line = humanizeTool(
      "run_shell",
      { command: "git log", description: "List merges" },
      t(),
    );
    expect(line.obj).toBe("git log");
    expect(line.post).toContain("list merges");
  });
});
