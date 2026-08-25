import { describe, expect, it, vi, afterEach } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import i18n from "../i18n";
import koSession from "../i18n/locales/ko/session.json";
import { SecurityView } from "./SecurityView";

// SecurityView는 useTranslation을 전혀 쓰지 않았고, 서버가 보내는 한국어 status 문구를
// 그대로 화면에 뿌리면서 그 문구로 색까지 판정하고 있었다.

const SCORE = {
  ok: true,
  overall_score: 80,
  grade: "B",
  categories: {
    ssl: { score: 25, max: 25, status: "양호", status_code: "good" },
    ports: { score: 15, max: 25, status: "주의", status_code: "caution" },
    // status_code가 없는 구버전 응답도 섞어 둔다.
    auth: { score: 5, max: 25, status: "위험" },
  },
};

vi.stubGlobal(
  "fetch",
  vi.fn(async () => ({ ok: true, json: async () => SCORE })),
);

async function renderView() {
  const view = render(<SecurityView />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return view;
}

afterEach(async () => {
  cleanup();
  await act(async () => {
    await i18n.changeLanguage("en");
  });
});

describe("SecurityView i18n", () => {
  it("영어에서 제목·점수·스캔 영역이 영문으로 렌더된다", async () => {
    const { container } = await renderView();
    expect(screen.getByText("Security Dashboard")).toBeTruthy();
    expect(screen.getByText("Overall Security Grade")).toBeTruthy();
    expect(screen.getByText("Container Image Scan")).toBeTruthy();
    expect(screen.getByText("80 pts")).toBeTruthy();

    // 하드코딩이 남아 있으면 한국어가 새어 나온다 — 서버가 보낸 status 문구 포함.
    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("서버의 status_code를 번역하고, 없으면 한국어 문구로 코드를 되짚는다", async () => {
    await renderView();
    expect(screen.getByText("Good")).toBeTruthy();
    expect(screen.getByText("Caution")).toBeTruthy();
    // status_code가 빠진 auth 항목도 "위험"이 아니라 "At risk"로 나와야 한다.
    expect(screen.getByText("At risk")).toBeTruthy();
  });

  it("한국어로 전환하면 한국어로 렌더된다", async () => {
    i18n.addResourceBundle("ko", "session", koSession, true, true);
    await act(async () => {
      await i18n.changeLanguage("ko");
    });
    await renderView();
    expect(screen.getByText("보안 대시보드")).toBeTruthy();
    expect(screen.getByText("항목별 점수")).toBeTruthy();
    expect(screen.queryByText("Security Dashboard")).toBeNull();
  });
});
