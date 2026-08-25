import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { List, useDynamicRowHeight, useListRef, type RowComponentProps } from "react-window";

const CARD = "rounded-xl2 border border-line bg-panel";

// The viewer holds `limit=500` entries and re-fetches every 10s. Rendered plainly that is
// ~2,500 DOM nodes torn down and rebuilt on every refresh, which is what made scrolling
// stutter while a refresh landed. Above the threshold the rows are virtualized instead, so
// the node count tracks the viewport rather than the result size.
const VIRTUAL_THRESHOLD = 60;
// Log lines wrap (`whitespace-pre-wrap`), so row heights genuinely vary — a stack trace is
// several times a one-line entry. `useDynamicRowHeight` measures them rather than forcing a
// fixed height, which would either clip long lines or leave gaps after short ones.
const EST_ROW_HEIGHT = 20;

interface LogEntry {
  ts: number;
  server_id: string;
  line: string;
  severity: string;
  source_id: string;
  matched_pattern: string;
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  error: "#ef4444",
  warning: "#f59e0b",
  info: "#3b82f6",
  debug: "#6b7280",
};

function formatTs(epoch: number, locale: string): string {
  if (!epoch) return "";
  const d = new Date(epoch * 1000);
  // The locale follows the UI language: hardcoding "ko-KR" rendered "7시 13분 20초" in the
  // English UI. `hour12: false` stays — a log console wants a fixed-width 24h clock whatever
  // the locale's default is.
  return d.toLocaleTimeString(locale, { hour12: false });
}

export function LogView() {
  const { t, i18n } = useTranslation(["common"]);
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [serverFilter, setServerFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [searchPattern, setSearchPattern] = useState("");
  const [servers, setServers] = useState<string[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useListRef(null);
  const rowHeight = useDynamicRowHeight({ defaultRowHeight: EST_ROW_HEIGHT });

  const fetchLogs = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (serverFilter) params.set("server_id", serverFilter);
    if (severityFilter) params.set("severity", severityFilter);
    if (searchPattern) params.set("pattern", searchPattern);
    params.set("limit", "500");
    fetch(`/v1/dashboard/logs?${params}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) setEntries(d.entries || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [serverFilter, severityFilter, searchPattern]);

  const fetchServers = useCallback(() => {
    fetch("/v1/dashboard/logs/servers")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) setServers(d.servers || []);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchLogs();
    fetchServers();
  }, [fetchLogs, fetchServers]);

  // Auto-refresh every 10s
  useEffect(() => {
    const id = setInterval(fetchLogs, 10_000);
    return () => clearInterval(id);
  }, [fetchLogs]);

  // Auto-scroll. The virtualized list owns its own scroll container, so pinning the outer
  // div's scrollTop would do nothing there — ask the list to scroll to the last row instead.
  useEffect(() => {
    if (!autoScroll || entries.length === 0) return;
    if (entries.length > VIRTUAL_THRESHOLD) {
      listRef.current?.scrollToRow({ index: entries.length - 1, align: "end" });
    } else if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [entries, autoScroll, listRef]);

  const severities = ["", "critical", "error", "warning", "info", "debug"];

  return (
    <div className="flex flex-col h-full gap-3 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("common:monitoring.log.title")}</h2>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-muted">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
            />
            {t("common:monitoring.log.autoScroll")}
          </label>
          <button
            onClick={fetchLogs}
            disabled={loading}
            className="text-xs px-2 py-1 rounded bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            {loading ? t("common:monitoring.log.loading") : t("common:monitoring.log.refresh")}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <select
          value={serverFilter}
          onChange={(e) => setServerFilter(e.target.value)}
          className="text-xs px-2 py-1 rounded border border-line bg-panel"
        >
          <option value="">{t("common:monitoring.log.allServers")}</option>
          {servers.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="text-xs px-2 py-1 rounded border border-line bg-panel"
        >
          {severities.map((s) => (
            <option key={s} value={s}>{s || t("common:monitoring.log.allSeverities")}</option>
          ))}
        </select>
        <input
          type="text"
          value={searchPattern}
          onChange={(e) => setSearchPattern(e.target.value)}
          placeholder={t("common:monitoring.log.searchPlaceholder")}
          className="text-xs px-2 py-1 rounded border border-line bg-panel flex-1 min-w-[150px]"
          onKeyDown={(e) => e.key === "Enter" && fetchLogs()}
        />
      </div>

      {/* Log entries */}
      <div
        ref={containerRef}
        className={CARD + " flex-1 overflow-auto p-2 font-mono text-xs leading-5"}
      >
        {entries.length === 0 ? (
          <div className="text-center text-muted py-8">
            {loading ? t("common:monitoring.log.loadingEntries") : t("common:monitoring.log.noEntries")}
          </div>
        ) : entries.length > VIRTUAL_THRESHOLD ? (
          <List
            listRef={listRef}
            rowComponent={VirtualLogRow}
            rowProps={{ entries, locale: i18n.language }}
            rowCount={entries.length}
            rowHeight={rowHeight}
            overscanCount={10}
            style={{ height: "100%" }}
          />
        ) : (
          entries.map((e, i) => <LogRow key={i} entry={e} locale={i18n.language} />)
        )}
      </div>

      <div className="text-xs text-muted text-right">
        {t("common:monitoring.log.shown", { count: entries.length })}
      </div>
    </div>
  );
}

// One log line. Shared by both paths so the virtualized list can never drift from the plain
// one — a difference between them would only ever show up past 60 entries.
function LogRow({
  entry,
  locale,
  style,
}: {
  entry: LogEntry;
  locale: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{ ...style, borderLeft: `3px solid ${SEVERITY_COLORS[entry.severity] || "#6b7280"}` }}
      className="flex gap-2 hover:bg-paper/50 px-1 rounded"
    >
      <span className="text-muted whitespace-nowrap">{formatTs(entry.ts, locale)}</span>
      <span className="text-muted whitespace-nowrap">[{entry.server_id}]</span>
      <span
        className="font-medium whitespace-nowrap"
        style={{ color: SEVERITY_COLORS[entry.severity] || "var(--ink)" }}
      >
        {entry.severity?.toUpperCase().padEnd(8)}
      </span>
      <span className="whitespace-pre-wrap break-all">{entry.line}</span>
    </div>
  );
}

function VirtualLogRow({
  index,
  style,
  entries,
  locale,
}: RowComponentProps<{ entries: LogEntry[]; locale: string }>) {
  return <LogRow entry={entries[index]} locale={locale} style={style} />;
}
