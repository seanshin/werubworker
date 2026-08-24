// jsdom lacks ResizeObserver, which react-window uses to measure its viewport and (for
// dynamic row heights) each row. Without it any virtualized component throws on mount, so
// the tests would only ever exercise the non-virtualized branch.
//
// The stub never fires: jsdom reports every element as 0×0 anyway, so a real implementation
// would add nothing. Components under test therefore fall back to `defaultHeight`, which is
// what makes the rendered row count deterministic here.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!("ResizeObserver" in globalThis)) {
  (globalThis as any).ResizeObserver = ResizeObserverStub;
}

// i18next must be initialized before any component renders, or `useTranslation` returns the
// key itself ("settings:modelChecklist.modelFamily") instead of the string, and every test
// that looks for real UI text fails on text that is present but unresolved.
//
// The language is pinned to English *before* importing the app's i18n module on purpose. That
// module reads the saved language on import and, when it is not "en", kicks off an async load
// of the Korean bundle and switches to it — mid-test, after assertions were written against
// English. jsdom starts with empty localStorage, so without this line the default is "ko".
localStorage.setItem("openworker-language", "en");
await import("./i18n");

export {}; // top-level `await` requires this file to be a module
