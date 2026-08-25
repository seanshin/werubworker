import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const CARD = "rounded-xl2 border border-line bg-panel";

const LEGACY_STATUS: Record<string, string> = {
  "양호": "good", "주의": "caution", "위험": "risk",
  "활성": "active", "미확인": "unverified", "확인 불가": "unknown",
};

/** status_code가 없는 응답(구버전 서버)에서는 서버가 보낸 한국어 문구로 코드를 되짚는다. */
function statusCode(cat: ScoreCategory): string | undefined {
  return cat.status_code || LEGACY_STATUS[cat.status];
}

function statusTone(cat: ScoreCategory): string {
  const code = statusCode(cat);
  if (code === "good" || code === "active") return "text-green-400";
  if (code === "risk") return "text-red-400";
  return "text-yellow-400";
}

interface ScoreCategory {
  score: number;
  max: number;
  /** 사람이 읽는 문구. 서버가 한국어로 보낸다 — 표시에는 status_code를 쓴다. */
  status: string;
  /** 번역 가능한 안정 코드 (good/caution/risk/active/unverified/unknown). */
  status_code?: string;
}

function GradeCircle({ grade, score }: { grade: string; score: number }) {
  const { t } = useTranslation(["session"]);
  const colors: Record<string, string> = { A: "#22c55e", B: "#3b82f6", C: "#f59e0b", D: "#ef4444" };
  const color = colors[grade] || "#6b7280";
  const r = 40;
  const circumference = 2 * Math.PI * r;
  const offset = circumference - (score / 100) * circumference;
  return (
    <div className="flex flex-col items-center">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={r} fill="none" stroke="var(--line)" strokeWidth="8" />
        <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="8"
          strokeDasharray={circumference} strokeDashoffset={offset}
          strokeLinecap="round" transform="rotate(-90 50 50)"
          style={{ transition: "stroke-dashoffset 0.5s ease" }} />
        <text x="50" y="45" textAnchor="middle" fill={color} fontSize="28" fontWeight="700">{grade}</text>
        <text x="50" y="65" textAnchor="middle" fill="var(--muted)" fontSize="12">{t("session:security.points", { score })}</text>
      </svg>
    </div>
  );
}

export function SecurityView() {
  const { t } = useTranslation(["session"]);
  const [score, setScore] = useState<{ overall_score: number; grade: string; categories: Record<string, ScoreCategory> } | null>(null);
  const [loading, setLoading] = useState(false);
  const [containerImage, setContainerImage] = useState("");
  const [scanResult, setScanResult] = useState<any>(null);
  const [scanning, setScanning] = useState(false);

  const fetchScore = useCallback(() => {
    setLoading(true);
    fetch("/v1/dashboard/security/score")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.ok) setScore(d); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchScore(); }, [fetchScore]);

  const handleContainerScan = async () => {
    if (!containerImage.trim()) return;
    setScanning(true);
    try {
      const res = await fetch("/v1/dashboard/security/container-scan", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: containerImage }),
      });
      const d = await res.json();
      setScanResult(d);
    } catch { /* ignore */ }
    setScanning(false);
  };

  const categories = score?.categories || {};

  return (
    <div className="flex flex-col gap-4 p-4 overflow-auto">
      <h2 className="text-lg font-semibold">{t("session:security.title")}</h2>

      {/* Score Overview */}
      <div className="grid grid-cols-2 gap-4">
        <div className={CARD + " p-6 flex items-center gap-6"}>
          {score ? <GradeCircle grade={score.grade} score={score.overall_score} /> : (
            <div className="text-muted text-sm">{loading ? t("session:security.evaluating") : t("session:security.loadingScore")}</div>
          )}
          <div>
            <h3 className="font-semibold text-sm mb-2">{t("session:security.overallGrade")}</h3>
            <button onClick={fetchScore} disabled={loading}
              className="text-xs px-2 py-1 rounded bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50">
              {loading ? t("session:security.evaluating") : t("session:security.reevaluate")}
            </button>
          </div>
        </div>

        <div className={CARD + " p-4"}>
          <h3 className="font-semibold text-sm mb-3">{t("session:security.categoryScores")}</h3>
          <div className="space-y-2">
            {Object.entries(categories).map(([key, cat]) => (
              <div key={key} className="flex items-center gap-2 text-xs">
                <span className="w-16 text-muted capitalize">{key}</span>
                <div className="flex-1 h-2 rounded-full bg-line overflow-hidden">
                  <div className="h-full rounded-full transition-all" style={{
                    width: `${(cat.score / cat.max) * 100}%`,
                    background: cat.score >= cat.max * 0.8 ? "#22c55e" : cat.score >= cat.max * 0.5 ? "#f59e0b" : "#ef4444",
                  }} />
                </div>
                <span className="w-12 text-right">{cat.score}/{cat.max}</span>
                <span className={`w-16 text-right ${statusTone(cat)}`}>
                  {t(`session:security.status.${statusCode(cat) || "unknown"}`, { defaultValue: cat.status })}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Container Scan */}
      <div className={CARD + " p-4"}>
        <h3 className="font-semibold text-sm mb-3">{t("session:security.containerScan")}</h3>
        <div className="flex gap-2">
          <input value={containerImage} onChange={(e) => setContainerImage(e.target.value)}
            placeholder={t("session:security.imagePlaceholder")} className="flex-1 text-xs px-2 py-1.5 rounded border border-line bg-panel font-mono"
            onKeyDown={(e) => e.key === "Enter" && handleContainerScan()} />
          <button onClick={handleContainerScan} disabled={scanning || !containerImage.trim()}
            className="text-xs px-3 py-1.5 rounded bg-accent text-white hover:bg-accent/90 disabled:opacity-50">
            {scanning ? t("session:security.scanning") : t("session:security.scan")}
          </button>
        </div>
        {scanResult && (
          <div className="mt-3">
            {scanResult.ok ? (
              <div>
                <div className="text-xs text-muted mb-2">
                  {t("session:security.vulnTotal", { count: scanResult.total || 0 })} | <span className="text-red-400">CRITICAL {scanResult.critical || 0}</span> | <span className="text-yellow-400">HIGH {scanResult.high || 0}</span>
                </div>
                <div className="space-y-1 max-h-60 overflow-auto">
                  {(scanResult.vulnerabilities || []).map((v: any, i: number) => (
                    <div key={i} className="text-xs flex gap-2 p-1 rounded bg-paper">
                      <span className={`font-medium ${v.severity === "CRITICAL" ? "text-red-400" : "text-yellow-400"}`}>{v.severity}</span>
                      <span className="text-muted">{v.id}</span>
                      <span>{v.package}</span>
                      {v.fixed && <span className="text-green-400">{"\u2192"} {v.fixed}</span>}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-xs text-red-400">{scanResult.error || scanResult.message}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
