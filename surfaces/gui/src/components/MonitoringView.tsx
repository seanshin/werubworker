import { useCallback, useEffect, useState } from "react";
import { MiniChart } from "./MiniChart";
import { ProgressBar } from "./ProgressBar";
import { Icon } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";
const POLL_MS = 30_000;

/* ── Types ─────────────────────────────────────────────── */

interface ServerInfo {
  server_id: string;
  name: string;
  host: string;
  status?: string;
  cpu_percent?: number;
  memory_percent?: number;
  disk_percent?: number;
}

interface Alert {
  id?: string;
  rule_id?: string;
  metric?: string;
  value?: number;
  threshold?: number;
  severity: string;
  message: string;
  server_id?: string;
  server_name?: string;
  fired_at?: number;
  resolved_at?: number;
}

interface Incident {
  id: string;
  title: string;
  severity: string;
  status: string;
  created_at?: number;
  updated_at?: number;
  resolved_at?: number;
  timeline?: { ts: number; text: string }[];
}

interface HealthCheck {
  name: string;
  type: string;
  target: string;
  last_status: string;
  last_check: number;
  last_latency_ms: number;
  last_error?: string;
  consecutive_failures: number;
  total_checks: number;
  total_failures: number;
}

interface AuditEntry {
  ts: number;
  user: string;
  action: string;
  target: string;
  result: string;
  detail?: string;
}

interface Webhook {
  id: string;
  url: string;
  events: string[];
  enabled: boolean;
}

interface MetricPoint {
  ts: number;
  cpu: number;
  memory: number;
  disk: number;
}

interface OverviewData {
  servers: ServerInfo[];
  server_count: number;
  active_alerts: Alert[];
  alert_count: number;
  health_checks: HealthCheck[];
  active_incidents: Incident[];
  incident_count: number;
}

/* ── Helpers ───────────────────────────────────────────── */

