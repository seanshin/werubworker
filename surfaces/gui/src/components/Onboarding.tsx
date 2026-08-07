import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getConnectors,
  setOnboarded,
  type Connector,
} from "../api";
import { ConnectorBadge } from "../connectors/ConnectorIcon";
import { ProviderCards, ProviderForm, useProviderSetup } from "../providers/ProviderSetup";

// First-run onboarding (UX-DECISIONS §24 → §29 → §39): model → your tools → go.
// §39 (owner design, 2026-07-18): step 1 is a PROVIDER GALLERY — 13 real brand
// marks, two per row, each card wearing its own state — and step 2 is a
// two-state tools page whose post-sign-in body is a mini connector gallery with
// live one-click connects. Both steps share one frame rule: the header and
// footer never move; only the middle region swaps, at a fixed height.
// The gallery/form themselves live in providers/ProviderSetup.tsx, shared with
// Settings ▸ Models (UX-021) so the two surfaces can't drift.
// Replayable from Settings ▸ General ▸ "Run setup again".

// Step 2's benefit rows (§41): managed connectors with LIVE prod OAuth apps only,
// each framed by the job it does (detail copy stays ONE line even with a Connect
// pill — wrap made rows jump between states). gmail + google_calendar ship as one
// combined grayed "Coming soon" row — both ride the same Google app, gated on
// Google verification/CASA; give them rows when it lands.
const TOOL_ROWS = [
  { name: "outlook", benefit: "Stay on top of email", detail: "Outlook — triage mail, draft replies, run your calendar." },
  { name: "slack", benefit: "Keep up with Slack", detail: "Slack — catch up, answer mentions, post updates." },
  { name: "github", benefit: "Ship code", detail: "GitHub — review PRs, watch issues, reply to @mentions." },
  { name: "notion", benefit: "Keep your notes in reach", detail: "Notion — search pages, query databases, draft docs." },
  { name: "hubspot", benefit: "Keep the CRM current", detail: "HubSpot — update deals, log notes, prep calls." },
  { name: "attio", benefit: "Track every relationship", detail: "Attio — search records, read timelines, log notes." },
];
// const TOOLS_SOON = ["gmail", "google_calendar"]; // reserved for future use

