import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import en from "../locales/en.json";
import zh from "../locales/zh.json";

export const LOCALE_KEY = "agentregistry-locale";
export type Locale = "zh" | "en";

const stored = typeof window !== "undefined" ? localStorage.getItem(LOCALE_KEY) : null;

// Pick the UI language: stored preference wins; otherwise probe the browser
// (zh* -> zh, everything else -> en). During prerender (no navigator) fall
// back to "zh" so the static export matches the previous default.
const detected: Locale =
  stored === "zh" || stored === "en"
    ? stored
    : typeof navigator !== "undefined"
      ? (navigator.language || "").toLowerCase().startsWith("zh")
        ? "zh"
        : "en"
      : "zh";

function syncDocumentLang(lng: string) {
  if (typeof document !== "undefined") document.documentElement.lang = lng;
}

void i18next.use(initReactI18next).init({
  resources: { en: { translation: en }, zh: { translation: zh } },
  lng: detected,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

if (typeof window !== "undefined") syncDocumentLang(detected);

export function setLocale(lang: Locale) {
  localStorage.setItem(LOCALE_KEY, lang);
  void i18next.changeLanguage(lang);
  syncDocumentLang(lang);
}

export default i18next;
