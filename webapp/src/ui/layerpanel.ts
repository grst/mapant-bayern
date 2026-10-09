import type {Key} from '../i18n/en';
import type {LayerCode} from '../urlstate';
import {controlButton, element, i18nText} from './dom';
import {popover} from './popover';

export interface LayerToggle {
  code: LayerCode;
  labelKey: Key;
  isVisible(): boolean;
  setVisible(visible: boolean): void;
}

/**
 * The "Layers" control: a map-anchored button opening a checkbox list. Anchored
 * to the map rather than the navbar so it behaves the same on phone and desktop.
 */
export function createLayerPanel(
  toggles: LayerToggle[],
  onChange: () => void,
  /** Registers a callback for visibility changes made from elsewhere, e.g. a pasted link. */
  onVisibilityChange: (listener: () => void) => void,
): HTMLElement {
  const container = element('div', 'maplibregl-ctrl maplibregl-ctrl-group layer-panel');
  const button = controlButton('layers', 'layers.toggle');
  const panel = element('div', 'layer-panel-body');
  panel.append(i18nText('h2', 'layers.title'));

  for (const toggle of toggles) {
    const {code, labelKey} = toggle;
    const label = element('label');
    const checkbox = element('input');
    checkbox.type = 'checkbox';
    checkbox.checked = toggle.isVisible();
    checkbox.dataset.layer = code;
    checkbox.addEventListener('change', () => {
      toggle.setVisible(checkbox.checked);
      onChange();
    });
    // Keeps the checkbox honest if the layer is switched from elsewhere.
    onVisibilityChange(() => (checkbox.checked = toggle.isVisible()));
    label.append(checkbox, i18nText('span', labelKey));
    panel.append(label);
  }

  popover(container, button, panel);
  container.append(button, panel);
  return container;
}
