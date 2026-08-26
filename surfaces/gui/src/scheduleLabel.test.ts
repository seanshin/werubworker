import { describe, expect, it, beforeAll, afterAll } from "vitest";
import type { TFunction } from "i18next";
import i18n from "./i18n";
import koSession from "./i18n/locales/ko/session.json";
import { runStatus, scheduleLabel } from "./scheduleLabel";
import type { ScheduleDesc } from "./api";

// 서버가 일정을 영어 한 줄로만 보내던 시절엔 한국어 화면에 "Every day at ~5:40 PM"이
// 그대로 찍혔다. 이제 조각(`schedule_desc`)으로 받아 문구는 여기서 만든다.

const t = i18n.t.bind(i18n) as unknown as TFunction;

beforeAll(() => {
  i18n.addResourceBundle("ko", "session", koSession, true, true);
});
afterAll(async () => {
  await i18n.changeLanguage("en");
});

const DAILY: ScheduleDesc = { kind: "daily", hour: 17, minute: 40 };
const WEEKLY: ScheduleDesc = { kind: "weekly", hour: 9, minute: 0, dow: 1 };

describe("scheduleLabel", () => {
  it("영어에서 서버의 영어 한 줄과 같은 뜻을 낸다", () => {
    expect(scheduleLabel(t, DAILY, "x")).toBe("Every day at ~5:40 PM");
    expect(scheduleLabel(t, WEEKLY, "x")).toBe("Every Monday at ~9:00 AM");
  });

  it("cron 요일 규약(0=일요일)을 따른다", () => {
    // 백엔드가 라벨을 하루씩 밀어 적던 버그와 같은 자리다.
    expect(scheduleLabel(t, { kind: "weekly", hour: 9, minute: 0, dow: 0 }, "x")).toContain("Sunday");
    expect(scheduleLabel(t, { kind: "weekly", hour: 9, minute: 0, dow: 6 }, "x")).toContain("Saturday");
  });

  it("한국어에서는 시각까지 한국어 표기가 된다", async () => {
    await i18n.changeLanguage("ko");
    const s = scheduleLabel(t, DAILY, "x");
    expect(s).toContain("매일");
    expect(s).not.toMatch(/PM|AM/);
    expect(scheduleLabel(t, WEEKLY, "x")).toContain("월요일");
    await i18n.changeLanguage("en");
  });

  it("월간·1회·복잡한 cron도 다룬다", () => {
    expect(scheduleLabel(t, { kind: "monthly", hour: 8, minute: 30, dom: 15 }, "x")).toBe(
      "Monthly on day 15 at ~8:30 AM",
    );
    expect(scheduleLabel(t, { kind: "once", fire_at: "2026-09-01T10:00" }, "x")).toBe(
      "Once at 2026-09-01T10:00",
    );
    // 범위·스텝은 번역할 문장이 없다 — cron을 그대로.
    expect(scheduleLabel(t, { kind: "raw", cron: "*/5 * * * *" }, "x")).toBe("*/5 * * * *");
  });

  it("서술이 없으면 서버의 영어 한 줄로 되돌아간다", () => {
    // 구버전 서버: 번역은 못 하지만 빈 칸보다 낫다.
    expect(scheduleLabel(t, undefined, "Every day at ~5:40 PM")).toBe("Every day at ~5:40 PM");
  });
});

describe("runStatus", () => {
  it("서버가 보낸 코드를 문구로 옮긴다", async () => {
    expect(runStatus(t, "ok")).toBe("ok");
    await i18n.changeLanguage("ko");
    expect(runStatus(t, "ok")).toBe("성공");
    expect(runStatus(t, "error")).toBe("실패");
    await i18n.changeLanguage("en");
  });

  it("모르는 코드는 그대로 보여준다", () => {
    // 서버에 새 상태가 생겨도 빈 칸이 나가지 않는다.
    expect(runStatus(t, "throttled")).toBe("throttled");
    expect(runStatus(t, null)).toBe("");
  });
});
