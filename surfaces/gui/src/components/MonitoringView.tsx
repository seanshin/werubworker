import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { connectMetrics, fetchAnomalies, analyzeAnomalies, generatePostmortem, fetchEscalationPolicies } from "../api";
import { MiniChart } from "./MiniChart";
import { ProgressBar } from "./ProgressBar";
import { Icon } from "./Icon";

// Incidents load a page at a time; 50 matches the store's own default page size.
const INCIDENT_PAGE = 50;

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
  load_1m?: number;
  net_rx?: number;
  net_tx?: number;
}

interface AnomalyInfo {
  metric: string;
  value: number;
  expected: number;
  z_score: number;
  severity: string;
  description: string;
  timestamp: number;
}

interface EscalationPolicy {
  id: string;
  name: string;
  levels: { delay_minutes: number; channels: string[]; assignee: string }[];
  repeat_last: boolean;
  enabled: boolean;
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

function relativeTime(epoch: number, t: TFunction): string {
  if (!epoch) return "—";
  const diff = Math.floor(Date.now() / 1000 - epoch);
  if (diff < 60) return t("common:monitoring.relative.seconds", { n: diff });
  if (diff < 3600) return t("common:monitoring.relative.minutes", { n: Math.floor(diff / 60) });
  if (diff < 86400) return t("common:monitoring.relative.hours", { n: Math.floor(diff / 3600) });
  return t("common:monitoring.relative.days", { n: Math.floor(diff / 86400) });
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

type TabId = "dashboard" | "overview" | "alerts" | "incidents" | "healthchecks" | "audit";

export function MonitoringView() {
  const { t, i18n } = useTranslation(["common"]);
  const [activeTab, setActiveTab] = useState<TabId>("dashboard");
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
  const [incidentTotal, setIncidentTotal] = useState(0);
  const [incidentsLoading, setIncidentsLoading] = useState(false);
  const [expandedIncident, setExpandedIncident] = useState<string | null>(null);

  // Health checks
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);
  const [runningHC, setRunningHC] = useState(false);

  // Audit
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [auditStats, setAuditStats] = useState<{ daily: { date: string; total: number; risky: number }[] } | null>(null);
  const [auditUsers, setAuditUsers] = useState<{ user: string; total: number; risky: number }[]>([]);
  const [flaggedActions, setFlaggedActions] = useState<AuditEntry[]>([]);

  // Real-time metrics
  const metricsCleanup = useRef<(() => void) | null>(null);

  // Anomalies
  const [anomalies, setAnomalies] = useState<Record<string, AnomalyInfo[]>>({});
  const [anomalyAnalysis, setAnomalyAnalysis] = useState<string>("");
  const [analyzingAnomalies, setAnalyzingAnomalies] = useState(false);

  // Escalation policies
  const [escalationPolicies, setEscalationPolicies] = useState<EscalationPolicy[]>([]);

  // Postmortem
  const [postmortemLoading, setPostmortemLoading] = useState<string | null>(null);
  const [postmortemResult, setPostmortemResult] = useState<Record<string, string>>({});

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

  // The list is served a page at a time. It has always been capped at 50 server-side, but
  // without an offset there was no way to reach incident 51 — the tail was unreachable, not
  // merely unshown. `total` is what lets the panel say so.
  const fetchIncidents = useCallback((offset = 0) => {
    fetch(`/v1/dashboard/incidents?limit=${INCIDENT_PAGE}&offset=${offset}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d?.ok) return;
        const page = d.incidents || [];
        setIncidents((prev) => (offset === 0 ? page : [...prev, ...page]));
        setIncidentTotal(typeof d.total === "number" ? d.total : page.length);
      })
      .catch(() => {});
  }, []);

  const loadMoreIncidents = useCallback(() => {
    setIncidentsLoading(true);
    fetch(`/v1/dashboard/incidents?limit=${INCIDENT_PAGE}&offset=${incidents.length}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d?.ok) return;
        // Append by id so a refresh landing mid-page cannot duplicate rows.
        setIncidents((prev) => {
          const seen = new Set(prev.map((i) => i.id));
          return [...prev, ...(d.incidents || []).filter((i: Incident) => !seen.has(i.id))];
        });
        setIncidentTotal(typeof d.total === "number" ? d.total : 0);
      })
      .catch(() => {})
      .finally(() => setIncidentsLoading(false));
  }, [incidents.length]);

  const fetchAudit = useCallback(() => {
    fetch("/v1/dashboard/audit")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) setAuditEntries(d.entries || []);
      })
      .catch(() => {});
  }, []);

  const fetchAuditStats = useCallback(() => {
    fetch("/v1/dashboard/audit/stats?days=7")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.ok) setAuditStats(d); })
      .catch(() => {});
  }, []);

  const fetchAuditUsers = useCallback(() => {
    fetch("/v1/dashboard/audit/users?days=7")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.ok) setAuditUsers(d.users || []); })
      .catch(() => {});
  }, []);

  const fetchFlagged = useCallback(() => {
    fetch("/v1/dashboard/audit/flagged?limit=20")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.ok) setFlaggedActions(d.flagged || []); })
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
    if (activeTab === "audit") { fetchAudit(); fetchAuditStats(); fetchAuditUsers(); fetchFlagged(); }
    setLastRefresh(new Date());
  }, [activeTab, fetchOverview, fetchAlerts, fetchWebhooks, fetchIncidents, fetchAudit, fetchAuditStats, fetchAuditUsers, fetchFlagged]);

  // Initial + tab change
  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Polling
  useEffect(() => {
    const id = setInterval(fetchAll, POLL_MS);
    return () => clearInterval(id);
  }, [fetchAll]);

  // Real-time metrics via WebSocket
  useEffect(() => {
    metricsCleanup.current = connectMetrics((points) => {
      setServerMetrics((prev) => {
        const next = { ...prev };
        for (const p of points) {
          const sid = p.server_id;
          const entry: MetricPoint = {
            ts: Date.now() / 1000,
            cpu: p.cpu,
            memory: p.memory,
            disk: p.disk,
            load_1m: p.load_1m,
            net_rx: p.net_rx,
            net_tx: p.net_tx,
          };
          const existing = next[sid] || [];
          // Keep last 120 points
          next[sid] = [...existing.slice(-119), entry];
        }
        return next;
      });
    });
    return () => {
      metricsCleanup.current?.();
    };
  }, []);

  // Fetch anomalies periodically
  useEffect(() => {
    const loadAnomalies = () => {
      fetchAnomalies().then((d) => {
        if (d?.ok && d.servers) {
          const map: Record<string, AnomalyInfo[]> = {};
          for (const s of d.servers) {
            map[s.server_id] = s.anomalies;
          }
          setAnomalies(map);
        }
      }).catch(() => {});
    };
    loadAnomalies();
    const id = setInterval(loadAnomalies, 60_000);
    return () => clearInterval(id);
  }, []);

  // Fetch escalation policies
  useEffect(() => {
    if (activeTab === "alerts") {
      fetchEscalationPolicies().then((d) => {
        if (d?.ok) setEscalationPolicies(d.policies || []);
      }).catch(() => {});
    }
  }, [activeTab]);

  const handleAnalyzeAnomalies = async () => {
    setAnalyzingAnomalies(true);
    try {
      const d = await analyzeAnomalies();
      if (d?.ok) setAnomalyAnalysis(d.analysis || "");
    } catch { /* ignore */ }
    setAnalyzingAnomalies(false);
  };

  const handlePostmortem = async (incidentId: string, useLlm = false) => {
    setPostmortemLoading(incidentId);
    try {
      const d = await generatePostmortem(incidentId, useLlm);
      if (d?.ok && d.markdown) {
        setPostmortemResult((prev) => ({ ...prev, [incidentId]: d.markdown }));
      }
    } catch { /* ignore */ }
    setPostmortemLoading(null);
  };

  // Fetch server metrics when overview loads
  useEffect(() => {
    if (overview?.servers) {
      overview.servers.forEach((s) => {
        if (s.server_id) fetchServerMetrics(s.server_id);
      });
    }
  }, [overview, fetchServerMetrics]);

  const tabs: { id: TabId; label: string }[] = [
    { id: "dashboard", label: t("common:monitoring.tab.dashboard") },
    { id: "overview", label: t("common:monitoring.tab.overview") },
    { id: "alerts", label: t("common:monitoring.tab.alerts") },
    { id: "incidents", label: t("common:monitoring.tab.incidents") },
    { id: "healthchecks", label: t("common:monitoring.tab.healthchecks") },
    { id: "audit", label: t("common:monitoring.tab.audit") },
  ];

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-subtle">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold text-ink">{t("common:monitoring.title")}</h1>
          {lastRefresh && (
            <span className="text-[11px] text-faint">
              {t("common:monitoring.lastUpdated")}: {lastRefresh.toLocaleTimeString(i18n.language)}
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
        {activeTab === "dashboard" && (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
              {overview?.servers?.map((s) => (
                <div key={s.server_id} className={CARD + " p-4"}>
                  <h4 className="text-xs font-medium text-muted mb-3">{s.name || s.server_id}</h4>
                  <div className="flex gap-4 justify-center">
                    <GaugeWidget label={t("common:monitoring.server.cpu")} value={s.cpu_percent ?? 0} color="var(--accent)" />
                    <GaugeWidget label="MEM" value={s.memory_percent ?? 0} color="var(--warn)" />
                    <GaugeWidget label="DISK" value={s.disk_percent ?? 0} color="var(--danger)" />
                  </div>
                  {serverMetrics[s.server_id]?.length > 1 && (
                    <div className="mt-3">
                      <MiniChart data={serverMetrics[s.server_id].map((p) => p.cpu)} height={40} color="var(--accent)" />
                    </div>
                  )}
                </div>
              ))}
            </div>

            {overview?.active_alerts?.length ? (
              <div className={CARD + " p-4 mt-4"}>
                <h3 className="text-sm font-semibold mb-2">{t("common:monitoring.alert.active")} ({overview.active_alerts.length})</h3>
                <div className="space-y-1">
                  {overview.active_alerts.slice(0, 5).map((a, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <SeverityBadge severity={a.severity} />
                      <span className="text-muted">{a.server_name || a.server_id}</span>
                      <span>{a.message}</span>
                      {a.fired_at && <span className="text-muted ml-auto">{relativeTime(a.fired_at, t)}</span>}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )}
        {activeTab === "overview" && (
          <OverviewPanel
            overview={overview}
            serverMetrics={serverMetrics}
            anomalies={anomalies}
            anomalyAnalysis={anomalyAnalysis}
            analyzingAnomalies={analyzingAnomalies}
            onAnalyzeAnomalies={handleAnalyzeAnomalies}
          />
        )}
        {activeTab === "alerts" && (
          <AlertsPanel
            active={activeAlerts}
            history={alertHistory}
            webhooks={webhooks}
            escalationPolicies={escalationPolicies}
          />
        )}
        {activeTab === "incidents" && (
          <IncidentsPanel
            incidents={incidents}
            total={incidentTotal}
            loadingMore={incidentsLoading}
            onLoadMore={loadMoreIncidents}
            expandedId={expandedIncident}
            onToggle={(id) =>
              setExpandedIncident(expandedIncident === id ? null : id)
            }
            postmortemLoading={postmortemLoading}
            postmortemResult={postmortemResult}
            onPostmortem={handlePostmortem}
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
        {activeTab === "audit" && (
          <AuditPanel
            entries={auditEntries}
            auditStats={auditStats}
            auditUsers={auditUsers}
            flaggedActions={flaggedActions}
          />
        )}
      </div>
    </div>
  );
}

/* ── Gauge Widget ─────────────────────────────────────── */

function GaugeWidget({ label, value, color }: { label: string; value: number; color: string }) {
  const r = 30;
  const circumference = 2 * Math.PI * r;
  const progress = Math.min(100, Math.max(0, value));
  const offset = circumference - (progress / 100) * circumference;
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="72" height="72" viewBox="0 0 72 72">
        <circle cx="36" cy="36" r={r} fill="none" stroke="var(--line)" strokeWidth="6" />
        <circle
          cx="36" cy="36" r={r} fill="none" stroke={color} strokeWidth="6"
          strokeDasharray={circumference} strokeDashoffset={offset}
          strokeLinecap="round" transform="rotate(-90 36 36)"
          style={{ transition: "stroke-dashoffset 0.5s ease" }}
        />
        <text x="36" y="38" textAnchor="middle" dominantBaseline="middle"
          fill="var(--ink)" fontSize="14" fontWeight="600">
          {Math.round(value)}%
        </text>
      </svg>
      <span className="text-[10px] text-muted">{label}</span>
    </div>
  );
}

/* ── Overview Panel ────────────────────────────────────── */

function OverviewPanel({
  overview,
  serverMetrics,
  anomalies,
  anomalyAnalysis,
  analyzingAnomalies,
  onAnalyzeAnomalies,
}: {
  overview: OverviewData | null;
  serverMetrics: Record<string, MetricPoint[]>;
  anomalies: Record<string, AnomalyInfo[]>;
  anomalyAnalysis: string;
  analyzingAnomalies: boolean;
  onAnalyzeAnomalies: () => void;
}) {
  const { t } = useTranslation(["common"]);
  if (!overview) {
    return <p className="text-muted text-sm">{t("common:monitoring.loading")}</p>;
  }

  const cards = [
    { label: t("common:monitoring.card.servers"), value: overview.server_count, icon: "gear" as const },
    { label: t("common:monitoring.card.activeAlerts"), value: overview.alert_count, icon: "shield" as const },
    { label: t("common:monitoring.card.healthChecks"), value: overview.health_checks?.length ?? 0, icon: "refresh" as const },
    { label: t("common:monitoring.card.incidents"), value: overview.incident_count, icon: "info" as const },
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
        <h2 className="text-sm font-semibold text-ink mb-3">{t("common:monitoring.serverStatus")}</h2>
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
                  <div className="flex items-center gap-2">
                    {anomalies[srv.server_id]?.length ? (
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 font-medium">
                        {t("common:monitoring.anomaly.count", { n: anomalies[srv.server_id].length })}
                      </span>
                    ) : null}
                    <span className="text-[11px] text-faint">{srv.host}</span>
                  </div>
                </div>
                <div className="space-y-2">
                  <ProgressBar
                    label={t("common:monitoring.server.cpu")}
                    value={srv.cpu_percent ?? 0}
                  />
                  <ProgressBar
                    label={t("common:monitoring.server.memory")}
                    value={srv.memory_percent ?? 0}
                  />
                  <ProgressBar
                    label={t("common:monitoring.server.disk")}
                    value={srv.disk_percent ?? 0}
                  />
                </div>
                {cpuData.length > 0 && (
                  <div className="flex gap-4 mt-3">
                    <MiniChart data={cpuData} color="var(--accent)" label={t("common:monitoring.server.cpu")} height={32} width={140} />
                    <MiniChart data={memData} color="var(--warn)" label="MEM" height={32} width={140} />
                  </div>
                )}
              </div>
            );
          })}
          {overview.servers.length === 0 && (
            <p className="text-sm text-muted">{t("common:monitoring.noServers")}</p>
          )}
        </div>
      </div>

      {/* Recent alerts + incidents */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Recent alerts */}
        <div>
          <h2 className="text-sm font-semibold text-ink mb-3">{t("common:monitoring.recentAlerts")}</h2>
          <div className="space-y-2">
            {overview.active_alerts.slice(0, 3).map((a, i) => (
              <div key={i} className={`${CARD} p-3 flex items-start gap-2`}>
                <SeverityBadge severity={a.severity} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-ink truncate">{a.message}</p>
                  <p className="text-[11px] text-faint">
                    {a.server_name && `${a.server_name} · `}
                    {a.fired_at ? relativeTime(a.fired_at, t) : ""}
                  </p>
                </div>
              </div>
            ))}
            {overview.active_alerts.length === 0 && (
              <p className="text-sm text-muted">{t("common:monitoring.alert.noActive")}</p>
            )}
          </div>
        </div>

        {/* Recent incidents */}
        <div>
          <h2 className="text-sm font-semibold text-ink mb-3">{t("common:monitoring.recentIncidents")}</h2>
          <div className="space-y-2">
            {overview.active_incidents.slice(0, 3).map((inc) => (
              <div key={inc.id} className={`${CARD} p-3 flex items-start gap-2`}>
                <SeverityBadge severity={inc.severity} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-ink truncate">{inc.title}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <StatusBadge status={inc.status} />
                    <span className="text-[11px] text-faint">
                      {inc.created_at ? relativeTime(inc.created_at, t) : ""}
                    </span>
                  </div>
                </div>
              </div>
            ))}
            {overview.active_incidents.length === 0 && (
              <p className="text-sm text-muted">{t("common:monitoring.noActiveIncidents")}</p>
            )}
          </div>
        </div>
      </div>

      {/* Anomaly Detection */}
      {Object.keys(anomalies).length > 0 && (
        <div className={CARD + " p-4 mt-4"}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-sm">{t("common:monitoring.anomaly.title")}</h3>
            <button
              onClick={onAnalyzeAnomalies}
              disabled={analyzingAnomalies}
              className="text-xs px-2 py-1 rounded bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50"
            >
              {analyzingAnomalies ? t("common:monitoring.anomaly.analyzing") : t("common:monitoring.anomaly.analyze")}
            </button>
          </div>
          <div className="space-y-2">
            {Object.entries(anomalies).map(([sid, items]) =>
              items.map((a, i) => (
                <div key={`${sid}-${i}`} className="flex items-center gap-2 text-xs">
                  <SeverityBadge severity={a.severity} />
                  <span className="text-muted">[{sid}]</span>
                  <span>{a.description}</span>
                </div>
              ))
            )}
          </div>
          {anomalyAnalysis && (
            <div className="mt-3 p-3 rounded-lg bg-paper text-xs whitespace-pre-wrap">
              {anomalyAnalysis}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Alerts Panel ──────────────────────────────────────── */

function AlertsPanel({
  active,
  history,
  webhooks,
  escalationPolicies,
}: {
  active: Alert[];
  history: Alert[];
  webhooks: Webhook[];
  escalationPolicies: EscalationPolicy[];
}) {
  const { t } = useTranslation(["common"]);
  return (
    <div className="space-y-6">
      {/* Active alerts */}
      <div>
        <h2 className="text-sm font-semibold text-ink mb-3">
          {t("common:monitoring.alert.active")} ({active.length})
        </h2>
        <div className="space-y-2">
          {active.map((a, i) => (
            <div key={i} className={`${CARD} p-3 flex items-start gap-3`}>
              <SeverityBadge severity={a.severity} />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-ink">{a.message}</p>
                <p className="text-[11px] text-faint">
                  {a.metric && t("common:monitoring.alert.threshold", { metric: a.metric, value: a.value, threshold: a.threshold })}
                  {a.server_name && ` · ${a.server_name}`}
                  {a.fired_at ? ` · ${relativeTime(a.fired_at, t)}` : ""}
                </p>
              </div>
            </div>
          ))}
          {active.length === 0 && (
            <p className="text-sm text-muted">{t("common:monitoring.alert.noActive")}</p>
          )}
        </div>
      </div>

      {/* Alert history */}
      <div>
        <h2 className="text-sm font-semibold text-ink mb-3">{t("common:monitoring.alert.history")}</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted text-[12px] border-b border-subtle">
                <th className="pb-2 pr-4">{t("common:monitoring.alert.severity")}</th>
                <th className="pb-2 pr-4">{t("common:monitoring.alert.message")}</th>
                <th className="pb-2 pr-4">{t("common:monitoring.alert.server")}</th>
                <th className="pb-2 pr-4">{t("common:monitoring.alert.firedAt")}</th>
                <th className="pb-2">{t("common:monitoring.alert.resolvedAt")}</th>
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
                    {a.fired_at ? relativeTime(a.fired_at, t) : "—"}
                  </td>
                  <td className="py-2 text-faint text-[12px]">
                    {a.resolved_at ? relativeTime(a.resolved_at, t) : t("common:monitoring.alert.unresolved")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {history.length === 0 && (
            <p className="text-sm text-muted mt-2">{t("common:monitoring.alert.noHistory")}</p>
          )}
        </div>
      </div>

      {/* Webhooks */}
      <div>
        <h2 className="text-sm font-semibold text-ink mb-3">{t("common:monitoring.webhook.title")}</h2>
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
                  {t("common:monitoring.webhook.events")}: {wh.events.join(", ")}
                </p>
              </div>
              <span className="text-[11px] text-muted">
                {wh.enabled ? t("common:monitoring.enabled") : t("common:monitoring.disabled")}
              </span>
            </div>
          ))}
          {webhooks.length === 0 && (
            <p className="text-sm text-muted">{t("common:monitoring.webhook.none")}</p>
          )}
        </div>
      </div>

      {/* Escalation Policies */}
      {escalationPolicies.length > 0 && (
        <div className={CARD + " p-4 mt-4"}>
          <h3 className="font-semibold text-sm mb-3">{t("common:monitoring.escalation.title")}</h3>
          <div className="space-y-2">
            {escalationPolicies.map((p) => (
              <div key={p.id} className="p-2 rounded-lg bg-paper text-xs">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium">{p.name}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] ${p.enabled ? "bg-green-500/15 text-green-400" : "bg-gray-500/15 text-gray-400"}`}>
                    {p.enabled ? t("common:monitoring.enabled") : t("common:monitoring.disabled")}
                  </span>
                </div>
                <div className="text-muted">
                  {p.levels.map((l, i) => (
                    <span key={i}>
                      {t("common:monitoring.escalation.level", { level: i + 1, minutes: l.delay_minutes, channels: l.channels.join(", ") || t("common:monitoring.escalation.noChannels") })}
                      {l.assignee && ` (${l.assignee})`}
                      {i < p.levels.length - 1 && " → "}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Incidents Panel ───────────────────────────────────── */

function IncidentsPanel({
  incidents,
  total,
  loadingMore,
  onLoadMore,
  expandedId,
  onToggle,
  postmortemLoading,
  postmortemResult,
  onPostmortem,
}: {
  incidents: Incident[];
  total: number;
  loadingMore: boolean;
  onLoadMore: () => void;
  expandedId: string | null;
  onToggle: (id: string) => void;
  postmortemLoading: string | null;
  postmortemResult: Record<string, string>;
  onPostmortem: (id: string, useLlm?: boolean) => void;
}) {
  const { t } = useTranslation(["common"]);
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-ink mb-3">
        {t("common:monitoring.incident.title")} ({incidents.length}
        {total > incidents.length ? ` / ${total}` : ""})
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
              {inc.created_at ? relativeTime(inc.created_at, t) : ""}
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
                  <p className="text-sm text-muted">{t("common:monitoring.incident.emptyTimeline")}</p>
                )}
              </div>
              {/* Postmortem */}
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => onPostmortem(inc.id)}
                  disabled={postmortemLoading === inc.id}
                  className="text-xs px-2 py-1 rounded bg-paper hover:bg-accent/10"
                >
                  {postmortemLoading === inc.id ? t("common:monitoring.incident.generating") : t("common:monitoring.incident.generatePostmortem")}
                </button>
                <button
                  onClick={() => onPostmortem(inc.id, true)}
                  disabled={postmortemLoading === inc.id}
                  className="text-xs px-2 py-1 rounded bg-accent/10 text-accent hover:bg-accent/20"
                >
                  {t("common:monitoring.incident.aiPostmortem")}
                </button>
              </div>
              {postmortemResult[inc.id] && (
                <div className="mt-3 p-3 rounded-lg bg-paper text-xs whitespace-pre-wrap max-h-80 overflow-auto">
                  {postmortemResult[inc.id]}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
      {incidents.length === 0 && (
        <p className="text-sm text-muted">{t("common:monitoring.incident.none")}</p>
      )}
      {total > incidents.length && (
        <button
          onClick={onLoadMore}
          disabled={loadingMore}
          className="w-full py-2 rounded-lg border border-line text-sm text-muted hover:text-ink hover:bg-paper disabled:opacity-50 transition-colors"
        >
          {loadingMore ? t("common:monitoring.incident.loadingMore") : t("common:monitoring.incident.loadMore", { count: total - incidents.length })}
        </button>
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
  const { t } = useTranslation(["common"]);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">
          {t("common:monitoring.healthcheck.title")} ({checks.length})
        </h2>
        <button
          onClick={onRunAll}
          disabled={running}
          className="px-3 py-1.5 rounded-lg text-sm font-medium text-white bg-accent hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {running ? t("common:monitoring.healthcheck.running") : t("common:monitoring.healthcheck.runNow")}
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
                  {hc.last_check ? relativeTime(hc.last_check, t) : "—"}
                </p>
              </div>
              {hc.consecutive_failures > 0 && (
                <span className="text-[11px] text-white px-2 py-0.5 rounded" style={{ background: "var(--danger)" }}>
                  {t("common:monitoring.healthcheck.consecutiveFailures", { n: hc.consecutive_failures })}
                </span>
              )}
            </div>
          );
        })}
        {checks.length === 0 && (
          <p className="text-sm text-muted">{t("common:monitoring.healthcheck.none")}</p>
        )}
      </div>
    </div>
  );
}

/* ── Audit Panel ───────────────────────────────────────── */

function AuditPanel({
  entries,
  auditStats,
  auditUsers,
  flaggedActions,
}: {
  entries: AuditEntry[];
  auditStats: { daily: { date: string; total: number; risky: number }[] } | null;
  auditUsers: { user: string; total: number; risky: number }[];
  flaggedActions: AuditEntry[];
}) {
  const { t } = useTranslation(["common"]);
  return (
    <div>
      {/* Audit Stats */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        {/* Daily chart */}
        <div className={CARD + " p-4"}>
          <h3 className="text-sm font-semibold mb-2">{t("common:monitoring.audit.dailyActivity")}</h3>
          <div className="flex items-end gap-1 h-24">
            {auditStats?.daily?.map((d, i) => {
              const maxVal = Math.max(...(auditStats.daily.map((x) => x.total)), 1);
              return (
                <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
                  <div className="w-full flex flex-col justify-end" style={{ height: "80px" }}>
                    {d.risky > 0 && (
                      <div className="w-full rounded-t" style={{ height: `${(d.risky / maxVal) * 80}px`, background: "var(--danger)", opacity: 0.7 }} />
                    )}
                    <div className="w-full rounded-t" style={{ height: `${((d.total - d.risky) / maxVal) * 80}px`, background: "var(--accent)", opacity: 0.5 }} />
                  </div>
                  <span className="text-[9px] text-muted">{d.date.slice(5)}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* User stats */}
        <div className={CARD + " p-4"}>
          <h3 className="text-sm font-semibold mb-2">{t("common:monitoring.audit.userActivity")}</h3>
          <div className="space-y-1 max-h-24 overflow-auto">
            {auditUsers.map((u, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="w-20 truncate font-medium">{u.user || "system"}</span>
                <div className="flex-1 h-1.5 rounded-full bg-line overflow-hidden">
                  <div className="h-full rounded-full bg-accent/50" style={{ width: `${Math.min(100, (u.total / Math.max(...auditUsers.map((x) => x.total), 1)) * 100)}%` }} />
                </div>
                <span className="text-muted w-8 text-right">{u.total}</span>
                {u.risky > 0 && <span className="text-red-400 text-[10px]">{u.risky}</span>}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Flagged Actions */}
      {flaggedActions.length > 0 && (
        <div className={CARD + " p-4 mb-4"}>
          <h3 className="text-sm font-semibold mb-2 text-red-400">{t("common:monitoring.audit.flagged", { count: flaggedActions.length })}</h3>
          <div className="space-y-1 max-h-40 overflow-auto">
            {flaggedActions.map((e, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="text-muted">{relativeTime(e.ts, t)}</span>
                <span className="font-medium">{e.user || "system"}</span>
                <span className="text-red-400">{e.action}</span>
                <span className="text-muted truncate">{e.target}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* CSV Export */}
      <div className="flex justify-end mb-2">
        <a href="/v1/dashboard/audit/export?days=30" download className="text-xs px-2 py-1 rounded bg-paper hover:bg-accent/10">
          {t("common:monitoring.audit.exportCsv")}
        </a>
      </div>

      <h2 className="text-sm font-semibold text-ink mb-3">
        {t("common:monitoring.audit.title")} ({entries.length})
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[12px] border-b border-subtle">
              <th className="pb-2 pr-4">{t("common:monitoring.audit.time")}</th>
              <th className="pb-2 pr-4">{t("common:monitoring.audit.user")}</th>
              <th className="pb-2 pr-4">{t("common:monitoring.audit.action")}</th>
              <th className="pb-2 pr-4">{t("common:monitoring.audit.target")}</th>
              <th className="pb-2">{t("common:monitoring.audit.result")}</th>
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
          <p className="text-sm text-muted mt-2">{t("common:monitoring.audit.none")}</p>
        )}
      </div>
    </div>
  );
}
