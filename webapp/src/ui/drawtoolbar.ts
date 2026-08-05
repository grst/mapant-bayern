import Control from 'ol/control/Control';
import type {DrawTools} from '../draw';
import type {DrawingType} from '../drawings';
import {controlButton, element, i18nText} from './dom';

/** Measure/draw toolbar: line, polygon, undo, clear. */
export function createDrawToolbar(tools: DrawTools): Control {
  const container = element('div', 'ol-control draw-toolbar');

  const modeButtons = new Map<DrawingType, HTMLButtonElement>([
    ['l', controlButton('line', 'draw.line')],
    ['p', controlButton('polygon', 'draw.polygon')],
  ]);
  modeButtons.forEach((button, mode) => {
    button.addEventListener('click', () => tools.setMode(tools.getMode() === mode ? null : mode));
    container.append(button);
  });

  const undo = controlButton('undo', 'draw.undo');
  undo.addEventListener('click', () => tools.undo());
  const clear = controlButton('trash', 'draw.clear');
  clear.addEventListener('click', () => tools.clear());
  container.append(undo, clear);

  const hint = i18nText('span', 'draw.hint', 'draw-hint');
  hint.hidden = true;
  container.append(hint);

  tools.onModeChange((mode) => {
    modeButtons.forEach((button, buttonMode) =>
      button.setAttribute('aria-pressed', String(buttonMode === mode)),
    );
    hint.hidden = mode === null;
  });

  return new Control({element: container});
}
