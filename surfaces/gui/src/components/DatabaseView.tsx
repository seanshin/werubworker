import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelHead } from "./IntegrationsView";
import { Icon } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";
const INPUT =
  "flex-1 min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BTN_ACCENT =
  "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12.5px] px-3 py-2 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0";

interface DatabaseConfig {
  id: string;
  name: string;
  type: string;
  host: string;
  port?: number;
  database?: string;
  status?: string;
}

interface QueryResult {
  columns: string[];
  rows: string[][];
  rowCount: number;
  error?: string;
}

export function DatabaseView() {
  const { t } = useTranslation(["session", "common"]);
  const [databases, setDatabases] = useState<DatabaseConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDb, setSelectedDb] = useState<string>("");
  const [query, setQuery] = useState("");
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [executing, setExecuting] = useState(false);
  const [tables] = useState<string[]>([]);
  const [backingUp, setBackingUp] = useState(false);

  const fetchDatabases = useCallback(() => {
    setLoading(true);
    fetch("/v1/databases")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        const list = Array.isArray(data) ? data : [];
        setDatabases(list);
        if (list.length > 0 && !selectedDb) setSelectedDb(list[0].id);
      })
      .catch(() => setDatabases([]))
      .finally(() => setLoading(false));
  }, [selectedDb]);

  useEffect(() => {
    fetchDatabases();
  }, [fetchDatabases]);

  const executeQuery = () => {
    if (!query.trim() || !selectedDb) return;
    setExecuting(true);
    setQueryResult(null);
    fetch("/v1/databases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ database_id: selectedDb, query: query.trim() }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setQueryResult({ columns: [], rows: [], rowCount: 0, error: data.error });
        } else {
          setQueryResult({
            columns: data.columns || [],
            rows: data.rows || [],
            rowCount: data.row_count ?? (data.rows || []).length,
          });
        }
      })
      .catch((err) =>
        setQueryResult({
          columns: [],
          rows: [],
          rowCount: 0,
          error: String(err),
        }),
      )
      .finally(() => setExecuting(false));
  };

  const requestBackup = () => {
    if (!selectedDb) return;
    setBackingUp(true);
    fetch("/v1/databases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ database_id: selectedDb, action: "backup" }),
    })
      .catch(() => {})
      .finally(() => {
        setTimeout(() => setBackingUp(false), 2000);
      });
  };

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">
          <PanelHead
            title={t("session:database.title")}
            sub={t("session:database.sub")}
          />

          {/* Database selector */}
          <div className={CARD + " p-5 mb-4"}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[14px] font-semibold text-ink">
                {t("session:database.configured")}
              </h3>
              <button
                className="text-[12.5px] text-accent font-medium"
                onClick={fetchDatabases}
              >
                <Icon name="refresh" size={13} className="inline mr-1" />
                {t("common:button.refresh")}
              </button>
            </div>
            {loading ? (
              <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
            ) : databases.length === 0 ? (
              <p className="text-[13px] text-muted">
                {t("session:database.noDatabases")}
              </p>
            ) : (
              <div className="space-y-2">
                {databases.map((db) => (
                  <div
                    key={db.id}
                    className={
                      "flex items-center gap-3 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors " +
                      (selectedDb === db.id
                        ? "bg-accentSoft/30 border-accent"
                        : "bg-paper border-line hover:border-lineStrong")
                    }
                    onClick={() => setSelectedDb(db.id)}
                  >
                    <Icon name="table" size={15} className="text-muted shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-ink truncate">
                        {db.name || db.database || db.host}
                      </div>
                      <div className="text-[11.5px] text-faint truncate">
                        {db.type}://{db.host}:{db.port ?? ""}/{db.database ?? ""}
                      </div>
                    </div>
                    <span
                      className={
                        "text-[11px] px-2 py-0.5 rounded-full font-medium " +
                        (db.status === "connected"
                          ? "bg-ok/10 text-ok"
                          : "bg-faint/10 text-faint")
                      }
                    >
                      {db.status || "configured"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Query runner */}
          <div className={CARD + " p-5 mb-4"}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[14px] font-semibold text-ink">
                {t("session:database.queryRunner")}
              </h3>
              <div className="flex items-center gap-2">
                <button
                  className={BTN_BORDERED}
                  onClick={requestBackup}
                  disabled={!selectedDb || backingUp}
                >
                  {backingUp
                    ? t("common:status.running")
                    : t("session:database.backup")}
                </button>
              </div>
            </div>
            <textarea
              className={
                INPUT +
                " w-full font-mono text-[12.5px] min-h-[80px] resize-y mb-3"
              }
              placeholder={t("session:database.queryPlaceholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  executeQuery();
                }
              }}
            />
            <div className="flex items-center gap-2">
              <button
                className={BTN_ACCENT}
                onClick={executeQuery}
                disabled={!query.trim() || !selectedDb || executing}
              >
                {executing
                  ? t("common:status.running")
                  : t("session:database.execute")}
              </button>
              <span className="text-[11px] text-faint">Ctrl+Enter</span>
            </div>

            {/* Results */}
            {queryResult && (
              <div className="mt-4">
                {queryResult.error ? (
                  <div className="px-3 py-2 rounded-lg bg-danger/10 text-danger text-[12.5px]">
                    {queryResult.error}
                  </div>
                ) : (
                  <>
                    <div className="text-[11.5px] text-faint mb-2">
                      {queryResult.rowCount} {t("session:database.rows")}
                    </div>
                    {queryResult.columns.length > 0 && (
                      <div className="overflow-x-auto rounded-lg border border-line">
                        <table className="w-full text-[12px]">
                          <thead>
                            <tr className="bg-paper border-b border-line">
                              {queryResult.columns.map((col, i) => (
                                <th
                                  key={i}
                                  className="px-3 py-1.5 text-left font-semibold text-ink whitespace-nowrap"
                                >
                                  {col}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {queryResult.rows.slice(0, 100).map((row, ri) => (
                              <tr
                                key={ri}
                                className="border-b border-line last:border-b-0 hover:bg-paper/50"
                              >
                                {row.map((cell, ci) => (
                                  <td
                                    key={ci}
                                    className="px-3 py-1.5 text-muted whitespace-nowrap max-w-[200px] truncate"
                                  >
                                    {cell}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>

          {/* Tables list */}
          {tables.length > 0 && (
            <div className={CARD + " p-5"}>
              <h3 className="text-[14px] font-semibold text-ink mb-3">
                {t("session:database.tables")}
              </h3>
              <div className="space-y-1">
                {tables.map((tbl) => (
                  <div
                    key={tbl}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-paper cursor-pointer text-[13px] text-ink"
                    onClick={() => setQuery(`SELECT * FROM ${tbl} LIMIT 50;`)}
                  >
                    <Icon name="file" size={13} className="text-faint" />
                    {tbl}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
