import { describe, expect, it, vi, afterEach } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import i18n from "../i18n";
import koSession from "../i18n/locales/ko/session.json";
import { DevView } from "./DevView";

// DevView는 절반만 번역돼 있었다 — Repos·Pipelines 탭과 리포 통계·시크릿 스캔 패널이
// 한국어 하드코딩으로 남아 영어 UI에 그대로 나갔다.

const ROUTES: Record<string, unknown> = {
  "/v1/dev/config": { ok: true, configured: true, owner: "shin", repo: "werubworker" },
  "/v1/dev/repo": { name: "werubworker", default_branch: "main", description: "", open_issues_count: 0 },
  "/v1/gitea/repos": { ok: true, repos: [{ full_name: "shin/werubworker", language: "TypeScript", stars: 1, forks: 0, open_issues: 0, description: "" }] },
  "/v1/gitea/pipelines": { ok: true, pipelines: [{ name: "ci", trigger: "push", branch_filter: "main", stages: ["build", "test"] }] },
  "/v1/gitea/pipelines/runs": { ok: true, runs: [] },
};

function routeFor(url: string) {
  const path = String(url).split("?")[0];
  return ROUTES[path] ?? { ok: true, pulls: [], runs: [], events: [] };
}

vi.stubGlobal(
  "fetch",
  vi.fn(async (url: string) => ({ ok: true, json: async () => routeFor(url) })),
);

async function renderView() {
  const view = render(<DevView />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return view;
}

async function openTab(label: string | RegExp) {
  fireEvent.click(screen.getByText(label));
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(async () => {
  // auto-cleanup이 꺼져 있어, 남은 트리가 언어 변경 때 함께 다시 렌더되며 중복 매치를 만든다.
  cleanup();
  await act(async () => {
    await i18n.changeLanguage("en");
  });
});

describe("DevView i18n", () => {
  it("Repos 탭이 영문으로 렌더된다", async () => {
    const { container } = await renderView();
    await openTab(/^Repos \(/);

    expect(screen.getByText("Browse code")).toBeTruthy();
    expect(screen.getByText("Stats")).toBeTruthy();
    expect(screen.getByText("Secret scan")).toBeTruthy();
    expect(screen.getByText("Wiki → Gitea sync")).toBeTruthy();

    // 하드코딩이 남아 있으면 한국어가 새어 나온다.
    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("Pipelines 탭이 영문으로 렌더된다", async () => {
    const { container } = await renderView();
    await openTab("Pipelines");

    expect(screen.getByText("Branch: main | Stages: build → test")).toBeTruthy();
    expect(screen.getByText("Run")).toBeTruthy();
    expect(screen.getByText("Run History")).toBeTruthy();
    expect(screen.getByText("No pipeline runs yet")).toBeTruthy();

    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("한국어로 전환하면 한국어로 렌더된다", async () => {
    // 테스트 환경에는 영어 번들만 올라와 있다. 실제 ko 파일을 그대로 싣는다.
    i18n.addResourceBundle("ko", "session", koSession, true, true);
    await act(async () => {
      await i18n.changeLanguage("ko");
    });
    await renderView();
    await openTab("Pipelines");

    expect(screen.getByText("실행 이력")).toBeTruthy();
    expect(screen.getByText("실행 이력이 없습니다")).toBeTruthy();
    expect(screen.queryByText("Run History")).toBeNull();
  });
});
