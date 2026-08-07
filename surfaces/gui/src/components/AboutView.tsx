import { useTranslation } from "react-i18next";

const CARD = "rounded-xl2 border border-line bg-panel";

export function AboutView() {
  const { t } = useTranslation("settings");

  return (
    <div className="max-w-2xl mx-auto py-8 px-6">
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <div className="w-14 h-14 rounded-2xl bg-accent/10 grid place-items-center text-accent text-2xl font-bold">
          AI
        </div>
        <div>
          <h1 className="text-xl font-bold text-ink">{t("about.title")}</h1>
          <p className="text-[13px] text-muted mt-0.5">{t("about.description")}</p>
        </div>
      </div>

      {/* Version & Info */}
      <div className={CARD + " p-4 mb-4"}>
        <table className="text-[13px] w-full">
          <tbody>
            <tr>
              <td className="text-muted py-1.5 pr-4 w-32">{t("about.version")}</td>
              <td className="text-ink font-medium">0.1.7</td>
            </tr>
            <tr>
              <td className="text-muted py-1.5 pr-4">{t("about.license")}</td>
              <td className="text-ink">{t("about.mit")}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Release Notes */}
      <div className={CARD + " p-4 mb-4"}>
        <h2 className="text-[13px] font-semibold text-ink mb-3">{t("about.releaseNotes")}</h2>
        <div className="text-[12.5px] text-muted space-y-2">
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 rounded-md bg-accent/10 text-accent text-[11px] font-medium">v0.1.7</span>
            <span className="text-faint">2026-08-06</span>
          </div>
          <ul className="list-disc list-inside space-y-1 ml-1">
            <li>{t("about.release_i18n")}</li>
            <li>{t("about.release_refactor")}</li>
            <li>{t("about.release_ollama")}</li>
            <li>{t("about.release_modelRoles")}</li>
            <li>{t("about.release_about")}</li>
          </ul>
        </div>
      </div>

      {/* Key Features */}
      <div className={CARD + " p-4 mb-4"}>
        <h2 className="text-[13px] font-semibold text-ink mb-3">{t("about.features")}</h2>
        <ul className="text-[12.5px] text-muted space-y-2">
          <li className="flex gap-2"><span>🤖</span> {t("about.feature1")}</li>
          <li className="flex gap-2"><span>🔒</span> {t("about.feature2")}</li>
          <li className="flex gap-2"><span>🔗</span> {t("about.feature3")}</li>
          <li className="flex gap-2"><span>⚡</span> {t("about.feature4")}</li>
          <li className="flex gap-2"><span>⏰</span> {t("about.feature5")}</li>
          <li className="flex gap-2"><span>🎤</span> {t("about.feature6")}</li>
        </ul>
      </div>

      {/* Tech Stack */}
      <div className={CARD + " p-4 mb-4"}>
        <h2 className="text-[13px] font-semibold text-ink mb-3">{t("about.techStack")}</h2>
        <table className="text-[12.5px] w-full">
          <tbody>
            <tr>
              <td className="text-muted py-1.5 pr-4 w-32">{t("about.backend")}</td>
              <td className="text-ink">Python 3.10+, FastAPI</td>
            </tr>
            <tr>
              <td className="text-muted py-1.5 pr-4">{t("about.frontend")}</td>
              <td className="text-ink">React 18, TypeScript, Vite, Tailwind CSS</td>
            </tr>
            <tr>
              <td className="text-muted py-1.5 pr-4">{t("about.desktop")}</td>
              <td className="text-ink">Tauri (Rust)</td>
            </tr>
            <tr>
              <td className="text-muted py-1.5 pr-4">{t("about.stt")}</td>
              <td className="text-ink">Whisper-rs (Rust)</td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Privacy */}
      <div className={CARD + " p-4 mb-4"}>
        <h2 className="text-[13px] font-semibold text-ink mb-2">{t("about.privacy")}</h2>
        <p className="text-[12.5px] text-muted">{t("about.privacyDesc")}</p>
      </div>

      {/* License / Based on */}
      <div className={CARD + " p-4 mb-4"}>
        <h2 className="text-[13px] font-semibold text-ink mb-2">{t("about.basedOn")}</h2>
        <p className="text-[12.5px] text-muted">{t("about.basedOnDesc")}</p>
      </div>

      {/* Credits */}
      <div className="text-center text-[12px] text-faint mt-6 mb-4">
        <p>{t("about.creditsDesc")}</p>
      </div>
    </div>
  );
}