export function Onboarding({ onDone }: { onDone: (next?: "work" | "gallery" | "automations") => void }) {
  const { t } = useTranslation(["settings", "common"]);
  const [step, setStep] = useState(0);

  // -- step 1: model (provider gallery ⇄ key form, shared machinery) ---------------
  const ps = useProviderSetup();
  const [skipConfirm, setSkipConfirm] = useState(false);

  const anyReady =
    ps.providers.some((p) => p.configured && p.needs_key) || ps.keylessOk.size > 0;
  // In the form with typed-but-untested input, Next verifies+saves first (tester
  // catch 2026-07-12: a manual Test-then-Continue two-step reads as a puzzle).
  const nextFromForm = !!ps.sel && ps.dirty && ps.secretFilled;
  const canNext = anyReady || nextFromForm;

  const advance = async () => {
    if (nextFromForm && !ps.credentialed) {
      ps.cancelBackTimer();
      if (!(await ps.runTestAndSave())) return;
    }
    setStep(1);
  };

  // -- step 2: connect your everyday tools (manual only) -------------------
  const [connectors, setConnectors] = useState<Connector[]>([]);

  // Load connectors once when entering the tools page.
  useEffect(() => {
    if (step !== 1) return;
    getConnectors().then(setConnectors).catch(() => {});
    const interval = setInterval(() => {
      getConnectors().then(setConnectors).catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, [step]);

  const finish = async (next?: "work" | "gallery" | "automations") => {
    await setOnboarded(true).catch(() => {});
    onDone(next);
  };

  // -- shared bits ----------------------------------------------------------------
  const dots = (
    <div className="flex justify-center gap-2 mb-6">
      {[0, 1, 2].map((i) => (
        <span key={i} className={"w-1.5 h-1.5 rounded-full " + (i <= step ? "bg-accent" : "bg-line")} />
      ))}
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 bg-ink/30 grid place-items-center" data-testid="onboarding">
      {/* FIXED height across all three steps (owner call 2026-07-12, reaffirmed §39: the
          modal must never resize — the gallery⇄form swap happens inside this box). */}
      <div className="w-[600px] max-w-[92vw] h-[560px] max-h-[88vh] rounded-2xl border border-line bg-panel shadow-2xl p-8 flex flex-col">
        {dots}

        {step === 0 && (
          <section data-testid="ob-step-model" className="flex-1 min-h-0 flex flex-col">
            {/* Persistent header — stays put while the region below swaps (§39). */}
            <h1 className="text-[19px] font-semibold">{t("settings:onboarding.welcome")}<span className="beta-tag">BETA</span></h1>
            <p className="text-[13px] text-muted mt-0.5 mb-4">
              {t("settings:onboarding.setupDesc")}
            </p>

            {!ps.sel ? (
              /* ---- the provider GALLERY ---- */
              <div className="flex-1 min-h-0 overflow-y-auto pr-1" data-testid="ob-provider-gallery">
                <ProviderCards ps={ps} tp="ob" />
              </div>
            ) : (
              /* ---- one provider's key form, same box ---- */
              <div className="flex-1 min-h-0 overflow-y-auto pr-1">
                <ProviderForm ps={ps} tp="ob" />
              </div>
            )}

            {/* Persistent footer (§39). */}
            <div className="flex items-center gap-3 pt-5">
              {!skipConfirm ? (
                <button className="text-[12.5px] text-faint hover:text-muted" onClick={() => setSkipConfirm(true)}>
                  {t("settings:onboarding.skipSetup")}
                </button>
              ) : (
                <span className="text-[12.5px] text-muted">
                  {t("settings:onboarding.skipWarning")}{" "}
                  <button className="text-accent" onClick={() => finish()}>
                    {t("settings:onboarding.skipAnyway")}
                  </button>
                </span>
              )}
              <button
                className="ml-auto px-6 py-2 rounded-full bg-ink text-panel text-[13px] disabled:opacity-40"
                disabled={!canNext || ps.verify.state === "testing"}
                onClick={advance}
                data-testid="ob-continue"
              >
                {ps.verify.state === "testing" ? t("settings:onboarding.checking") : t("common:button.next")}
              </button>
            </div>
            <p className="text-[11px] text-faint mt-3">
              {t("settings:onboarding.modelsNote")}
            </p>
          </section>
        )}

        {step === 1 && (
          <section data-testid="ob-step-tools" className="flex-1 min-h-0 flex flex-col">
            <h1 className="text-[19px] font-semibold">{t("settings:onboarding.connectTools")}</h1>
            <p className="text-[13px] text-muted mt-0.5 mb-3">
              {t("settings:onboarding.connectToolsDesc")}
            </p>

            <div className="flex-1 min-h-0 overflow-y-auto pr-1" data-testid="ob-tool-gallery">
              {TOOL_ROWS.map(({ name, benefit, detail }) => {
                const c = connectors.find((x) => x.name === name);
                if (!c) return null;
                return (
                  <div
                    key={name}
                    className="flex items-center gap-3 py-2 border-b border-paper last:border-0"
                    data-testid={`ob-tool-${name}`}
                  >
                    <ConnectorBadge connector={c} size={34} title={c.title} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-semibold leading-tight">{benefit}</span>
                      <span className="block text-[12px] text-muted truncate">{detail}</span>
                    </span>
                    {c.connected && (
                      <span className="text-[12px] text-ok font-medium shrink-0">{t("settings:onboarding.connected")}</span>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="mt-3.5 rounded-xl border border-line bg-paper px-4 py-3 shrink-0">
              <span className="block text-[13px] font-semibold text-ink mb-0.5">
                Connect your tools manually
              </span>
              <span className="block text-[12.5px] text-muted leading-snug">
                Head to Settings &gt; Connectors after setup to add tokens for Slack, GitHub, and more.
              </span>
            </div>

            <div className="flex items-center mt-3.5">
              <button
                className="ml-auto px-6 py-2 rounded-full bg-ink text-panel text-[13px] shrink-0"
                onClick={() => setStep(2)}
                data-testid="ob-continue-tools"
              >
                {t("common:button.next")}
              </button>
            </div>
            <p className="text-[11px] text-faint mt-3">
              {t("settings:onboarding.moreTools")}
            </p>
          </section>
        )}

        {step === 2 && (
          <section data-testid="ob-step-done" className="flex-1 min-h-0 flex flex-col overflow-y-auto">
            <div className="text-center">
              <div className="w-12 h-12 rounded-full bg-okSoft text-ok grid place-items-center mx-auto mb-3 text-[22px]">
                ✓
              </div>
              <h1 className="text-[19px] font-semibold mb-1">{t("settings:onboarding.youreSetUp")}</h1>
              <p className="text-[13px] text-muted mb-5">{t("settings:onboarding.twoWaysToStart")}</p>
            </div>

            <button
              className="w-full flex items-start gap-3 rounded-xl2 border border-line hover:border-accent bg-panel px-4 py-3.5"
              onClick={() => finish("automations")}
              data-testid="ob-cta-automation"
            >
              <span className="w-9 h-9 rounded-lg bg-accentSoft text-accent grid place-items-center text-[15px] shrink-0">
                ◷
              </span>
              <span className="flex-1 min-w-0 text-left">
                <b className="block text-[13.5px]">{t("settings:onboarding.createFirstAutomation")}</b>
                <span className="text-[12px] text-muted">
                  {t("settings:onboarding.automationDesc")}
                </span>
              </span>
              <span className="text-faint self-center">›</span>
            </button>
            <button
              className="w-full flex items-start gap-3 rounded-xl2 border border-line hover:border-accent bg-panel px-4 py-3.5 mt-2.5"
              onClick={() => finish("work")}
              data-testid="ob-start"
            >
              <span className="w-9 h-9 rounded-lg bg-accentSoft text-accent grid place-items-center text-[15px] shrink-0">
                ✦
              </span>
              <span className="flex-1 min-w-0 text-left">
                <b className="block text-[13.5px]">{t("settings:onboarding.startWorking")}</b>
                <span className="text-[12px] text-muted">
                  {t("settings:onboarding.startWorkingDesc")}
                </span>
              </span>
              <span className="text-faint self-center">›</span>
            </button>

            {/* The Specialist-coworkers gallery card and the per-session-scope line stay HIDDEN
                (owner call 2026-07-12); the finish("gallery") plumbing remains for their return. */}

            <p className="text-[11px] text-faint text-center mt-auto pt-5">
              {t("settings:onboarding.replaySetup")}
            </p>
          </section>
        )}
      </div>
    </div>
  );
}
