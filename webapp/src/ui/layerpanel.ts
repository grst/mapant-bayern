import Control from 'ol/control/Control';
import type BaseLayer from 'ol/layer/Base';
import type {Key} from '../i18n/en';
import type {LayerCode} from '../urlstate';
import {controlButton, element, i18nText} from './dom';

export interface LayerToggle {
  code: LayerCode;
  labelKey: Key;
  layer: BaseLayer;
}

/**
 * The "Layers" control: a map-anchored button opening a checkbox list. Anchored
 * to the map rather than the navbar so it behaves the same on phone and desktop.
 */
export function createLayerPanel(toggles: LayerToggle[], onChange: () => void, target: HTMLElement): Control {
  const container = element('div', 'ol-control layer-panel');
  const button = controlButton('layers', 'layers.toggle');
  const panel = element('div', 'layer-panel-body');
  panel.hidden = true;
  panel.append(i18nText('h2', 'layers.title'));

  for (const {code, labelKey, layer} of toggles) {
    const label = element('label');
    const checkbox = element('input');
    checkbox.type = 'checkbox';
    checkbox.checked = layer.getVisible();
    checkbox.dataset.layer = code;
    checkbox.addEventListener('change', () => {
      layer.setVisible(checkbox.checked);
      onChange();
    });
    // Keeps the checkbox honest if the layer is switched from elsewhere.
    layer.on('change:visible', () => (checkbox.checked = layer.getVisible()));
    label.append(checkbox, i18nText('span', labelKey));
    panel.append(label);
  }

  const setOpen = (open: boolean) => {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
  };
  setOpen(false);
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    setOpen(panel.hidden);
  });
  document.addEventListener('click', (event) => {
    if (!panel.hidden && event.target instanceof Node && !container.contains(event.target)) {
      setOpen(false);
    }
  });

  container.append(button, panel);
  return new Control({element: container, target});
}
