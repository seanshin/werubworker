import { describe, expect, it, vi, afterEach } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import i18n from "../i18n";
import koSession from "../i18n/locales/ko/session.json";
import { BackupView } from "./BackupView";

// BackupView는 useTranslation을 전혀 쓰지 않고 한국어를 하드코딩하고 있었다.
// 날짜도 "ko-KR"로 고정돼 있어 영어 UI에 한국식 표기가 나갔다.

const BACKUPS = {
  ok: true,
  backups: [
    { id: "b1", timestamp: 1756000000, targets: ["db"], size_human: "12 MB", status: "completed", error: "" },
    { id: "b2", timestamp: 1756100000, targets: ["config"], size_human: "1 MB", status: "partial", error: "" },
  ],
};
const TARGETS = {
  ok: true,
  targets: [{ name: "db", file: "db.sqlite", exists: true, size_human: "12 MB" }],
};

vi.stubGlobal(
  "fetch",
  vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (String(url).endsWith("/targets") ? TARGETS : BACKUPS),
  })),
);

async function renderView() {
  const view = render(<BackupView />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return view;
}

afterEach(async () => {
  // auto-cleanup이 꺼져 있어, 남은 트리가 언어 변경 때 함께 다시 렌더되며 중복 매치를 만든다.
  cleanup();
  await act(async () => {
    await i18n.changeLanguage("en");
  });
});

describe("BackupView i18n", () => {
  it("영어에서 제목·대상·이력이 영문으로 렌더된다", async () => {
    const { container } = await renderView();
    expect(screen.getByText("Backup / Restore")).toBeTruthy();
    expect(screen.getByText("Backup Targets")).toBeTruthy();
    expect(screen.getByText("Back up everything")).toBeTruthy();
    expect(screen.getByText("Backup History")).toBeTruthy();
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.getByText("Partial")).toBeTruthy();

    // 하드코딩이 남아 있으면 한국어가 새어 나온다.
    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("한국어로 전환하면 한국어로 렌더된다", async () => {
    // 테스트 환경에는 영어 번들만 올라와 있다. 실제 ko 파일을 그대로 싣는다.
    i18n.addResourceBundle("ko", "session", koSession, true, true);
    await act(async () => {
      await i18n.changeLanguage("ko");
    });
    await renderView();
    expect(screen.getByText("백업 / 복원")).toBeTruthy();
    expect(screen.getByText("백업 이력")).toBeTruthy();
    expect(screen.queryByText("Backup / Restore")).toBeNull();
  });
});
