import {marked} from 'marked';
import './style.css';

// The repository READMEs are the single source of truth for the about text. Vite
// inlines them at build time (?raw), so nothing is fetched at runtime.
import readmeDe from '../../README.de.md?raw';
import readmeEn from '../../README.md?raw';

import {applyTranslations, getLang, onLangChange, setLang, type Lang} from './i18n';
import {initNavbar} from './ui/navbar';
import {readState} from './urlstate';

const READMES: Record<Lang, string> = {de: readmeDe, en: readmeEn};

async function render(): Promise<void> {
  const content = document.getElementById('content');
  if (!content) {
    return;
  }
  content.innerHTML = await marked.parse(READMES[getLang()]);
  // Send outgoing links from the README to a new tab.
  content.querySelectorAll('a[href^="http"]').forEach((link) => {
    link.setAttribute('target', '_blank');
    link.setAttribute('rel', 'noopener');
  });
  // The screenshots are several megabytes, so don't hold up the rest of the page.
  content.querySelectorAll('img').forEach((image) => {
    image.loading = 'lazy';
    image.decoding = 'async';
  });
}

setLang(readState().lang);
initNavbar();
applyTranslations();
onLangChange((lang) => {
  // The language lives in the URL, so a reload or a shared link keeps it.
  history.replaceState(null, '', `#lang=${lang}`);
  void render();
});
await render();
