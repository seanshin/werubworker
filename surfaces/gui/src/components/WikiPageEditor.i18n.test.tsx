import { describe, expect, it, vi, afterEach } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import i18n from "../i18n";
import koSession from "../i18n/locales/ko/session.json";
import { WikiPageEditor } from "./WikiPageEditor";

// WikiPageEditor는 절반만 번역돼 있었다 — 카테고리 설명 11개가 한국어 상수 테이블에
// 박혀 있어 영어 UI의 카테고리 드롭다운이 통째로 한국어였다.

vi.mock("../api", async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  getWikiCategories: vi.fn(async () => ({ categories: [] })),
  getWikiPage: vi.fn(async () => ({})),
}));

async function renderEditor() {
  const view = render(<WikiPageEditor onSave={() => {}} onCancel={() => {}} />);
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

describe("WikiPageEditor i18n", () => {
  it("영어에서 카테고리 설명이 영문으로 렌더된다", async () => {
    const { container } = await renderEditor();

    expect(screen.getByText("-- Select a category --")).toBeTruthy();
    expect(screen.getByText("Runbook — incident response steps")).toBeTruthy();
    expect(screen.getByText("General doc")).toBeTruthy();

    // 하드코딩이 남아 있으면 한국어가 새어 나온다.
    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("한국어로 전환하면 한국어로 렌더된다", async () => {
    // 테스트 환경에는 영어 번들만 올라와 있다. 실제 ko 파일을 그대로 싣는다.
    i18n.addResourceBundle("ko", "session", koSession, true, true);
    await act(async () => {
      await i18n.changeLanguage("ko");
    });
    await renderEditor();

    expect(screen.getByText("런북 — 장애 대응 절차, 단계")).toBeTruthy();
    expect(screen.queryByText("General doc")).toBeNull();
  });
});
