import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enCommon from "./locales/en/common.json";
import enSession from "./locales/en/session.json";
import enSettings from "./locales/en/settings.json";
import enHumanize from "./locales/en/humanize.json";
import enSkills from "./locales/en/skills.json";
import enConnectors from "./locales/en/connectors.json";
import enAuth from "./locales/en/auth.json";

import koCommon from "./locales/ko/common.json";
import koSession from "./locales/ko/session.json";
import koSettings from "./locales/ko/settings.json";
import koHumanize from "./locales/ko/humanize.json";
import koSkills from "./locales/ko/skills.json";
import koConnectors from "./locales/ko/connectors.json";
import koAuth from "./locales/ko/auth.json";

const LANGUAGE_KEY = "openworker-language";

i18n.use(initReactI18next).init({
  resources: {
    en: {
      common: enCommon,
      session: enSession,
      settings: enSettings,
      humanize: enHumanize,
      skills: enSkills,
      connectors: enConnectors,
      auth: enAuth,
    },
    ko: {
      common: koCommon,
      session: koSession,
      settings: koSettings,
      humanize: koHumanize,
      skills: koSkills,
      connectors: koConnectors,
      auth: koAuth,
    },
  },
  lng: localStorage.getItem(LANGUAGE_KEY) || "ko",
  fallbackLng: "en",
  ns: ["common", "session", "settings", "humanize", "skills", "connectors", "auth"],
  defaultNS: "common",
  interpolation: { escapeValue: false },
});

export { LANGUAGE_KEY };
export default i18n;
