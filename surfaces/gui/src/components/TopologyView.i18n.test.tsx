import { describe, expect, it, vi, afterEach } from "vitest";
import { act, cleanup, render, screen, fireEvent } from "@testing-library/react";
import i18n from "../i18n";
import koSession from "../i18n/locales/ko/session.json";
import { TopologyView } from "./TopologyView";

// TopologyView는 useTranslation을 전혀 쓰지 않고 한국어를 하드코딩하고 있었다 —
// 영어로 전환해도 이 화면만 한국어로 남았다.

const TOPOLOGY = {
  ok: true,
  nodes: [
    { id: "n1", label: "gateway", type: "local", status: "healthy" },
    { id: "n2", label: "db-1", type: "server", host: "10.0.0.4", status: "degraded" },
  ],
  edges: [{ source: "n1", target: "n2", type: "tcp" }],
};

vi.stubGlobal(
  "fetch",
  vi.fn(async () => ({ ok: true, json: async () => TOPOLOGY })),
);

async function renderView() {
  const view = render(<TopologyView />);
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

describe("TopologyView i18n", () => {
  it("영어에서 제목·범례·상세 패널이 영문으로 렌더된다", async () => {
    const { container } = await renderView();
    expect(screen.getByText("Network Topology")).toBeTruthy();
    expect(screen.getByText("Refresh")).toBeTruthy();

    // 노드를 골라 상세 패널까지 열어야 유형·상태·연결 수가 렌더된다.
    fireEvent.click(screen.getByText("db-1"));
    expect(screen.getByText("Host")).toBeTruthy();
    expect(screen.getByText("Degraded")).toBeTruthy();
    expect(screen.getByText("1 link")).toBeTruthy();

    // 하드코딩이 남아 있으면 한국어가 새어 나온다.
    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("서버가 보낸 상태 코드가 번역된다", async () => {
    await renderView();
    fireEvent.click(screen.getByText("gateway"));
    // 예전에는 "healthy"라는 원시 코드가 그대로 화면에 나갔다.
    expect(screen.getByText("Healthy")).toBeTruthy();
    expect(screen.queryByText("healthy")).toBeNull();
  });

  it("한국어로 전환하면 한국어로 렌더된다", async () => {
    // 테스트 환경에는 영어 번들만 올라와 있다. 실제 ko 파일을 그대로 실어
    // 번역문이 로케일에 정말 들어 있는지까지 함께 검증한다.
    i18n.addResourceBundle("ko", "session", koSession, true, true);
    await act(async () => {
      await i18n.changeLanguage("ko");
    });
    await renderView();
    expect(screen.getByText("네트워크 토폴로지")).toBeTruthy();
    expect(screen.getByText("새로고침")).toBeTruthy();
    expect(screen.queryByText("Network Topology")).toBeNull();
  });
});
