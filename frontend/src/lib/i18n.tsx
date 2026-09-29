import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { en } from "./i18n.en";
import { fr } from "./i18n.fr";

export type Language = "en" | "fr";

const STORAGE_KEY = "sonalim-erp.language";

export type TranslationKey = keyof typeof en;

const dictionaries: Record<Language, Record<TranslationKey, string>> = { en, fr };

interface I18nContextValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: TranslationKey) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

/** The language the user picked, readable outside React (the API client uses it for error text). */
export function readStoredLanguage(): Language {
  try {
    // French is the plant's working language, so it is the default until the
    // user picks otherwise; a saved choice always wins.
    return localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "fr";
  } catch {
    return "fr";
  }
}

/**
 * The BCP-47 locale for `Intl.NumberFormat`/`toLocaleString`, matching the
 * app's own language toggle rather than the browser's OS locale.
 *
 * French and English disagree on what a comma *means* in a number — French
 * reads it as the decimal separator, English as the thousands separator — so
 * a number formatted with the wrong one is not just cosmetically off, it is
 * read as a different value. `Intl.NumberFormat(undefined, ...)` follows
 * whatever locale the browser happens to be configured with, which routinely
 * disagrees with the language the user picked in the app; this is the one
 * place that decision is made, for every number formatter to share.
 */
export function currentLocale(): string {
  return readStoredLanguage() === "fr" ? "fr-FR" : "en-US";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => readStoredLanguage());

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, language);
    } catch {
      // private browsing / storage blocked — language just won't persist
    }
    document.documentElement.lang = language;
  }, [language]);

  const value = useMemo<I18nContextValue>(
    () => ({
      language,
      setLanguage,
      t: (key: TranslationKey) => dictionaries[language][key] ?? en[key] ?? key,
    }),
    [language],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return context;
}
