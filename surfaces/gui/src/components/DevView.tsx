import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelHead } from "./IntegrationsView";
import { Icon } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";
const BTN_ACCENT =
  "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";

interface RepoStatus {
  name: string;
  branch: string;
  ahead: number;
  behind: number;
  dirty: boolean;
}

interface PipelineRun {
  id: string;
  name: string;
  status: "success" | "failure" | "running" | "pending";
  time: string;
}

interface PullRequest {
  id: string;
  title: string;
  author: string;
  state: "open" | "merged" | "closed";
  number: number;
  updated: string;
}

export function DevView() {
  const { t } = useTranslation(["session", "common"]);
  const [repo] = useState<RepoStatus | null>(null);
  const [pipelines] = useState<PipelineRun[]>([]);
  const [prs] = useState<PullRequest[]>([]);

  const statusColor = (status: string) => {
    switch (status) {
      case "success":
      case "merged":
        return "bg-ok/10 text-ok";
      case "failure":
      case "closed":
        return "bg-danger/10 text-danger";
      case "running":
        return "bg-accent/10 text-accent";
      default:
        return "bg-faint/10 text-faint";
    }
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
              <h3 className="text-[14px] font-semibold text-ink">
                {t("session:dev.repoStatus")}
              </h3>
              <button className={BTN_ACCENT}>
                {t("session:dev.startSession")}
              </button>
            </div>
            {repo ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-[13px]">
                  <Icon name="code" size={14} className="text-muted" />
                  <span className="font-medium text-ink">{repo.name}</span>
                  <span className="text-faint">on</span>
                  <span className="px-1.5 py-0.5 rounded bg-paper border border-line text-[12px] font-mono">
                    {repo.branch}
                  </span>
                </div>
                <div className="text-[12px] text-muted">
                  {repo.ahead > 0 && <span className="mr-2">+{repo.ahead} ahead</span>}
                  {repo.behind > 0 && <span className="mr-2">-{repo.behind} behind</span>}
                  {repo.dirty && <span className="text-warn">uncommitted changes</span>}
                </div>
              </div>
            ) : (
              <p className="text-[13px] text-muted">
                {t("session:dev.noRepo")}
              </p>
            )}
          </div>

          {/* CI/CD Pipelines */}
          <div className={CARD + " p-5 mb-4"}>
            <h3 className="text-[14px] font-semibold text-ink mb-3">
              {t("session:dev.pipelines")}
            </h3>
            {pipelines.length === 0 ? (
              <p className="text-[13px] text-muted">
                {t("session:dev.noPipelines")}
              </p>
            ) : (
              <div className="space-y-2">
                {pipelines.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-ink truncate">
                        {p.name}
                      </div>
                    </div>
                    <span className="text-[11px] text-faint">{p.time}</span>
                    <span
                      className={
                        "text-[11px] px-2 py-0.5 rounded-full font-medium " +
                        statusColor(p.status)
                      }
                    >
                      {p.status}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Recent PRs */}
          <div className={CARD + " p-5"}>
            <h3 className="text-[14px] font-semibold text-ink mb-3">
              {t("session:dev.recentPRs")}
            </h3>
            {prs.length === 0 ? (
              <p className="text-[13px] text-muted">
                {t("session:dev.noPRs")}
              </p>
            ) : (
              <div className="space-y-2">
                {prs.map((pr) => (
                  <div
                    key={pr.id}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-ink truncate">
                        #{pr.number} {pr.title}
                      </div>
                      <div className="text-[11.5px] text-faint">
                        {pr.author} &middot; {pr.updated}
                      </div>
                    </div>
                    <span
                      className={
                        "text-[11px] px-2 py-0.5 rounded-full font-medium " +
                        statusColor(pr.state)
                      }
                    >
                      {pr.state}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
