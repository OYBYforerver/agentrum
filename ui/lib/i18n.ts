import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import en from "../locales/en.json";
import zh from "../locales/zh.json";

const stored = typeof window !== "undefined" ? localStorage.getItem("agentrum-locale") : null;
const lang = stored || "zh";

void i18next.use(initReactI18next).init({
  resources: { en: { translation: en }, zh: { translation: zh } },
  lng: lang,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function setLocale(lang: "zh" | "en") {
  localStorage.setItem("agentrum-locale", lang);
  void i18next.changeLanguage(lang);
}

export default i18next;
