/**
 * The open/close behaviour of the map's panels (layers, PDF, OCD): a button toggles its panel, a
 * click elsewhere closes it, and opening one closes whichever other was open -- they open in the
 * same place, and the PDF and OCD panels each show their own print rectangle.
 */

const closers = new Set<() => void>();

export function popover(
  container: HTMLElement,
  button: HTMLElement,
  panel: HTMLElement,
  /** Called after every change, with whether the panel is now open. */
  onToggle?: (open: boolean) => void,
): void {
  const setOpen = (open: boolean) => {
    if (open === !panel.hidden) {
      return;
    }
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    onToggle?.(open);
  };
  const close = () => setOpen(false);
  closers.add(close);

  panel.hidden = true;
  button.setAttribute('aria-expanded', 'false');
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    if (panel.hidden) {
      closers.forEach((other) => other !== close && other());
      setOpen(true);
    } else {
      setOpen(false);
    }
  });
  document.addEventListener('click', (event) => {
    if (!panel.hidden && event.target instanceof Node && !container.contains(event.target)) {
      setOpen(false);
    }
  });
}
