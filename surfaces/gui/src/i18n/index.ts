import i18n from "i18next";
import { initReactI18next } from "react-i18next";

// Eagerly import English (fallback) — always needed for missing keys.
import enCommon from "./locales/en/common.json";
import enSession from "./locales/en/session.json";
import enSettings from "./locales/en/settings.json";
import enHumanize from "./locales/en/humanize.json";
import enSkills from "./locales/en/skills.json";
import enConnectors from "./locales/en/connectors.json";
import enAuth from "./locales/en/auth.json";

const LANGUAGE_KEY = "openworker-language";
const savedLng = localStorage.getItem(LANGUAGE_KEY) || "ko";

const enResources = {
  common: enCommon,
  session: enSession,
  settings: enSettings,
  humanize: enHumanize,
  skills: enSkills,
  connectors: enConnectors,
  auth: enAuth,
};

// Start with English. If the user's language is different, load it lazily.
i18n.use(initReactI18next).init({
  resources: { en: enResources },
  lng: savedLng === "en" ? "en" : "en", // start EN; switch after lazy load
  fallbackLng: "en",
  ns: ["common", "session", "settings", "humanize", "skills", "connectors", "auth"],
  defaultNS: "common",
  interpolation: { escapeValue: false },
});

// Lazy-load non-English language bundles.
if (savedLng !== "en") {
  (async () => {
    const [common, session, settings, humanize, skills, connectors, auth] =
      await Promise.all([
        import(`./locales/${savedLng}/common.json`),
        import(`./locales/${savedLng}/session.json`),
        import(`./locales/${savedLng}/settings.json`),
        import(`./locales/${savedLng}/humanize.json`),
        import(`./locales/${savedLng}/skills.json`),
        import(`./locales/${savedLng}/connectors.json`),
        import(`./locales/${savedLng}/auth.json`),
      ]);
    i18n.addResourceBundle(savedLng, "common", common.default);
    i18n.addResourceBundle(savedLng, "session", session.default);
    i18n.addResourceBundle(savedLng, "settings", settings.default);
    i18n.addResourceBundle(savedLng, "humanize", humanize.default);
    i18n.addResourceBundle(savedLng, "skills", skills.default);
    i18n.addResourceBundle(savedLng, "connectors", connectors.default);
    i18n.addResourceBundle(savedLng, "auth", auth.default);
    i18n.changeLanguage(savedLng);
  })();
}

export { LANGUAGE_KEY };
export default i18n;
