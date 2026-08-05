import {getLang, isLang, onLangChange, setLang, t} from '../i18n';

/** Navbar behaviour shared by the map and about pages: drawer plus language switch. */
export function initNavbar(): void {
  const toggle = document.getElementById('nav-toggle');
  const nav = document.getElementById('site-nav');
  const backdrop = document.getElementById('nav-backdrop');

  const setOpen = (open: boolean) => {
    nav?.classList.toggle('open', open);
    if (toggle) {
      toggle.setAttribute('aria-expanded', String(open));
      // Keeps the label in step with what the button now does, in both languages.
      toggle.dataset.i18nLabel = open ? 'nav.close' : 'nav.menu';
      toggle.setAttribute('aria-label', t(open ? 'nav.close' : 'nav.menu'));
    }
    if (backdrop) {
      backdrop.hidden = !open;
    }
  };

  toggle?.addEventListener('click', () => setOpen(nav?.classList.contains('open') !== true));
  backdrop?.addEventListener('click', () => setOpen(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      setOpen(false);
    }
  });
  // Following a link inside the drawer should not leave it open behind the new page.
  nav?.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setOpen(false)));

  const buttons = document.querySelectorAll<HTMLButtonElement>('#lang-switch button[data-lang]');
  buttons.forEach((button) =>
    button.addEventListener('click', () => {
      const lang = button.dataset.lang;
      if (isLang(lang)) {
        setLang(lang);
      }
    }),
  );

  const markActive = () =>
    buttons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.lang === getLang())));
  onLangChange(() => {
    markActive();
    syncInternalLinks();
  });
  markActive();
  syncInternalLinks();
}

/**
 * The chosen language lives in the URL only, so links between the map and the
 * about page have to carry it – otherwise the other page falls back to the
 * browser's language. Idempotent: only the hash is replaced.
 */
function syncInternalLinks(): void {
  document.querySelectorAll<HTMLAnchorElement>('a[data-keep-lang]').forEach((link) => {
    const url = new URL(link.href);
    url.hash = `lang=${getLang()}`;
    link.href = url.toString();
  });
}
