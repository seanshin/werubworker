import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelHead } from "./IntegrationsView";
import { Icon, type IconName } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";
const BTN_ACCENT =
  "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";

interface DevConfig {
  configured: boolean;
  owner?: string;
  repo?: string;
}

interface RepoInfo {
  name: string;
  default_branch: string;
  description: string;
  open_issues_count: number;
}

interface PullRequest {
  number: number;
  title: string;
  author: string;
  state: string;
  updated_at: string;
  draft: boolean;
}

interface ActionRun {
  id: number;
  name: string;
  status: string;
  conclusion: string;
  created_at: string;
  head_branch: string;
}

interface Issue {
  number: number;
  title: string;
  state: string;
  author: string;
  labels: string[];
  updated_at: string;
}

interface PRDetail {
  number: number;
  title: string;
  body: string;
  state: string;
  author: string;
  draft: boolean;
  mergeable: boolean | null;
  additions: number;
  deletions: number;
  changed_files: number;
  reviews: { user: string; state: string; body: string }[];
  checks: { name: string; status: string; conclusion: string }[];
  created_at: string;
  updated_at: string;
}

interface RunJob {
  name: string;
  status: string;
  conclusion: string;
  steps: { name: string; status: string; conclusion: string }[];
}

interface Release {
  id: number;
  tag_name: string;
  name: string;
  body: string;
  draft: boolean;
  prerelease: boolean;
  published_at: string;
  author: string;
}

interface Commit {
  sha: string;
  message: string;
  author: string;
  date: string;
}

