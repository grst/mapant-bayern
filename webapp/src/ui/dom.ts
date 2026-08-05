import {t} from '../i18n';
import type {Key} from '../i18n/en';

const ICONS = {
  layers:
    '<polygon points="12 3 2 8 12 13 22 8 12 3"/><polyline points="2 12 12 17 22 12"/><polyline points="2 16 12 21 22 16"/>',
  share: '<path d="M15 7h3a5 5 0 0 1 0 10h-3m-6 0H6A5 5 0 0 1 6 7h3"/><line x1="8" y1="12" x2="16" y2="12"/>',
  line: '<line x1="5" y1="19" x2="19" y2="5"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="5" r="2"/>',
  polygon: '<polygon points="12 3 21 9 18 20 6 20 3 9"/>',
  undo: '<polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>',
  trash: '<polyline points="3 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V3h6v3"/>',
} as const;

export type IconName = keyof typeof ICONS;

/** A button styled like OpenLayers' own controls, labelled from the i18n tables. */
export function controlButton(icon: IconName, titleKey: Key): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.innerHTML = `<svg class="control-icon" viewBox="0 0 24 24" aria-hidden="true">${ICONS[icon]}</svg>`;
  button.dataset.i18nTitle = titleKey;
  button.dataset.i18nLabel = titleKey;
  button.title = t(titleKey);
  button.setAttribute('aria-label', t(titleKey));
  return button;
}

export function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (className) {
    el.className = className;
  }
  return el;
}

/** Translated text that keeps its key, so a language switch updates it in place. */
export function i18nText<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  key: Key,
  className?: string,
): HTMLElementTagNameMap[K] {
  const el = element(tag, className);
  el.dataset.i18n = key;
  el.textContent = t(key);
  return el;
}
