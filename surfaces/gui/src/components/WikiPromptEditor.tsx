import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const CARD = "rounded-xl2 border border-line bg-panel";

interface PromptRun {
  run_id: string;
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  success: number;
  variables: Record<string, string>;
  output_preview: string;
  created_at: number;
}

interface AbTestResult {
  version_a: { version: number; content: string };
  version_b: { version: number; content: string };
}

export function WikiPromptEditor({ pageId, content }: { pageId: string; content: string }) {
  const { t } = useTranslation(["session"]);
  const [runs, setRuns] = useState<PromptRun[]>([]);
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [abResult, setAbResult] = useState<AbTestResult | null>(null);
  const [abLoading, setAbLoading] = useState(false);

  // Extract {{variable}} from content
  const varNames = [...new Set((content.match(/\{\{(\w+)\}\}/g) || []).map(v => v.slice(2, -2)))];

  const fetchRuns = useCallback(() => {
    fetch(`/v1/wiki/prompts/${pageId}/runs`)
      .then(r => r.json())
      .then(d => setRuns(d.runs || []))
      .catch(() => {});
  }, [pageId]);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  const handleTest = async () => {
    await fetch(`/v1/wiki/prompts/${pageId}/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ variables, model_id: "test" }),
    });
    fetchRuns();
  };

  const handleAbTest = async () => {
    setAbLoading(true);
    try {
      const r = await fetch(`/v1/wiki/prompts/${pageId}/ab-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const d = await r.json();
      if (d.ok) setAbResult(d);
    } catch { /* ignore */ }
    setAbLoading(false);
  };

  const successRate = runs.length > 0
    ? Math.round((runs.filter(r => r.success).length / runs.length) * 100)
    : 0;

  return (
    <div className="space-y-4 mt-4">
      {/* Variables */}
      {varNames.length > 0 && (
        <div className={CARD + " p-4"}>
          <h4 className="text-[13px] font-semibold text-ink mb-3">{t("session:wiki.variables")}</h4>
          <div className="grid grid-cols-2 gap-3">
            {varNames.map(v => (
              <div key={v}>
                <label className="block text-[11px] text-muted mb-1">{`{{${v}}}`}</label>
                <input className="w-full text-[12px] px-2.5 py-1.5 rounded-lg border border-line bg-paper text-ink"
                  value={variables[v] || ""} onChange={e => setVariables(prev => ({...prev, [v]: e.target.value}))}
                  placeholder={v} />
              </div>
            ))}
          </div>
          <button className="mt-3 text-[12.5px] px-3 py-1.5 rounded-lg bg-accent text-white" onClick={handleTest}>
            {t("session:wiki.testRun")}
          </button>
        </div>
      )}

      {/* Stats */}
      {runs.length > 0 && (
        <div className={CARD + " p-4"}>
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-[13px] font-semibold text-ink">
              {t("session:wiki.promptRuns")} ({runs.length} runs, {successRate}% {t("session:wiki.successRate").toLowerCase()})
            </h4>
            <button
              className="text-[12px] px-2.5 py-1 rounded-lg border border-line text-muted hover:text-ink"
              onClick={handleAbTest}
              disabled={abLoading}
            >
              {abLoading ? t("common:status.loading") : t("session:wiki.abCompare")}
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-muted text-left border-b border-line">
                  <th className="pb-2 pr-3">Model</th>
                  <th className="pb-2 pr-3">In/Out</th>
                  <th className="pb-2 pr-3">Latency</th>
                  <th className="pb-2 pr-3">Status</th>
                  <th className="pb-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 20).map(run => (
                  <tr key={run.run_id} className="border-b border-line/50 text-ink">
                    <td className="py-1.5 pr-3 font-mono">{run.model_id}</td>
                    <td className="py-1.5 pr-3">{run.input_tokens}/{run.output_tokens}</td>
                    <td className="py-1.5 pr-3">{run.latency_ms}ms</td>
                    <td className="py-1.5 pr-3">
                      <span className={run.success ? "text-ok" : "text-err"}>{run.success ? "\u2713" : "\u2717"}</span>
                    </td>
                    <td className="py-1.5 text-faint">{new Date(run.created_at * 1000).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* A/B Compare button when no runs exist */}
      {runs.length === 0 && (
        <button
          className="text-[12.5px] px-3 py-1.5 rounded-lg border border-line text-muted hover:text-ink"
          onClick={handleAbTest}
          disabled={abLoading}
        >
          {abLoading ? t("common:status.loading") : t("session:wiki.abCompare")}
        </button>
      )}

      {/* A/B Compare results */}
      {abResult && (
        <div className={CARD + " p-4"}>
          <h4 className="text-[13px] font-semibold text-ink mb-3">{t("session:wiki.abCompare")}</h4>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-[11px] text-muted mb-1">
                {t("session:wiki.version")} {abResult.version_a.version}
              </div>
              <pre className="text-[11.5px] bg-paper border border-line rounded-lg p-3 whitespace-pre-wrap max-h-[300px] overflow-y-auto">
                {abResult.version_a.content}
              </pre>
            </div>
            <div>
              <div className="text-[11px] text-muted mb-1">
                {t("session:wiki.version")} {abResult.version_b.version}
              </div>
              <pre className="text-[11.5px] bg-paper border border-line rounded-lg p-3 whitespace-pre-wrap max-h-[300px] overflow-y-auto">
                {abResult.version_b.content}
              </pre>
            </div>
          </div>
          <button
            className="mt-2 text-[11px] text-muted hover:text-ink"
            onClick={() => setAbResult(null)}
          >
            {t("session:wiki.cancel")}
          </button>
        </div>
      )}
    </div>
  );
}
