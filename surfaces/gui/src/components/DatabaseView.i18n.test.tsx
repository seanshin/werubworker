import { describe, expect, it, vi, afterEach } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import i18n from "../i18n";
import koSession from "../i18n/locales/ko/session.json";
import { DatabaseView } from "./DatabaseView";

// DatabaseView는 절반만 번역돼 있었다 — 네트워크 스캔 모달 전체가 한국어 하드코딩이었다.

const SCAN = {
  ok: true,
  found: [
    { host: "10.0.0.7", port: 5432, type: "postgres", label: "postgres", status: "open" },
    { host: "10.0.0.7", port: 3306, type: "mysql", label: "mysql", status: "open" },
  ],
  scanned: 254,
  network: [{ ip: "10.0.0.7", interface: "en0", subnet: "10.0.0" }],
  subnets: ["10.0.0"],
  my_ip: "10.0.0.7",
  scan_mode: "quick",
};

vi.stubGlobal(
  "fetch",
  vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      String(url).includes("/scan") ? SCAN : { ok: true, databases: [] },
  })),
);

async function openScanModal() {
  const view = render(<DatabaseView />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  fireEvent.click(screen.getByTestId("db-scan"));
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

describe("DatabaseView scan modal i18n", () => {
  it("영어에서 스캔 모달이 영문으로 렌더된다", async () => {
    const { container } = await openScanModal();

    expect(screen.getByText("Network Database Scan")).toBeTruthy();
    expect(screen.getByText("My Network")).toBeTruthy();
    expect(screen.getByText("Full scan (1-254)")).toBeTruthy();
    expect(screen.getByText("2 services")).toBeTruthy();
    expect(screen.getByText("My IP")).toBeTruthy();
    expect(screen.getByText(/2 found \/ 254 scanned/)).toBeTruthy();

    // 하드코딩이 남아 있으면 한국어가 새어 나온다.
    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("한국어로 전환하면 한국어로 렌더된다", async () => {
    // 테스트 환경에는 영어 번들만 올라와 있다. 실제 ko 파일을 그대로 싣는다.
    i18n.addResourceBundle("ko", "session", koSession, true, true);
    await act(async () => {
      await i18n.changeLanguage("ko");
    });
    await openScanModal();

    expect(screen.getByText("네트워크 데이터베이스 스캔")).toBeTruthy();
    expect(screen.getByText("내 네트워크")).toBeTruthy();
    expect(screen.queryByText("Network Database Scan")).toBeNull();
  });
});