// ---------------------------------------------------------------------------
// GitHub Setup Modal
// ---------------------------------------------------------------------------
function SetupModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [provider, setProvider] = useState<"github" | "gitea">("github");
  const [baseUrl, setBaseUrl] = useState("https://itms.weve.io.kr");
  const [token, setToken] = useState("");
  const [owner, setOwner] = useState("");
  const [repo, setRepo] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    if (!token.trim()) { setError("Token is required"); return; }
    if (!owner.trim() || !repo.trim()) { setError("Owner and repo are required"); return; }
    if (provider === "gitea" && !baseUrl.trim()) { setError("Server URL is required"); return; }
    setSaving(true);
    try {
      const body: Record<string, string> = { provider, token, owner, repo };
      if (provider === "gitea") body.base_url = baseUrl;
      const r = await fetch("/v1/dev/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (d.ok) { onSaved(); onClose(); }
      else setError(d.error || "Save failed");
    } catch { setError("Network error"); }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-panel rounded-xl2 border border-line p-6 w-[460px]" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[15px] font-semibold text-ink mb-4">SCM Configuration</h3>
        <div className="space-y-3">
          {/* Provider selector */}
          <div>
            <label className="block text-[12px] text-muted mb-1">Provider</label>
            <div className="flex gap-2">
              {(["github", "gitea"] as const).map((p) => (
                <button
                  key={p}
                  className={"flex-1 text-[13px] px-3 py-2 rounded-lg border font-medium " +
                    (provider === p ? "border-accent bg-accent/10 text-accent" : "border-line text-muted hover:text-ink")}
                  onClick={() => setProvider(p)}
                >
                  {p === "github" ? "GitHub" : "Gitea / Forgejo"}
                </button>
              ))}
            </div>
          </div>
          {/* Gitea server URL */}
          {provider === "gitea" && (
            <div>
              <label className="block text-[12px] text-muted mb-1">Server URL</label>
              <input className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
                value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://itms.weve.io.kr" />
            </div>
          )}
          <div>
            <label className="block text-[12px] text-muted mb-1">
              {provider === "github" ? "Personal Access Token" : "Access Token"}
            </label>
            <input type="password" className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
              value={token} onChange={(e) => setToken(e.target.value)}
              placeholder={provider === "github" ? "ghp_..." : "your-gitea-token"} />
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-[12px] text-muted mb-1">Owner</label>
              <input className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
                value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="seanshin" />
            </div>
            <div className="flex-1">
              <label className="block text-[12px] text-muted mb-1">Repository</label>
              <input className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
                value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="werubworker" />
            </div>
          </div>
          <p className="text-[11px] text-faint">Required scopes: repo:status, public_repo, read:org</p>
        </div>
        {error && <p className="text-[12px] text-err mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted" onClick={onClose}>Cancel</button>
          <button className={BTN_ACCENT} onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// New Issue Modal
// ---------------------------------------------------------------------------
function NewIssueModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useTranslation(["session"]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [labels, setLabels] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleCreate = async () => {
    if (!title.trim()) { setError("Title is required"); return; }
    setSaving(true);
    try {
      const labelList = labels.split(",").map((l) => l.trim()).filter(Boolean);
      const r = await fetch("/v1/dev/issues", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, body, labels: labelList }),
      });
      const d = await r.json();
      if (d.ok) { onCreated(); onClose(); }
      else setError(d.error || "Create failed");
    } catch { setError("Network error"); }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-panel rounded-xl2 border border-line p-6 w-[480px]" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[15px] font-semibold text-ink mb-4">{t("session:dev.newIssue")}</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-[12px] text-muted mb-1">{t("session:dev.issueTitle")}</label>
            <input className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
              value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Bug: ..." />
          </div>
          <div>
            <label className="block text-[12px] text-muted mb-1">{t("session:dev.issueBody")}</label>
            <textarea className="w-full text-[13px] px-3 py-2 rounded-lg border border-line bg-paper text-ink min-h-[100px] resize-y"
              value={body} onChange={(e) => setBody(e.target.value)} placeholder="Describe the issue..." />
          </div>
          <div>
            <label className="block text-[12px] text-muted mb-1">{t("session:dev.issueLabels")}</label>
            <input className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
              value={labels} onChange={(e) => setLabels(e.target.value)} placeholder="bug, enhancement" />
          </div>
        </div>
        {error && <p className="text-[12px] text-err mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted" onClick={onClose}>Cancel</button>
          <button className={BTN_ACCENT} onClick={handleCreate} disabled={saving}>
            {saving ? "Creating..." : t("session:dev.newIssue")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// New Release Modal
// ---------------------------------------------------------------------------
function NewReleaseModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useTranslation(["session"]);
  const [tag, setTag] = useState("");
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [draft, setDraft] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleCreate = async () => {
    if (!tag.trim()) { setError("Tag is required"); return; }
    if (!name.trim()) { setError("Name is required"); return; }
    setSaving(true);
    try {
      const r = await fetch("/v1/dev/releases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tag, name, body, draft }),
      });
      const d = await r.json();
      if (d.ok) { onCreated(); onClose(); }
      else setError(d.error || "Create failed");
    } catch { setError("Network error"); }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-panel rounded-xl2 border border-line p-6 w-[480px]" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[15px] font-semibold text-ink mb-4">{t("session:dev.newRelease")}</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-[12px] text-muted mb-1">{t("session:dev.tagName")}</label>
            <input className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
              value={tag} onChange={(e) => setTag(e.target.value)} placeholder="v1.0.0" />
          </div>
          <div>
            <label className="block text-[12px] text-muted mb-1">{t("session:dev.releaseName")}</label>
            <input className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
              value={name} onChange={(e) => setName(e.target.value)} placeholder="Release 1.0.0" />
          </div>
          <div>
            <label className="block text-[12px] text-muted mb-1">{t("session:dev.releaseBody")}</label>
            <textarea className="w-full text-[13px] px-3 py-2 rounded-lg border border-line bg-paper text-ink min-h-[100px] resize-y"
              value={body} onChange={(e) => setBody(e.target.value)} placeholder="Release notes..." />
          </div>
          <label className="flex items-center gap-2 text-[13px] text-ink cursor-pointer">
            <input type="checkbox" checked={draft} onChange={(e) => setDraft(e.target.checked)} />
            {t("session:dev.draft")}
          </label>
        </div>
        {error && <p className="text-[12px] text-err mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted" onClick={onClose}>Cancel</button>
          <button className={BTN_ACCENT} onClick={handleCreate} disabled={saving}>
            {saving ? "Creating..." : t("session:dev.newRelease")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
export function DevView() {
  const { t } = useTranslation(["session", "common"]);

  const [config, setConfig] = useState<DevConfig | null>(null);
  const [repo, setRepo] = useState<RepoInfo | null>(null);
  const [prs, setPrs] = useState<PullRequest[]>([]);
  const [runs, setRuns] = useState<ActionRun[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(true);
  const [showSetup, setShowSetup] = useState(false);
  const [showNewIssue, setShowNewIssue] = useState(false);
  const [showNewRelease, setShowNewRelease] = useState(false);
  const [activeTab, setActiveTab] = useState<"prs" | "actions" | "issues" | "releases" | "commits" | "webhooks" | "repos" | "pipelines">("prs");
  const [prFilter, setPrFilter] = useState<"open" | "closed" | "all">("open");
  const [selectedPR, setSelectedPR] = useState<number | null>(null);
  const [prDetail, setPrDetail] = useState<PRDetail | null>(null);
  const [prDetailLoading, setPrDetailLoading] = useState(false);
  const [expandedRun, setExpandedRun] = useState<number | null>(null);
  const [runJobs, setRunJobs] = useState<RunJob[]>([]);
  const [runJobsLoading, setRunJobsLoading] = useState(false);
  const [reviewCount, setReviewCount] = useState(0);
  const [releases, setReleases] = useState<Release[]>([]);
  const [commits, setCommits] = useState<Commit[]>([]);
  const [webhookEvents, setWebhookEvents] = useState<any[]>([]);
  const [giteaRepos, setGiteaRepos] = useState<any[]>([]);
  const [pipelines, setPipelines] = useState<any[]>([]);
  const [pipelineRuns, setPipelineRuns] = useState<any[]>([]);
  const [runningPipeline, setRunningPipeline] = useState<string | null>(null);
  const [merging, setMerging] = useState(false);
  const [mergeMethod, setMergeMethod] = useState<"squash" | "merge" | "rebase">("squash");
  const [showMergeConfirm, setShowMergeConfirm] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewResult, setReviewResult] = useState<string | null>(null);
  const [reviewingPr, setReviewingPr] = useState<number | null>(null);
  const [giteaReviewResult, setGiteaReviewResult] = useState<Record<number, any>>({});

  // Repo stats + security
  const [repoStats, setRepoStats] = useState<any>(null);
  const [contributors, setContributors] = useState<any[]>([]);
  const [secretScan, setSecretScan] = useState<any>(null);
  const [scanningSecrets, setScanningSecrets] = useState(false);

  // Code browser
  const [fileTree, setFileTree] = useState<{path: string; type: string; size: number}[]>([]);
  const [selectedFile, setSelectedFile] = useState<{path: string; content: string; sha: string} | null>(null);
  const [browsingRepo, setBrowsingRepo] = useState("");

  // Wiki sync
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<any>(null);

  const fetchConfig = useCallback(async () => {
    try {
      const r = await fetch("/v1/dev/config");
      const d = await r.json();
      setConfig(d);
      return d.configured;
    } catch { return false; }
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    const configured = await fetchConfig();
    if (!configured) { setLoading(false); return; }
    try {
      const [repoR, prsR, runsR] = await Promise.all([
        fetch("/v1/dev/repo").then((r) => r.json()).catch(() => null),
        fetch(`/v1/dev/pulls?state=${prFilter}`).then((r) => r.json()).catch(() => ({ pulls: [] })),
        fetch("/v1/dev/actions/runs").then((r) => r.json()).catch(() => ({ runs: [] })),
      ]);
      if (repoR?.ok) setRepo(repoR);
      setPrs(prsR?.pulls || []);
      setRuns(runsR?.runs || []);
    } catch { /* ignore */ }
    setLoading(false);
  }, [fetchConfig, prFilter]);

  const fetchIssues = useCallback(async () => {
    try {
      const r = await fetch("/v1/dev/issues");
      const d = await r.json();
      setIssues(d?.issues || []);
    } catch { /* ignore */ }
  }, []);

  const fetchPRDetail = useCallback(async (number: number) => {
    setPrDetailLoading(true);
    try {
      const r = await fetch(`/v1/dev/pulls/${number}`);
      const d = await r.json();
      if (d.ok) setPrDetail(d);
    } catch { /* ignore */ }
    setPrDetailLoading(false);
  }, []);

  const fetchRunJobs = useCallback(async (runId: number) => {
    setRunJobsLoading(true);
    try {
      const r = await fetch(`/v1/dev/actions/runs/${runId}/jobs`);
      const d = await r.json();
      setRunJobs(d?.jobs || []);
    } catch { setRunJobs([]); }
    setRunJobsLoading(false);
  }, []);

  const fetchReleases = useCallback(async () => {
    try {
      const r = await fetch("/v1/dev/releases");
      const d = await r.json();
      setReleases(d?.releases || []);
    } catch { /* ignore */ }
  }, []);

  const fetchCommits = useCallback(async () => {
    try {
      const r = await fetch("/v1/dev/commits");
      const d = await r.json();
      setCommits(d?.commits || []);
    } catch { /* ignore */ }
  }, []);

  const fetchWebhookEvents = useCallback(() => {
    fetch("/v1/webhooks/gitea/events?limit=30")
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.ok) setWebhookEvents(d.events || []); })
      .catch(() => {});
  }, []);

  const fetchGiteaRepos = useCallback(() => {
    fetch("/v1/gitea/repos")
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.ok) setGiteaRepos(d.repos || []); })
      .catch(() => {});
  }, []);

  const fetchPipelines = useCallback(() => {
    fetch("/v1/gitea/pipelines").then(r => r.ok ? r.json() : null).then(d => { if (d?.ok) setPipelines(d.pipelines || []); }).catch(() => {});
    fetch("/v1/gitea/pipelines/runs?limit=15").then(r => r.ok ? r.json() : null).then(d => { if (d?.ok) setPipelineRuns(d.runs || []); }).catch(() => {});
  }, []);

  const fetchFileTree = useCallback((owner: string, repo: string) => {
    setBrowsingRepo(`${owner}/${repo}`);
    fetch(`/v1/gitea/repos/${owner}/${repo}/tree`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.ok) setFileTree(d.tree || []); })
      .catch(() => {});
  }, []);

  const fetchFileContent = useCallback((owner: string, repo: string, filepath: string) => {
    fetch(`/v1/gitea/repos/${owner}/${repo}/contents/${filepath}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => {
        if (d?.content) {
          try {
            setSelectedFile({ path: filepath, content: atob(d.content), sha: d.sha || "" });
          } catch { setSelectedFile({ path: filepath, content: "(바이너리 파일)", sha: "" }); }
        }
      })
      .catch(() => {});
  }, []);

  const handleMerge = useCallback(async (number: number, method: string) => {
    setMerging(true);
    try {
      const r = await fetch(`/v1/dev/pulls/${number}/merge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ method }),
      });
      const d = await r.json();
      if (d.ok) {
        setSelectedPR(null);
        fetchAll();
      }
    } catch { /* ignore */ }
    setMerging(false);
    setShowMergeConfirm(false);
  }, []);

  const handleAIReview = useCallback(async (number: number) => {
    setReviewLoading(true);
    setReviewResult(null);
    try {
      const r = await fetch(`/v1/dev/pulls/${number}/review`, { method: "POST" });
      const d = await r.json();
      if (d.ok) setReviewResult(d.review_prompt || "No review data");
      else setReviewResult(d.error || "Review failed");
    } catch { setReviewResult("Network error"); }
    setReviewLoading(false);
  }, []);

  const handleGiteaReviewPr = useCallback(async (number: number) => {
    if (!config?.owner || !config?.repo) return;
    setReviewingPr(number);
    try {
      const res = await fetch(`/v1/gitea/repos/${config.owner}/${config.repo}/pulls/${number}/review`, { method: "POST" });
      const d = await res.json();
      if (d?.ok) setGiteaReviewResult((prev) => ({ ...prev, [number]: d }));
    } catch { /* ignore */ }
    setReviewingPr(null);
  }, [config]);

  const fetchReviewCount = useCallback(async () => {
    try {
      const r = await fetch("/v1/dev/reviews");
      const d = await r.json();
      setReviewCount(d?.reviews?.length || 0);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => { if (activeTab === "issues") fetchIssues(); }, [activeTab, fetchIssues]);
  useEffect(() => { if (activeTab === "releases") fetchReleases(); }, [activeTab, fetchReleases]);
  useEffect(() => { if (activeTab === "commits") fetchCommits(); }, [activeTab, fetchCommits]);
  useEffect(() => { if (activeTab === "webhooks") fetchWebhookEvents(); }, [activeTab, fetchWebhookEvents]);
  useEffect(() => { if (activeTab === "repos") fetchGiteaRepos(); }, [activeTab, fetchGiteaRepos]);
  useEffect(() => { if (activeTab === "pipelines") fetchPipelines(); }, [activeTab, fetchPipelines]);
  useEffect(() => { if (config?.configured) fetchReviewCount(); }, [config, fetchReviewCount]);

  // Listen for github_event WebSocket events to auto-refresh
  useEffect(() => {
    if (!config?.configured) return;
    let ws: WebSocket | null = null;
    try {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${window.location.host}/ws/events`);
      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === "github_event") {
            fetchAll();
            if (activeTab === "issues") fetchIssues();
            if (activeTab === "releases") fetchReleases();
            if (activeTab === "commits") fetchCommits();
            if (activeTab === "webhooks") fetchWebhookEvents();
            if (activeTab === "repos") fetchGiteaRepos();
            if (activeTab === "pipelines") fetchPipelines();
          }
        } catch { /* ignore */ }
      };
    } catch { /* ignore */ }
    return () => { ws?.close(); };
  }, [config, activeTab, fetchAll, fetchIssues, fetchReleases, fetchCommits, fetchWebhookEvents, fetchGiteaRepos, fetchPipelines]);
  useEffect(() => {
    if (selectedPR !== null) fetchPRDetail(selectedPR);
    else setPrDetail(null);
  }, [selectedPR, fetchPRDetail]);
  useEffect(() => {
    if (expandedRun !== null) fetchRunJobs(expandedRun);
    else setRunJobs([]);
  }, [expandedRun, fetchRunJobs]);

  const statusColor = (status: string) => {
    switch (status) {
      case "success": case "merged": return "bg-ok/10 text-ok";
      case "failure": case "closed": return "bg-danger/10 text-danger";
      case "running": case "in_progress": case "queued": return "bg-accent/10 text-accent";
      default: return "bg-faint/10 text-faint";
    }
  };

  const formatDate = (s: string) => {
    if (!s) return "";
    const d = new Date(s);
    const now = Date.now();
    const diff = now - d.getTime();
    if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h ago`;
    return d.toLocaleDateString();
  };

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">
          <PanelHead
            title={t("session:dev.title")}
            sub={t("session:dev.sub")}
          />

          {/* Repo status */}
          <div className={CARD + " p-5 mb-4"}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[14px] font-semibold text-ink">{t("session:dev.repoStatus")}</h3>
              <div className="flex gap-2">
                {config?.configured && (
                  <button className="text-[12.5px] text-accent font-medium" onClick={() => fetchAll()}>
                    <Icon name="refresh" size={13} className="inline mr-1" />{t("common:button.refresh")}
                  </button>
                )}
                <button className={BTN_ACCENT} onClick={() => setShowSetup(true)}>
                  {config?.configured ? t("session:dev.editConfig") : t("session:dev.startSession")}
                </button>
              </div>
            </div>
            {loading ? (
              <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
            ) : repo ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-[13px]">
                  <Icon name="code" size={14} className="text-muted" />
                  <span className="font-medium text-ink">{repo.name}</span>
                  <span className="px-1.5 py-0.5 rounded bg-paper border border-line text-[12px] font-mono">
                    {repo.default_branch}
                  </span>
                </div>
                {repo.description && (
                  <div className="text-[12px] text-muted">{repo.description}</div>
                )}
                <div className="text-[12px] text-muted">
                  {repo.open_issues_count} open issues
                </div>
              </div>
            ) : (
              <p className="text-[13px] text-muted">{t("session:dev.noRepo")}</p>
            )}
          </div>

          {/* Tab bar */}
          {config?.configured && (
            <>
              <div className="flex gap-1 mb-4 flex-wrap">
                {(["prs", "actions", "issues", "releases", "commits", "webhooks", "repos", "pipelines"] as const).map((tab) => (
                  <button
                    key={tab}
                    className={
                      "text-[13px] px-3 py-1.5 rounded-lg font-medium " +
                      (activeTab === tab ? "bg-accent/10 text-accent" : "text-muted hover:text-ink")
                    }
                    onClick={() => setActiveTab(tab)}
                  >
                    {tab === "prs" ? (
                      <>
                        PRs ({prs.length})
                        {reviewCount > 0 && (
                          <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-accent text-white text-[10px] font-semibold">
                            {reviewCount} {t("session:dev.reviews")}
                          </span>
                        )}
                      </>
                    ) :
                     tab === "actions" ? `Actions (${runs.length})` :
                     tab === "issues" ? `Issues (${issues.length})` :
                     tab === "releases" ? t("session:dev.releases") :
                     tab === "commits" ? t("session:dev.commits") :
                     tab === "webhooks" ? `Webhooks (${webhookEvents.length})` :
                     tab === "repos" ? `Repos (${giteaRepos.length})` :
                     "Pipelines"}
                  </button>
                ))}
              </div>

              {/* PRs Tab */}
              {activeTab === "prs" && (
                <div className={CARD + " p-5 mb-4"}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[14px] font-semibold text-ink">{t("session:dev.recentPRs")}</h3>
                    <div className="flex gap-1">
                      {(["open", "closed", "all"] as const).map((f) => (
                        <button
                          key={f}
                          className={"text-[11.5px] px-2 py-1 rounded " +
                            (prFilter === f ? "bg-accent/10 text-accent font-medium" : "text-muted")}
                          onClick={() => setPrFilter(f)}
                        >{f}</button>
                      ))}
                    </div>
                  </div>
                  {prs.length === 0 ? (
                    <p className="text-[13px] text-muted">{t("session:dev.noPRs")}</p>
                  ) : (
                    <div className="space-y-2">
                      {prs.map((pr) => (
                        <div key={pr.number}>
                          <div
                            className={"flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border cursor-pointer " +
                              (selectedPR === pr.number ? "border-accent" : "border-line")}
                            onClick={() => setSelectedPR(selectedPR === pr.number ? null : pr.number)}
                          >
                            <div className="flex-1 min-w-0">
                              <div className="text-[13px] font-medium text-ink truncate">
                                #{pr.number} {pr.title}
                              </div>
                              <div className="text-[11.5px] text-faint">
                                {pr.author} &middot; {formatDate(pr.updated_at)}
                                {pr.draft && <span className="ml-1 text-faint">(draft)</span>}
                              </div>
                            </div>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleGiteaReviewPr(pr.number); }}
                              disabled={reviewingPr === pr.number}
                              className="text-xs px-2 py-0.5 rounded bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50"
                            >
                              {reviewingPr === pr.number ? "리뷰 중..." : "AI 리뷰"}
                            </button>
                            <span className={"text-[11px] px-2 py-0.5 rounded-full font-medium " + statusColor(pr.state)}>
                              {pr.state}
                            </span>
                          </div>
                          {giteaReviewResult[pr.number] && (
                            <div className="mt-2 mx-3 p-2 rounded bg-paper text-xs">
                              <span className={giteaReviewResult[pr.number].verdict === "APPROVED" ? "text-green-400" : giteaReviewResult[pr.number].verdict === "REQUEST_CHANGES" ? "text-red-400" : "text-yellow-400"}>
                                {giteaReviewResult[pr.number].verdict}
                              </span>
                              <span className="ml-2 text-muted">점수: {giteaReviewResult[pr.number].score}/100</span>
                              {giteaReviewResult[pr.number].labels?.length > 0 && (
                                <span className="ml-2 text-muted">라벨: {giteaReviewResult[pr.number].labels.join(", ")}</span>
                              )}
                            </div>
                          )}
                          {selectedPR === pr.number && (
                            <div className="mt-1 ml-3 p-4 rounded-lg bg-paper border border-line">
                              {prDetailLoading ? (
                                <p className="text-[13px] text-muted">Loading...</p>
                              ) : prDetail ? (
                                <div className="space-y-3">
                                  {prDetail.body && (
                                    <div className="text-[12.5px] text-ink whitespace-pre-wrap max-h-[200px] overflow-y-auto">
                                      {prDetail.body}
                                    </div>
                                  )}
                                  <div className="flex gap-4 text-[12px]">
                                    <span className="text-ok font-medium">+{prDetail.additions} {t("session:dev.additions")}</span>
                                    <span className="text-danger font-medium">-{prDetail.deletions} {t("session:dev.deletions")}</span>
                                    <span className="text-muted">{prDetail.changed_files} files</span>
                                  </div>
                                  {prDetail.reviews.length > 0 && (
                                    <div>
                                      <h4 className="text-[12px] font-semibold text-muted mb-1">{t("session:dev.reviews")}</h4>
                                      <div className="space-y-1">
                                        {prDetail.reviews.map((rv, i) => (
                                          <div key={i} className="flex items-center gap-2 text-[12px]">
                                            <span className="font-medium text-ink">{rv.user}</span>
                                            <span className={"px-1.5 py-0.5 rounded-full text-[10px] font-medium " + statusColor(
                                              rv.state === "APPROVED" ? "success" : rv.state === "CHANGES_REQUESTED" ? "failure" : ""
                                            )}>{rv.state}</span>
                                            {rv.body && <span className="text-faint truncate max-w-[300px]">{rv.body}</span>}
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                  {prDetail.checks.length > 0 && (
                                    <div>
                                      <h4 className="text-[12px] font-semibold text-muted mb-1">{t("session:dev.checks")}</h4>
                                      <div className="space-y-1">
                                        {prDetail.checks.map((ck, i) => (
                                          <div key={i} className="flex items-center gap-2 text-[12px]">
                                            <span className={"w-2 h-2 rounded-full " + (
                                              ck.conclusion === "success" ? "bg-ok" :
                                              ck.conclusion === "failure" ? "bg-danger" :
                                              ck.status === "in_progress" ? "bg-accent" : "bg-faint"
                                            )} />
                                            <span className="text-ink">{ck.name}</span>
                                            <span className="text-faint">{ck.conclusion || ck.status}</span>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                  {/* Merge & AI Review actions */}
                                  <div className="flex items-center gap-2 pt-2 border-t border-line">
                                    <button
                                      className="text-[12px] px-2.5 py-1.5 rounded-lg bg-accent/10 text-accent font-medium disabled:opacity-40"
                                      disabled={reviewLoading}
                                      onClick={() => handleAIReview(prDetail.number)}
                                    >
                                      {reviewLoading ? "..." : t("session:dev.aiReview")}
                                    </button>
                                    {prDetail.state === "open" && !showMergeConfirm && (
                                      <div className="flex items-center gap-1">
                                        <select
                                          className="text-[11px] px-1.5 py-1 rounded border border-line bg-paper text-ink"
                                          value={mergeMethod}
                                          onChange={(e) => setMergeMethod(e.target.value as "squash" | "merge" | "rebase")}
                                        >
                                          <option value="squash">{t("session:dev.squash")}</option>
                                          <option value="merge">{t("session:dev.merge")}</option>
                                          <option value="rebase">{t("session:dev.rebase")}</option>
                                        </select>
                                        <button
                                          className="text-[12px] px-2.5 py-1.5 rounded-lg bg-ok/10 text-ok font-medium"
                                          onClick={() => setShowMergeConfirm(true)}
                                        >
                                          {t("session:dev.merge")}
                                        </button>
                                      </div>
                                    )}
                                    {showMergeConfirm && (
                                      <div className="flex items-center gap-2">
                                        <span className="text-[12px] text-ink">{t("session:dev.mergeConfirm")}</span>
                                        <button
                                          className="text-[11px] px-2 py-1 rounded bg-ok text-white font-medium disabled:opacity-40"
                                          disabled={merging}
                                          onClick={() => handleMerge(prDetail.number, mergeMethod)}
                                        >
                                          {merging ? "..." : "OK"}
                                        </button>
                                        <button
                                          className="text-[11px] px-2 py-1 rounded border border-line text-muted"
                                          onClick={() => setShowMergeConfirm(false)}
                                        >
                                          Cancel
                                        </button>
                                      </div>
                                    )}
                                  </div>
                                  {reviewResult && (
                                    <div className="mt-2 p-3 rounded-lg bg-paper border border-line text-[12px] text-ink whitespace-pre-wrap">
                                      {reviewResult}
                                    </div>
                                  )}
                                </div>
                              ) : null}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Actions Tab */}
              {activeTab === "actions" && (
                <div className={CARD + " p-5 mb-4"}>
                  <h3 className="text-[14px] font-semibold text-ink mb-3">{t("session:dev.pipelines")}</h3>
                  {runs.length === 0 ? (
                    <p className="text-[13px] text-muted">{t("session:dev.noPipelines")}</p>
                  ) : (
                    <div className="space-y-2">
                      {runs.map((run) => (
                        <div key={run.id}>
                          <div
                            className={"flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border cursor-pointer " +
                              (expandedRun === run.id ? "border-accent" : "border-line")}
                            onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)}
                          >
                            <div className="flex-1 min-w-0">
                              <div className="text-[13px] font-medium text-ink truncate">{run.name}</div>
                              <div className="text-[11.5px] text-faint">
                                {run.head_branch} &middot; {formatDate(run.created_at)}
                              </div>
                            </div>
                            <span className={"text-[11px] px-2 py-0.5 rounded-full font-medium " + statusColor(run.conclusion || run.status)}>
                              {run.conclusion || run.status}
                            </span>
                          </div>
                          {expandedRun === run.id && (
                            <div className="mt-1 ml-3 p-4 rounded-lg bg-paper border border-line">
                              {runJobsLoading ? (
                                <p className="text-[13px] text-muted">Loading...</p>
                              ) : runJobs.length === 0 ? (
                                <p className="text-[13px] text-muted">{t("session:dev.noJobs")}</p>
                              ) : (
                                <div className="space-y-3">
                                  {runJobs.map((job, ji) => (
                                    <div key={ji}>
                                      <div className="flex items-center gap-2 mb-1.5">
                                        <span className={"text-[12px] font-semibold " + (
                                          job.conclusion === "success" ? "text-ok" :
                                          job.conclusion === "failure" ? "text-danger" : "text-ink"
                                        )}>{job.name}</span>
                                        <span className={"text-[10px] px-1.5 py-0.5 rounded-full font-medium " + statusColor(job.conclusion || job.status)}>
                                          {job.conclusion || job.status}
                                        </span>
                                      </div>
                                      <div className="ml-3 space-y-0.5">
                                        {job.steps.map((step, si) => (
                                          <div key={si} className="flex items-center gap-2 text-[11.5px]">
                                            <span className={"w-1.5 h-1.5 rounded-full shrink-0 " + (
                                              step.conclusion === "success" ? "bg-ok" :
                                              step.conclusion === "failure" ? "bg-danger" :
                                              step.conclusion === "skipped" ? "bg-faint" :
                                              step.status === "in_progress" ? "bg-accent" : "bg-faint"
                                            )} />
                                            <span className="text-muted">{step.name}</span>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Issues Tab */}
              {activeTab === "issues" && (
                <div className={CARD + " p-5 mb-4"}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[14px] font-semibold text-ink">Issues</h3>
                    <button className={BTN_ACCENT} onClick={() => setShowNewIssue(true)}>
                      {t("session:dev.newIssue")}
                    </button>
                  </div>
                  {issues.length === 0 ? (
                    <p className="text-[13px] text-muted">No open issues.</p>
                  ) : (
                    <div className="space-y-2">
                      {issues.map((issue) => (
                        <div key={issue.number} className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line">
                          <div className="flex-1 min-w-0">
                            <div className="text-[13px] font-medium text-ink truncate">
                              #{issue.number} {issue.title}
                            </div>
                            <div className="text-[11.5px] text-faint flex gap-1.5 items-center">
                              <span>{issue.author}</span>
                              <span>&middot;</span>
                              <span>{formatDate(issue.updated_at)}</span>
                              {issue.labels.slice(0, 3).map((l) => (
                                <span key={l} className="px-1.5 py-0.5 rounded bg-accent/10 text-accent text-[10px]">{l}</span>
                              ))}
                            </div>
                          </div>
                          <span className={"text-[11px] px-2 py-0.5 rounded-full font-medium " + statusColor(issue.state)}>
                            {issue.state}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Releases Tab */}
              {activeTab === "releases" && (
                <div className={CARD + " p-5 mb-4"}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[14px] font-semibold text-ink">{t("session:dev.releases")}</h3>
                    <button className={BTN_ACCENT} onClick={() => setShowNewRelease(true)}>
                      {t("session:dev.newRelease")}
                    </button>
                  </div>
                  {releases.length === 0 ? (
                    <p className="text-[13px] text-muted">{t("session:dev.noReleases")}</p>
                  ) : (
                    <div className="space-y-2">
                      {releases.map((rel) => (
                        <div key={rel.id} className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line">
                          <div className="flex-1 min-w-0">
                            <div className="text-[13px] font-medium text-ink truncate">
                              <span className="font-mono text-accent">{rel.tag_name}</span>
                              {rel.name && <span className="ml-2">{rel.name}</span>}
                            </div>
                            <div className="text-[11.5px] text-faint">
                              {rel.author} &middot; {formatDate(rel.published_at)}
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            {rel.draft && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-faint/10 text-faint font-medium">
                                {t("session:dev.draft")}
                              </span>
                            )}
                            {rel.prerelease && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-accent/10 text-accent font-medium">
                                pre
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Commits Tab */}
              {activeTab === "commits" && (
                <div className={CARD + " p-5 mb-4"}>
                  <h3 className="text-[14px] font-semibold text-ink mb-3">{t("session:dev.commits")}</h3>
                  {commits.length === 0 ? (
                    <p className="text-[13px] text-muted">{t("session:dev.noCommits")}</p>
                  ) : (
                    <div className="space-y-0">
                      {commits.map((c, i) => (
                        <div key={i} className="flex items-start gap-3">
                          <div className="flex flex-col items-center">
                            <div className="w-2.5 h-2.5 rounded-full bg-accent border-2 border-accent/30" />
                            {i < commits.length - 1 && <div className="w-0.5 flex-1 bg-line min-h-[24px]" />}
                          </div>
                          <div className="flex-1 pb-3">
                            <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-paper border border-line">
                              <span className="text-[12px] font-mono text-accent shrink-0">{c.sha}</span>
                              <div className="flex-1 min-w-0">
                                <div className="text-[13px] text-ink truncate">{c.message}</div>
                                <div className="text-[11px] text-faint">
                                  {c.author} &middot; {formatDate(c.date)}
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Webhooks Tab */}
              {activeTab === "webhooks" && (
                <div className={CARD + " p-5 mb-4"}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[14px] font-semibold text-ink">Gitea Webhook Events</h3>
                    <button className="text-[12.5px] text-accent font-medium" onClick={fetchWebhookEvents}>
                      <Icon name="refresh" size={13} className="inline mr-1" />Refresh
                    </button>
                  </div>
                  <div className="space-y-2">
                    {webhookEvents.length === 0 ? (
                      <div className="text-center text-muted text-xs py-8">Webhook 이벤트가 없습니다</div>
                    ) : webhookEvents.map((e, i) => {
                      const iconMap: Record<string, IconName> = { push: "code", pull_request: "branch", issues: "info", release: "diamond", create: "plus", delete: "trash" };
                      const iconName: IconName = iconMap[e.event_type as string] || "pin";
                      return (
                        <div key={i} className={CARD + " p-3 text-xs"}>
                          <div className="flex items-center gap-2">
                            <Icon name={iconName} size={14} className="text-accent shrink-0" />
                            <span className="font-medium">{e.event_type}</span>
                            {e.action && <span className="text-muted">({e.action})</span>}
                            <span className="text-muted ml-auto">{e.sender}</span>
                            <span className="text-muted">{new Date(e.timestamp * 1000).toLocaleString("ko-KR", { hour12: false })}</span>
                          </div>
                          <div className="mt-1 text-muted">{e.summary}</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Repos Tab */}
              {activeTab === "repos" && (
                <div className={CARD + " p-5 mb-4"}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[14px] font-semibold text-ink">Gitea Repositories</h3>
                    <button className="text-[12.5px] text-accent font-medium" onClick={fetchGiteaRepos}>
                      <Icon name="refresh" size={13} className="inline mr-1" />Refresh
                    </button>
                  </div>
                  {/* Wiki sync */}
                  <div className="flex gap-2 mb-3">
                    <button
                      onClick={async () => {
                        setSyncing(true);
                        try {
                          const res = await fetch("/v1/gitea/wiki/sync-to-gitea", {
                            method: "POST", headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ owner: config?.owner || "shin", repo: config?.repo || "werubworker" }),
                          });
                          setSyncResult(await res.json());
                        } catch {}
                        setSyncing(false);
                      }}
                      disabled={syncing}
                      className="text-xs px-2 py-1 rounded bg-paper hover:bg-accent/10 disabled:opacity-50"
                    >
                      {syncing ? "동기화 중..." : "Wiki → Gitea 동기화"}
                    </button>
                    {syncResult && (
                      <span className="text-xs text-muted">
                        {syncResult.ok ? `✅ ${syncResult.synced || syncResult.imported || 0}건 동기화` : `❌ ${syncResult.error}`}
                      </span>
                    )}
                  </div>
                  <div className="space-y-2">
                    {giteaRepos.length === 0 ? (
                      <div className="text-center text-muted text-xs py-8">리포지토리가 없습니다</div>
                    ) : giteaRepos.map((r, i) => (
                      <div key={i} className={CARD + " p-3 text-xs"}>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-accent">{r.full_name}</span>
                          {r.language && <span className="px-1.5 py-0.5 rounded bg-paper text-muted text-[10px]">{r.language}</span>}
                          <button
                            onClick={() => { const parts = r.full_name.split("/"); fetchFileTree(parts[0], parts[1]); }}
                            className="text-xs px-2 py-0.5 rounded bg-paper hover:bg-accent/10"
                          >
                            코드 탐색
                          </button>
                          <button onClick={async () => {
                              const parts = r.full_name.split("/");
                              const [statsRes, contribRes] = await Promise.all([
                                  fetch(`/v1/gitea/repos/${parts[0]}/${parts[1]}/stats`).then(x => x.json()),
                                  fetch(`/v1/gitea/repos/${parts[0]}/${parts[1]}/contributors`).then(x => x.json()),
                              ]);
                              if (statsRes?.ok) setRepoStats(statsRes);
                              if (contribRes?.ok) setContributors(contribRes.contributors || []);
                          }} className="text-xs px-2 py-0.5 rounded bg-paper hover:bg-accent/10">통계</button>
                          <button onClick={async () => {
                              setScanningSecrets(true);
                              const parts = r.full_name.split("/");
                              const res = await fetch(`/v1/gitea/repos/${parts[0]}/${parts[1]}/secret-scan`).then(x => x.json());
                              setSecretScan(res);
                              setScanningSecrets(false);
                          }} disabled={scanningSecrets}
                          className="text-xs px-2 py-0.5 rounded bg-paper hover:bg-accent/10">
                              {scanningSecrets ? "스캔..." : "시크릿 스캔"}
                          </button>
                          <span className="ml-auto text-muted">{"*"} {r.stars} | {r.forks} forks | {r.open_issues} issues</span>
                        </div>
                        {r.description && <div className="mt-1 text-muted">{r.description}</div>}
                        <div className="mt-1 text-muted text-[10px]">
                          {r.updated_at ? new Date(r.updated_at).toLocaleDateString("ko-KR") : ""}
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* Repo Stats Panel */}
                  {repoStats && (
                    <div className={CARD + " p-4 mt-4"}>
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="text-sm font-semibold">리포 통계: {repoStats.repo?.full_name}</h3>
                            <button onClick={() => setRepoStats(null)} className="text-xs text-muted hover:text-ink">닫기</button>
                        </div>
                        <div className="grid grid-cols-4 gap-3 text-xs mb-3">
                            <div className="text-center p-2 rounded bg-paper"><div className="text-lg font-bold text-accent">{repoStats.branches}</div><div className="text-muted">브랜치</div></div>
                            <div className="text-center p-2 rounded bg-paper"><div className="text-lg font-bold text-accent">{repoStats.tags}</div><div className="text-muted">태그</div></div>
                            <div className="text-center p-2 rounded bg-paper"><div className="text-lg font-bold text-yellow-400">{repoStats.open_pulls}</div><div className="text-muted">Open PR</div></div>
                            <div className="text-center p-2 rounded bg-paper"><div className="text-lg font-bold text-red-400">{repoStats.open_issues}</div><div className="text-muted">Open Issues</div></div>
                        </div>
                        {/* Languages */}
                        {repoStats.languages && Object.keys(repoStats.languages).length > 0 && (
                            <div className="mb-3">
                                <div className="text-xs text-muted mb-1">언어</div>
                                <div className="flex gap-1">
                                    {Object.entries(repoStats.languages).map(([lang, _bytes]) => (
                                        <span key={lang} className="text-[10px] px-1.5 py-0.5 rounded bg-accent/10 text-accent">{lang}</span>
                                    ))}
                                </div>
                            </div>
                        )}
                        {/* Contributors */}
                        {contributors.length > 0 && (
                            <div>
                                <div className="text-xs text-muted mb-1">기여자</div>
                                <div className="space-y-1">
                                    {contributors.slice(0, 5).map((c: any, i: number) => (
                                        <div key={i} className="flex items-center gap-2 text-xs">
                                            <span className="font-medium w-20">{c.user}</span>
                                            <div className="flex-1 h-1.5 rounded-full bg-line overflow-hidden">
                                                <div className="h-full rounded-full bg-accent/50" style={{ width: `${Math.min(100, (c.commits / Math.max(...contributors.map((x: any) => x.commits), 1)) * 100)}%` }} />
                                            </div>
                                            <span className="text-muted">{c.commits} commits</span>
                                            {c.prs > 0 && <span className="text-muted">{c.prs} PRs</span>}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                  )}

                  {/* Secret Scan Result */}
                  {secretScan && (
                    <div className={CARD + " p-4 mt-4"}>
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-sm font-semibold">시크릿 스캔 결과</h3>
                            <button onClick={() => setSecretScan(null)} className="text-xs text-muted hover:text-ink">닫기</button>
                        </div>
                        <div className="text-xs mb-2">
                            전체 {secretScan.total || 0}건 | <span className="text-red-400">Critical {secretScan.critical || 0}</span>
                        </div>
                        {secretScan.findings?.length > 0 ? (
                            <div className="space-y-1">
                                {secretScan.findings.map((f: any, i: number) => (
                                    <div key={i} className={`text-xs p-1.5 rounded ${f.severity === "critical" ? "bg-red-500/10 text-red-400" : "bg-yellow-500/10 text-yellow-400"}`}>
                                        [{f.severity}] {f.type} — {f.location} {f.message || ""}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div className="text-xs text-green-400">시크릿이 발견되지 않았습니다</div>
                        )}
                    </div>
                  )}

                  {/* Code Browser */}
                  {fileTree.length > 0 && (
                    <div className={CARD + " p-4 mt-4"}>
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-semibold">코드 브라우저: {browsingRepo}</h3>
                        <button onClick={() => { setFileTree([]); setSelectedFile(null); }}
                          className="text-xs text-muted hover:text-ink">닫기</button>
                      </div>
                      <div className="flex gap-3" style={{ maxHeight: "400px" }}>
                        {/* File Tree */}
                        <div className="w-64 overflow-auto border-r border-line pr-3">
                          {(() => {
                            const dirs: Record<string, typeof fileTree> = {};
                            const rootFiles: typeof fileTree = [];
                            fileTree.forEach((f) => {
                              const parts = f.path.split("/");
                              if (parts.length === 1) { rootFiles.push(f); }
                              else {
                                const dir = parts[0];
                                if (!dirs[dir]) dirs[dir] = [];
                                dirs[dir].push(f);
                              }
                            });
                            return (
                              <>
                                {Object.keys(dirs).sort().map((dir) => (
                                  <details key={dir} className="mb-1">
                                    <summary className="text-xs cursor-pointer text-muted hover:text-ink py-0.5">
                                      📁 {dir} <span className="text-[10px]">({dirs[dir].length})</span>
                                    </summary>
                                    <div className="pl-3">
                                      {dirs[dir].filter((f) => f.type === "blob").slice(0, 30).map((f) => (
                                        <div key={f.path}
                                          onClick={() => { const parts = browsingRepo.split("/"); fetchFileContent(parts[0], parts[1], f.path); }}
                                          className={`text-xs py-0.5 cursor-pointer hover:text-accent truncate ${selectedFile?.path === f.path ? "text-accent font-medium" : "text-muted"}`}>
                                          📄 {f.path.split("/").pop()}
                                        </div>
                                      ))}
                                    </div>
                                  </details>
                                ))}
                                {rootFiles.filter((f) => f.type === "blob").map((f) => (
                                  <div key={f.path}
                                    onClick={() => { const parts = browsingRepo.split("/"); fetchFileContent(parts[0], parts[1], f.path); }}
                                    className={`text-xs py-0.5 cursor-pointer hover:text-accent ${selectedFile?.path === f.path ? "text-accent font-medium" : "text-muted"}`}>
                                    📄 {f.path}
                                  </div>
                                ))}
                              </>
                            );
                          })()}
                        </div>
                        {/* File Content */}
                        <div className="flex-1 overflow-auto">
                          {selectedFile ? (
                            <div>
                              <div className="text-xs text-muted mb-2 flex items-center gap-2">
                                <span className="font-mono">{selectedFile.path}</span>
                                {selectedFile.sha && <span className="text-[10px]">SHA: {selectedFile.sha.slice(0, 8)}</span>}
                              </div>
                              <pre className="text-xs font-mono bg-paper p-3 rounded overflow-auto whitespace-pre-wrap" style={{ maxHeight: "350px" }}>
                                {selectedFile.content}
                              </pre>
                            </div>
                          ) : (
                            <div className="text-xs text-muted text-center py-8">파일을 선택하세요</div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Pipelines Tab */}
              {activeTab === "pipelines" && (
                <div className={CARD + " p-5 mb-4"}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[14px] font-semibold text-ink">CI/CD Pipelines</h3>
                    <button className="text-[12.5px] text-accent font-medium" onClick={fetchPipelines}>
                      <Icon name="refresh" size={13} className="inline mr-1" />Refresh
                    </button>
                  </div>

                  {/* Pipeline Configs */}
                  <div className="grid grid-cols-3 gap-3 mb-4">
                    {pipelines.map((p, i) => (
                      <div key={i} className={CARD + " p-3"}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-semibold">{p.name}</span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-paper text-muted">{p.trigger}</span>
                        </div>
                        <div className="text-xs text-muted mb-2">
                          브랜치: {p.branch_filter} | 단계: {p.stages?.join(" → ")}
                        </div>
                        <button
                          onClick={async () => {
                            setRunningPipeline(p.name);
                            try {
                              await fetch(`/v1/gitea/pipelines/${p.name}/run`, { method: "POST" });
                              fetchPipelines();
                            } catch {}
                            setRunningPipeline(null);
                          }}
                          disabled={runningPipeline === p.name}
                          className="text-xs px-2 py-1 rounded bg-accent text-white hover:bg-accent/90 disabled:opacity-50"
                        >
                          {runningPipeline === p.name ? "실행 중..." : "실행"}
                        </button>
                      </div>
                    ))}
                  </div>

                  {/* Pipeline Runs */}
                  <h3 className="text-sm font-semibold mb-2">실행 이력</h3>
                  <div className="space-y-1">
                    {pipelineRuns.map((r, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs p-2 rounded bg-paper">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium text-white ${r.status === "success" ? "bg-green-500" : r.status === "failed" ? "bg-red-500" : "bg-yellow-500"}`}>
                          {r.status}
                        </span>
                        <span className="font-medium">{r.pipeline}</span>
                        <span className="text-muted">{r.trigger} {r.ref}</span>
                        {r.sha && <span className="text-muted font-mono">{r.sha}</span>}
                        <span className="ml-auto text-muted">{r.duration_ms}ms</span>
                        <span className="text-muted">{r.user}</span>
                      </div>
                    ))}
                    {pipelineRuns.length === 0 && <div className="text-center text-muted text-xs py-4">실행 이력이 없습니다</div>}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      {showSetup && <SetupModal onClose={() => setShowSetup(false)} onSaved={fetchAll} />}
      {showNewIssue && <NewIssueModal onClose={() => setShowNewIssue(false)} onCreated={fetchIssues} />}
      {showNewRelease && <NewReleaseModal onClose={() => setShowNewRelease(false)} onCreated={fetchReleases} />}
    </main>
  );
}
