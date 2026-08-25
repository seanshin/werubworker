import { describe, expect, it, vi, afterEach } from "vitest";
import { cleanup, render, act, screen } from "@testing-library/react";
import i18n from "../i18n";
import { OpsView } from "./OpsView";

// OpsView는 부분적으로만 번역을 쓰고 있었다 — 서버 온보딩·일괄 명령 패널은 한국어를,
// 네트워크·헬스체크 표는 영어를 하드코딩했다. 두 방향 모두 확인한다.

vi.stubGlobal(
  "fetch",
  vi.fn(async () => ({ ok: true, json: async () => ({ ok: false }) })),
);

async function renderView() {
  const view = render(<OpsView />);
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

describe("OpsView i18n", () => {
  it("영어에서 한글이 새어 나오지 않는다", async () => {
    const { container } = await renderView();
    // 온보딩·일괄 명령 패널이 한국어를 하드코딩하고 있었다.
    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("한국어로 전환하면 영문 하드코딩이 남지 않는다", async () => {
    i18n.addResourceBundle("ko", "session", {
      ops: {
        title: "서버 모니터링",
        onboard: { title: "서버 온보딩" },
        batch: { title: "일괄 명령 실행" },
      },
    });
    await act(async () => {
      await i18n.changeLanguage("ko");
    });

    await renderView();
    expect(screen.getByText("서버 모니터링")).toBeTruthy();
    // 영문 하드코딩이 남아 있었다면 영어 제목이 그대로 보인다.
    expect(screen.queryByText("Server Monitoring")).toBeNull();
  });
});
