import {marked} from 'marked';
import './style.css';

// The repository README is the single source of truth for the about text. Vite
// inlines it at build time (?raw), so nothing is fetched at runtime. A German
// version can be added later by importing README.de.md and picking by language.
import readme from '../../README.md?raw';

import {applyTranslations, setLang} from './i18n';
import {initNavbar} from './ui/navbar';
import {readState} from './urlstate';

setLang(readState().lang);
initNavbar();
applyTranslations();

const content = document.getElementById('content');
if (content) {
  content.innerHTML = await marked.parse(readme);
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