function relativeTime(epoch: number): string {
  if (!epoch) return "—";
  const diff = Math.floor(Date.now() / 1000 - epoch);
  if (diff < 60) return `${diff}초 전`;
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

function severityColor(sev: string): string {
  switch (sev?.toLowerCase()) {
    case "critical":
    case "p1":
      return "var(--danger)";
    case "warning":
    case "p2":
      return "var(--warn)";
    case "p3":
      return "var(--accent)";
    default:
      return "var(--accent)";
  }
}

function SeverityBadge({ severity }: { severity: string }) {
  const bg = severityColor(severity);
  return (
    <span
      className="inline-block px-2 py-0.5 rounded text-[11px] font-medium text-white"
      style={{ background: bg }}
    >
      {severity.toUpperCase()}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    open: "var(--danger)",
    investigating: "var(--warn)",
    identified: "var(--warn)",
    monitoring: "var(--accent)",
    resolved: "#22c55e",
  };
  const bg = colors[status?.toLowerCase()] || "var(--accent)";
  return (
    <span
      className="inline-block px-2 py-0.5 rounded text-[11px] font-medium text-white"
      style={{ background: bg }}
    >
      {status}
    </span>
  );
}

function TabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
        active
          ? "bg-accent text-white"
          : "text-muted hover:text-ink hover:bg-paper"
      }`}
    >
      {label}
    </button>
  );
}

/* ── Main Component ────────────────────────────────────── */

type TabId = "overview" | "alerts" | "incidents" | "healthchecks" | "audit";

export function MonitoringView() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // Overview
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [serverMetrics, setServerMetrics] = useState<Record<string, MetricPoint[]>>({});

  // Alerts
  const [activeAlerts, setActiveAlerts] = useState<Alert[]>([]);
  const [alertHistory, setAlertHistory] = useState<Alert[]>([]);
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);

  // Incidents
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [expandedIncident, setExpandedIncident] = useState<string | null>(null);

  // Health checks
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);
  const [runningHC, setRunningHC] = useState(false);

  // Audit
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);

  /* ── Fetch functions ─────────────────────────────────── */

  const fetchOverview = useCallback(() => {
    fetch("/v1/dashboard/overview")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) {
          setOverview(d);
          setHealthChecks(d.health_checks || []);
        }
      })
      .catch(() => {});
  }, []);

  const fetchServerMetrics = useCallback((serverId: string) => {
    fetch(`/v1/dashboard/servers/${encodeURIComponent(serverId)}/metrics?range=1h`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok && d.data) {
          setServerMetrics((prev) => ({ ...prev, [serverId]: d.data }));
        }
      })
      .catch(() => {});
  }, []);

  const fetchAlerts = useCallback(() => {
    fetch("/v1/dashboard/alerts")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) {
          setActiveAlerts(d.active || []);
          setAlertHistory(d.history || []);
        }
      })
      .catch(() => {});
  }, []);

  const fetchIncidents = useCallback(() => {
    fetch("/v1/dashboard/incidents")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) setIncidents(d.incidents || []);
      })
      .catch(() => {});
  }, []);

  const fetchAudit = useCallback(() => {
    fetch("/v1/dashboard/audit")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) setAuditEntries(d.entries || []);
      })
      .catch(() => {});
  }, []);

  const fetchWebhooks = useCallback(() => {
    fetch("/v1/dashboard/webhooks")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) setWebhooks(d.webhooks || []);
      })
      .catch(() => {});
  }, []);

  const fetchAll = useCallback(() => {
    fetchOverview();
    if (activeTab === "alerts") {
      fetchAlerts();
      fetchWebhooks();
    }
    if (activeTab === "incidents") fetchIncidents();
    if (activeTab === "audit") fetchAudit();
    setLastRefresh(new Date());
  }, [activeTab, fetchOverview, fetchAlerts, fetchWebhooks, fetchIncidents, fetchAudit]);

  // Initial + tab change
  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Polling
  useEffect(() => {
    const id = setInterval(fetchAll, POLL_MS);
    return () => clearInterval(id);
  }, [fetchAll]);

  // Fetch server metrics when overview loads
  useEffect(() => {
    if (overview?.servers) {
      overview.servers.forEach((s) => {
        if (s.server_id) fetchServerMetrics(s.server_id);
      });
    }
  }, [overview, fetchServerMetrics]);

  const tabs: { id: TabId; label: string }[] = [
    { id: "overview", label: "개요" },
    { id: "alerts", label: "알림" },
    { id: "incidents", label: "인시던트" },
    { id: "healthchecks", label: "헬스체크" },
    { id: "audit", label: "감사 로그" },
  ];

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-subtle">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold text-ink">모니터링 대시보드</h1>
          {lastRefresh && (
            <span className="text-[11px] text-faint">
              마지막 갱신: {lastRefresh.toLocaleTimeString("ko-KR")}
            </span>
          )}
        </div>
        <div className="flex gap-2 mt-2">
          {tabs.map((t) => (
            <TabButton
              key={t.id}
              label={t.label}
              active={activeTab === t.id}
              onClick={() => setActiveTab(t.id)}
            />
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeTab === "overview" && (
          <OverviewPanel
            overview={overview}
            serverMetrics={serverMetrics}
          />
        )}
        {activeTab === "alerts" && (
          <AlertsPanel
            active={activeAlerts}
            history={alertHistory}
            webhooks={webhooks}
          />
        )}
        {activeTab === "incidents" && (
          <IncidentsPanel
            incidents={incidents}
            expandedId={expandedIncident}
            onToggle={(id) =>
              setExpandedIncident(expandedIncident === id ? null : id)
            }
          />
        )}
        {activeTab === "healthchecks" && (
          <HealthChecksPanel
            checks={healthChecks}
            running={runningHC}
            onRunAll={() => {
              setRunningHC(true);
              fetch("/v1/ops/healthcheck/run", { method: "POST" })
                .then((r) => r.ok ? r.json() : null)
                .then(() => {
                  fetchOverview();
                })
                .catch(() => {})
                .finally(() => setRunningHC(false));
            }}
          />
        )}
        {activeTab === "audit" && <AuditPanel entries={auditEntries} />}
      </div>
    </div>
  );
}

/* ── Overview Panel ────────────────────────────────────── */

function OverviewPanel({
  overview,
  serverMetrics,
}: {
  overview: OverviewData | null;
  serverMetrics: Record<string, MetricPoint[]>;
}) {
  if (!overview) {
    return <p className="text-muted text-sm">데이터를 불러오는 중...</p>;
  }

  const cards = [
    { label: "서버", value: overview.server_count, icon: "gear" as const },
    { label: "활성 알림", value: overview.alert_count, icon: "shield" as const },
    { label: "헬스체크", value: overview.health_checks?.length ?? 0, icon: "refresh" as const },
    { label: "인시던트", value: overview.incident_count, icon: "info" as const },
  ];

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {cards.map((c) => (
          <div key={c.label} className={`${CARD} p-4 flex items-center gap-3`}>
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center"
              style={{ background: "var(--accent)", opacity: 0.15 }}
            >
              <Icon name={c.icon} size={20} className="text-accent" />
            </div>
            <div>
              <p className="text-2xl font-bold text-ink">{c.value}</p>
              <p className="text-[12px] text-muted">{c.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Server list */}
      <div>
        <h2 className="text-sm font-semibold text-ink mb-3">서버 현황</h2>
        <div className="space-y-3">
          {overview.servers.map((srv) => {
            const metrics = serverMetrics[srv.server_id] || [];
            const cpuData = metrics.map((m) => m.cpu);
            const memData = metrics.map((m) => m.memory);
            return (
              <div key={srv.server_id} className={`${CARD} p-4`}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{
                        background:
                          srv.status === "online" ? "#22c55e" : "var(--danger)",
                      }}
                    />
                    <span className="text-sm font-medium text-ink">
                      {srv.name || srv.host}
                    </span>
                  </div>
                  <span className="text-[11px] text-faint">{srv.host}</span>
                </div>
                <div className="space-y-2">
                  <ProgressBar
                    label="CPU"
                    value={srv.cpu_percent ?? 0}
                  />
                  <ProgressBar
                    label="메모리"
                    value={srv.memory_percent ?? 0}
                  />
                  <ProgressBar
                    label="디스크"
                    value={srv.disk_percent ?? 0}
                  />
                </div>
                {cpuData.length > 0 && (
                  <div className="flex gap-4 mt-3">
                    <MiniChart data={cpuData} color="var(--accent)" label="CPU" height={32} width={140} />
                    <MiniChart data={memData} color="var(--warn)" label="MEM" height={32} width={140} />
                  </div>
                )}
              </div>
            );
          })}
          {overview.servers.length === 0 && (
            <p className="text-sm text-muted">등록된 서버가 없습니다.</p>
          )}
        </div>
      </div>

      {/* Recent alerts + incidents */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Recent alerts */}
        <div>
          <h2 className="text-sm font-semibold text-ink mb-3">최근 알림</h2>
          <div className="space-y-2">
            {overview.active_alerts.slice(0, 3).map((a, i) => (
              <div key={i} className={`${CARD} p-3 flex items-start gap-2`}>
                <SeverityBadge severity={a.severity} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-ink truncate">{a.message}</p>
                  <p className="text-[11px] text-faint">
                    {a.server_name && `${a.server_name} · `}
                    {a.fired_at ? relativeTime(a.fired_at) : ""}
                  </p>
                </div>
              </div>
            ))}
            {overview.active_alerts.length === 0 && (
              <p className="text-sm text-muted">활성 알림이 없습니다.</p>
            )}
          </div>
        </div>

        {/* Recent incidents */}
        <div>
          <h2 className="text-sm font-semibold text-ink mb-3">최근 인시던트</h2>
          <div className="space-y-2">
            {overview.active_incidents.slice(0, 3).map((inc) => (
              <div key={inc.id} className={`${CARD} p-3 flex items-start gap-2`}>
                <SeverityBadge severity={inc.severity} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-ink truncate">{inc.title}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <StatusBadge status={inc.status} />
                    <span className="text-[11px] text-faint">
                      {inc.created_at ? relativeTime(inc.created_at) : ""}
                    </span>
                  </div>
                </div>
              </div>
            ))}
            {overview.active_incidents.length === 0 && (
              <p className="text-sm text-muted">활성 인시던트가 없습니다.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Alerts Panel ──────────────────────────────────────── */

function AlertsPanel({
  active,
  history,
  webhooks,
}: {
  active: Alert[];
  history: Alert[];
  webhooks: Webhook[];
}) {
  return (
    <div className="space-y-6">
      {/* Active alerts */}
      <div>
        <h2 className="text-sm font-semibold text-ink mb-3">
          활성 알림 ({active.length})
        </h2>
        <div className="space-y-2">
          {active.map((a, i) => (
            <div key={i} className={`${CARD} p-3 flex items-start gap-3`}>
              <SeverityBadge severity={a.severity} />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-ink">{a.message}</p>
                <p className="text-[11px] text-faint">
                  {a.metric && `${a.metric}: ${a.value} (임계값 ${a.threshold})`}
                  {a.server_name && ` · ${a.server_name}`}
                  {a.fired_at ? ` · ${relativeTime(a.fired_at)}` : ""}
                </p>
              </div>
            </div>
          ))}
          {active.length === 0 && (
            <p className="text-sm text-muted">활성 알림이 없습니다.</p>
          )}
        </div>
      </div>

      {/* Alert history */}
      <div>
        <h2 className="text-sm font-semibold text-ink mb-3">알림 히스토리</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted text-[12px] border-b border-subtle">
                <th className="pb-2 pr-4">심각도</th>
                <th className="pb-2 pr-4">메시지</th>
                <th className="pb-2 pr-4">서버</th>
                <th className="pb-2 pr-4">발생</th>
                <th className="pb-2">해소</th>
              </tr>
            </thead>
            <tbody>
              {history.slice(0, 20).map((a, i) => (
                <tr key={i} className="border-b border-subtle">
                  <td className="py-2 pr-4">
                    <SeverityBadge severity={a.severity} />
                  </td>
                  <td className="py-2 pr-4 text-ink">{a.message}</td>
                  <td className="py-2 pr-4 text-muted">{a.server_name || "—"}</td>
                  <td className="py-2 pr-4 text-faint text-[12px]">
                    {a.fired_at ? relativeTime(a.fired_at) : "—"}
                  </td>
                  <td className="py-2 text-faint text-[12px]">
                    {a.resolved_at ? relativeTime(a.resolved_at) : "미해소"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {history.length === 0 && (
            <p className="text-sm text-muted mt-2">히스토리가 없습니다.</p>
          )}
        </div>
      </div>

      {/* Webhooks */}
      <div>
        <h2 className="text-sm font-semibold text-ink mb-3">Webhook 목록</h2>
        <div className="space-y-2">
          {webhooks.map((wh) => (
            <div key={wh.id} className={`${CARD} p-3 flex items-center gap-3`}>
              <span
                className="w-2 h-2 rounded-full"
                style={{ background: wh.enabled ? "#22c55e" : "var(--danger)" }}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-ink truncate font-mono">{wh.url}</p>
                <p className="text-[11px] text-faint">
                  이벤트: {wh.events.join(", ")}
                </p>
              </div>
              <span className="text-[11px] text-muted">
                {wh.enabled ? "활성" : "비활성"}
              </span>
            </div>
          ))}
          {webhooks.length === 0 && (
            <p className="text-sm text-muted">등록된 웹훅이 없습니다.</p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Incidents Panel ───────────────────────────────────── */

function IncidentsPanel({
  incidents,
  expandedId,
  onToggle,
}: {
  incidents: Incident[];
  expandedId: string | null;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-ink mb-3">
        인시던트 ({incidents.length})
      </h2>
      {incidents.map((inc) => (
        <div key={inc.id} className={`${CARD} overflow-hidden`}>
          <button
            onClick={() => onToggle(inc.id)}
            className="w-full p-4 flex items-center gap-3 text-left hover:bg-paper transition-colors"
          >
            <Icon
              name={expandedId === inc.id ? "chevronDown" : "chevronRight"}
              size={14}
              className="text-muted shrink-0"
            />
            <SeverityBadge severity={inc.severity} />
            <span className="flex-1 text-sm text-ink truncate">{inc.title}</span>
            <StatusBadge status={inc.status} />
            <span className="text-[11px] text-faint shrink-0">
              {inc.created_at ? relativeTime(inc.created_at) : ""}
            </span>
          </button>
          {expandedId === inc.id && inc.timeline && (
            <div className="px-4 pb-4 border-t border-subtle">
              <div className="mt-3 ml-6 space-y-2">
                {inc.timeline.map((entry, i) => (
                  <div key={i} className="flex gap-3 items-start">
                    <div className="w-1.5 h-1.5 mt-1.5 rounded-full bg-accent shrink-0" />
                    <div>
                      <p className="text-[12px] text-faint">
                        {new Date(entry.ts * 1000).toLocaleString("ko-KR")}
                      </p>
                      <p className="text-sm text-ink">{entry.text}</p>
                    </div>
                  </div>
                ))}
                {inc.timeline.length === 0 && (
                  <p className="text-sm text-muted">타임라인이 비어 있습니다.</p>
                )}
              </div>
            </div>
          )}
        </div>
      ))}
      {incidents.length === 0 && (
        <p className="text-sm text-muted">인시던트가 없습니다.</p>
      )}
    </div>
  );
}

/* ── HealthChecks Panel ────────────────────────────────── */

function HealthChecksPanel({
  checks,
  running,
  onRunAll,
}: {
  checks: HealthCheck[];
  running: boolean;
  onRunAll: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">
          헬스체크 ({checks.length})
        </h2>
        <button
          onClick={onRunAll}
          disabled={running}
          className="px-3 py-1.5 rounded-lg text-sm font-medium text-white bg-accent hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {running ? "실행 중..." : "지금 실행"}
        </button>
      </div>

      <div className="space-y-2">
        {checks.map((hc, i) => {
          const ok = hc.last_status === "ok" || hc.last_status === "pass";
          return (
            <div key={i} className={`${CARD} p-4 flex items-center gap-4`}>
              <span className="text-lg shrink-0">{ok ? "\u2705" : "\u274C"}</span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-ink">{hc.name}</p>
                <p className="text-[11px] text-faint truncate">
                  {hc.type} · {hc.target}
                </p>
              </div>
              <div className="text-right shrink-0">
                <p className="text-sm text-ink">
                  {hc.last_latency_ms != null
                    ? `${hc.last_latency_ms.toFixed(0)}ms`
                    : "—"}
                </p>
                <p className="text-[11px] text-faint">
                  {hc.last_check ? relativeTime(hc.last_check) : "—"}
                </p>
              </div>
              {hc.consecutive_failures > 0 && (
                <span className="text-[11px] text-white px-2 py-0.5 rounded" style={{ background: "var(--danger)" }}>
                  연속 {hc.consecutive_failures}회 실패
                </span>
              )}
            </div>
          );
        })}
        {checks.length === 0 && (
          <p className="text-sm text-muted">등록된 헬스체크가 없습니다.</p>
        )}
      </div>
    </div>
  );
}

/* ── Audit Panel ───────────────────────────────────────── */

function AuditPanel({ entries }: { entries: AuditEntry[] }) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-ink mb-3">
        감사 로그 ({entries.length})
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[12px] border-b border-subtle">
              <th className="pb-2 pr-4">시간</th>
              <th className="pb-2 pr-4">사용자</th>
              <th className="pb-2 pr-4">액션</th>
              <th className="pb-2 pr-4">대상</th>
              <th className="pb-2">결과</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={i} className="border-b border-subtle">
                <td className="py-2 pr-4 text-faint text-[12px] whitespace-nowrap">
                  {e.ts
                    ? new Date(e.ts * 1000).toLocaleString("ko-KR")
                    : "—"}
                </td>
                <td className="py-2 pr-4 text-ink">{e.user || "—"}</td>
                <td className="py-2 pr-4 text-ink font-mono text-[12px]">
                  {e.action}
                </td>
                <td className="py-2 pr-4 text-muted truncate max-w-[200px]">
                  {e.target || "—"}
                </td>
                <td className="py-2">
                  <span
                    className="inline-block px-2 py-0.5 rounded text-[11px] font-medium text-white"
                    style={{
                      background:
                        e.result === "success" || e.result === "ok"
                          ? "#22c55e"
                          : "var(--danger)",
                    }}
                  >
                    {e.result}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {entries.length === 0 && (
          <p className="text-sm text-muted mt-2">감사 로그가 없습니다.</p>
        )}
      </div>
    </div>
  );
}
