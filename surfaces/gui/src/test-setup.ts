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
