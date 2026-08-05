import {de} from './i18n/de';
import {en, type Key} from './i18n/en';

export type Lang = 'de' | 'en';
export const LANGS: Lang[] = ['de', 'en'];

const tables: Record<Lang, Record<Key, string>> = {de, en};
const listeners = new Set<(lang: Lang) => void>();

let current: Lang = 'en';

export function isLang(value: unknown): value is Lang {
  return value === 'de' || value === 'en';
}

/** Browser preference, used when the URL does not pin a language. */
export function detectLang(): Lang {
  return navigator.languages?.some((l) => l.toLowerCase().startsWith('de')) ||
    navigator.language?.toLowerCase().startsWith('de')
    ? 'de'
    : 'en';
}

export function getLang(): Lang {
  return current;
}

/** Idempotent: also used on startup to translate the initial markup. */
export function setLang(lang: Lang): void {
  current = lang;
  document.documentElement.lang = lang;
  applyTranslations();
  listeners.forEach((listener) => listener(lang));
}

export function onLangChange(listener: (lang: Lang) => void): void {
  listeners.add(listener);
}

export function t(key: Key): string {
  return tables[current][key] || en[key];
}

/** Number formatting follows the active language (1.234,5 vs 1,234.5). */
export function formatNumber(value: number, digits = 0): string {
  return new Intl.NumberFormat(current, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

function isKey(value: string): value is Key {
  return value in en;
}

/**
 * Fills every element carrying a `data-i18n*` attribute:
 *   data-i18n           -> textContent (also covers <title>, i.e. the document title)
 *   data-i18n-html      -> innerHTML (for strings containing links)
 *   data-i18n-title     -> title attribute
 *   data-i18n-label     -> aria-label attribute
 */
export function applyTranslations(root: ParentNode = document): void {
  const assign = (attribute: string, apply: (el: HTMLElement, text: string) => void) => {
    root.querySelectorAll<HTMLElement>(`[${attribute}]`).forEach((el) => {
      const key = el.getAttribute(attribute);
      if (key && isKey(key)) {
        apply(el, t(key));
      }
    });
  };
  assign('data-i18n', (el, text) => (el.textContent = text));
  assign('data-i18n-html', (el, text) => (el.innerHTML = text));
  assign('data-i18n-title', (el, text) => el.setAttribute('title', text));
  assign('data-i18n-label', (el, text) => el.setAttribute('aria-label', text));
}
