import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  deletePersona,
  getPersonas,
  getSessions,
  installPersona,
  updatePersona,
  type Persona,
  type PersonaConsent,
} from "../api";
import type { SessionInfo } from "../types";
import { Icon } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";
const SEC_H = "text-[11px] uppercase tracking-[0.05em] text-faint font-semibold";
const CHECK = "flex items-center gap-1.5 text-[12.5px] text-muted select-none shrink-0";
const SELECT = "px-2.5 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink shrink-0";
const INPUT =
  "flex-1 min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BTN_ACCENT = "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12.5px] px-2.5 py-1.5 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0 disabled:opacity-40 disabled:hover:border-line";

export function PersonasTab({ onOpenPersona }: { onOpenPersona?: (id: string) => void }) {
  const { t } = useTranslation(["settings", "common"]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [mode, setMode] = useState<"git" | "dir">("git");
  const [src, setSrc] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [consent, setConsent] = useState<PersonaConsent[] | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [confirmOff, setConfirmOff] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  const reload = () => getPersonas().then(setPersonas).catch(() => {});
  const reloadSessions = () => getSessions().then(setSessions).catch(() => {});
  useEffect(() => {
    reload();
    reloadSessions();
  }, []);

  const liveCount = (id: string) =>
    sessions.filter((s) => s.agent === id && !s.archived).length;

  const toggle = async (
    id: string,
    body: { enabled?: boolean; surfaced?: boolean; default?: boolean },
  ) => {
    const r = await updatePersona(id, body);
    if (r.personas) setPersonas(r.personas);
    else reload();
    if (body.enabled === false) reloadSessions();
  };

  const requestDisable = (p: Persona) => {
    if (liveCount(p.id) > 0) setConfirmOff(p.id);
    else toggle(p.id, { enabled: false });
  };

  const remove = async (id: string) => {
    setConfirmDel(null);
    const r = await deletePersona(id);
    if (!r.ok) {
      setMsg(r.error || "delete failed");
      return;
    }
    if (r.personas) setPersonas(r.personas);
    else reload();
  };

  const install = async () => {
    if (!src.trim()) return;
    setBusy(true);
    setMsg(null);
    setConsent(null);
    const r = await installPersona(
      mode === "git" ? { git_url: src.trim() } : { dir: src.trim() },
    );
    setBusy(false);
    if (!r.ok) {
      setMsg(r.error || "install failed");
      return;
    }
    setConsent(r.consent || []);
    if (r.personas) setPersonas(r.personas);
    setMsg(t("settings:personasTab.installed", { count: (r.consent || []).length }));
    setSrc("");
  };

  return (
    <div>
      <p className="text-[12.5px] text-muted mb-3 leading-relaxed">
        {t("settings:personasTab.desc")}
      </p>

      <div className={CARD + " divide-y divide-line mb-6"}>
        {personas.map((p) => (
          <div key={p.id} className="px-4 py-3">
            <div className="flex items-center gap-4">
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium flex items-center gap-1.5">
                <span className="truncate">{p.name}</span>
                {p.default && <span className="text-accent" title={t("settings:personasTab.setDefault")}>&#9733;</span>}
                {p.builtin && <span className="text-[11px] text-faint font-normal">{"\u00b7 "}{t("settings:personasTab.builtIn")}</span>}
              </div>
              <div className="text-[12px] text-muted truncate">{p.tagline}</div>
            </div>
            <label className={CHECK}>
              <input
                type="checkbox"
                checked={p.enabled}
                onChange={(e) =>
                  e.target.checked ? toggle(p.id, { enabled: true }) : requestDisable(p)
                }
              />
              {t("settings:personasTab.enabled")}
            </label>
            <label className={CHECK + (p.enabled ? "" : " opacity-40")}>
              <input
                type="checkbox"
                checked={p.surfaced}
                disabled={!p.enabled}
                onChange={(e) => toggle(p.id, { surfaced: e.target.checked })}
              />
              {t("settings:personasTab.inPicker")}
            </label>
            <button
              className={BTN_BORDERED}
              disabled={p.default || !p.enabled}
              onClick={() => toggle(p.id, { default: true })}
            >
              {t("settings:personasTab.setDefault")}
            </button>
            {onOpenPersona && (
              <button
                className="text-faint hover:text-ink shrink-0 p-1"
                title={"Configure " + p.name}
                aria-label={"Configure " + p.name}
                data-testid={"persona-configure-" + p.id}
                onClick={() => onOpenPersona(p.id)}
              >
                <Icon name="sliders" size={15} />
              </button>
            )}
            {!p.builtin &&
              (confirmDel === p.id ? (
                <span className="flex items-center gap-1.5 shrink-0">
                  <button
                    className="text-[12px] px-2 py-1.5 rounded-lg bg-danger text-white"
                    data-testid={"persona-delete-confirm-" + p.id}
                    onClick={() => remove(p.id)}
                  >
                    {t("common:button.delete")}
                  </button>
                  <button className={BTN_BORDERED} onClick={() => setConfirmDel(null)}>
                    {t("settings:personasTab.keep")}
                  </button>
                </span>
              ) : (
                <button
                  className="text-faint hover:text-danger shrink-0 p-1"
                  title="Delete this persona"
                  aria-label={"Delete " + p.name}
                  data-testid={"persona-delete-" + p.id}
                  onClick={() => setConfirmDel(p.id)}
                >
                  <Icon name="trash" size={14} />
                </button>
              ))}
            </div>
            {confirmOff === p.id && (
              <div
                className="mt-2 flex items-center gap-2.5 text-[12px] text-muted"
                data-testid={"persona-disable-warning-" + p.id}
              >
                <span className="min-w-0">
                  {t("settings:personasTab.disableWarning", { count: liveCount(p.id), plural: liveCount(p.id) === 1 ? "" : "s" })}
                </span>
                <button
                  className="text-[12px] px-2.5 py-1.5 rounded-lg bg-accent text-white shrink-0"
                  data-testid={"persona-disable-confirm-" + p.id}
                  onClick={() => {
                    setConfirmOff(null);
                    toggle(p.id, { enabled: false });
                  }}
                >
                  {t("settings:personasTab.disable")}
                </button>
                <button className={BTN_BORDERED} onClick={() => setConfirmOff(null)}>
                  {t("settings:personasTab.keepEnabled")}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className={SEC_H + " mb-1.5"}>{t("settings:personasTab.addPersonas")}</div>
      <p className="text-[12px] text-muted mb-3 leading-relaxed">
        {t("settings:personasTab.addDesc")}
      </p>
      <div className="flex items-center gap-2">
        <select className={SELECT} value={mode} onChange={(e) => setMode(e.target.value as "git" | "dir")}>
          <option value="git">{t("settings:personasTab.githubUrl")}</option>
          <option value="dir">{t("settings:personasTab.localDir")}</option>
        </select>
        <input
          className={INPUT}
          placeholder={mode === "git" ? "https://github.com/acme/ops-persona" : "/path/to/personas"}
          value={src}
          onChange={(e) => setSrc(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && install()}
        />
        <button className={BTN_ACCENT} disabled={busy || !src.trim()} onClick={install}>
          {busy ? t("settings:personasTab.installing") : t("common:button.install")}
        </button>
      </div>
      {msg && <div className="text-[12.5px] text-muted mt-2.5">{msg}</div>}

      {consent && consent.length > 0 && (
        <div className="mt-4 space-y-2">
          {consent.map((c) => (
            <div key={c.id} className={CARD + " p-3.5"}>
              <div className="text-[13.5px] font-medium">{c.name}</div>
              <div className="text-[12px] text-muted mt-0.5 mb-2">{c.description}</div>
              <div className="text-[12px] text-ink">{t("settings:gallery.toolsLabel")}{c.tools.join(", ") || "\u2014"}</div>
              <div className="text-[12px] text-ink">
                {t("settings:gallery.riskLabel")}{c.risk.join(", ") || "read"}
                {c.connectors ? " \u00b7 connectors" : ""}
                {c.messaging ? t("settings:gallery.canUseMessaging") : ""}
                {c.mcp.length ? " \u00b7 mcp: " + c.mcp.join(", ") : ""}
              </div>
              <div className="text-[12px] text-faint mt-1">
                {t("settings:personasTab.recommendedMode", { mode: c.recommended_mode })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
