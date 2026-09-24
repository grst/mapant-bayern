import Control from 'ol/control/Control';
import {formatNumber, onLangChange, t} from '../i18n';
import {printGroundSize, SCALES, type Orientation} from '../print';
import {controlButton, element, i18nText} from './dom';

export interface PrintSettings {
  scale: number;
  orientation: Orientation;
}

export interface PrintPanelOptions {
  /** Called with the current settings while the panel is open, null when closed. */
  onSettingsChange(settings: PrintSettings | null): void;
  onExport(settings: PrintSettings): Promise<void>;
  /** The same area as an editable OCAD file, for someone who wants to survey from it. */
  onExportOcd(settings: PrintSettings): Promise<void>;
}

const ORIENTATIONS: {value: Orientation; labelKey: 'print.portrait' | 'print.landscape'}[] = [
  {value: 'portrait', labelKey: 'print.portrait'},
  {value: 'landscape', labelKey: 'print.landscape'},
];

/** Scale and paper format for the PDF export, plus the export button itself. */
export function createPrintPanel(options: PrintPanelOptions, target: HTMLElement): Control {
  const settings: PrintSettings = {scale: 10000, orientation: 'portrait'};

  const container = element('div', 'ol-control print-panel');
  const button = controlButton('print', 'print.toggle');
  const panel = element('div', 'print-panel-body');
  panel.hidden = true;
  panel.append(i18nText('h2', 'print.title'));

  const scaleLabel = element('label', 'print-field');
  scaleLabel.append(i18nText('span', 'print.scale'));
  const scaleSelect = element('select');
  for (const scale of SCALES) {
    const option = element('option');
    option.value = String(scale);
    // Written without a thousands separator so it reads the same in both languages.
    option.textContent = `1:${scale}`;
    option.selected = scale === settings.scale;
    scaleSelect.append(option);
  }
  scaleLabel.append(scaleSelect);
  panel.append(scaleLabel);

  const orientationField = element('div', 'print-field');
  orientationField.append(i18nText('span', 'print.orientation'));
  const orientationGroup = element('div', 'print-orientation');
  const orientationButtons = ORIENTATIONS.map(({value, labelKey}) => {
    const orientationButton = i18nText('button', labelKey);
    orientationButton.type = 'button';
    orientationButton.dataset.orientation = value;
    orientationButton.addEventListener('click', () => {
      settings.orientation = value;
      refresh();
      notify();
    });
    orientationGroup.append(orientationButton);
    return orientationButton;
  });
  orientationField.append(orientationGroup);
  panel.append(orientationField);

  const area = element('p', 'print-area');
  panel.append(area);
  panel.append(i18nText('p', 'print.hint', 'print-hint'));

  const exportButton = i18nText('button', 'print.export', 'print-export');
  exportButton.type = 'button';
  panel.append(exportButton);

  const ocdButton = i18nText('button', 'print.exportOcd', 'print-export-ocd');
  ocdButton.type = 'button';
  panel.append(ocdButton);
  panel.append(i18nText('p', 'print.ocdHint', 'print-hint'));

  function refresh(): void {
    orientationButtons.forEach((orientationButton) =>
      orientationButton.setAttribute(
        'aria-pressed',
        String(orientationButton.dataset.orientation === settings.orientation),
      ),
    );
    const [width, height] = printGroundSize(settings.scale, settings.orientation);
    area.textContent = `${t('print.area')} ${formatNumber(width / 1000, 1)} × ${formatNumber(height / 1000, 1)} km`;
  }

  function notify(): void {
    options.onSettingsChange(panel.hidden ? null : {...settings});
  }

  scaleSelect.addEventListener('change', () => {
    settings.scale = Number(scaleSelect.value);
    refresh();
    notify();
  });

  // Both exports do their heavy lifting on the main thread in places, so the busy label has to be
  // given a frame to paint before it starts.
  function wireExport(
    button: HTMLElement & {disabled: boolean},
    busyKey: 'print.busy' | 'print.ocdBusy',
    labelKey: 'print.export' | 'print.exportOcd',
    run: (settings: PrintSettings) => Promise<void>,
  ): void {
    button.addEventListener('click', async () => {
      button.disabled = true;
      button.textContent = t(busyKey);
      await new Promise((resolve) => requestAnimationFrame(resolve));
      try {
        await run({...settings});
      } finally {
        button.disabled = false;
        button.textContent = t(labelKey);
      }
    });
  }

  wireExport(exportButton, 'print.busy', 'print.export', options.onExport);
  wireExport(ocdButton, 'print.ocdBusy', 'print.exportOcd', options.onExportOcd);

  const setOpen = (open: boolean) => {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    notify();
  };
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    setOpen(panel.hidden);
  });
  document.addEventListener('click', (event) => {
    if (!panel.hidden && event.target instanceof Node && !container.contains(event.target)) {
      setOpen(false);
    }
  });

  onLangChange(refresh);
  refresh();
  setOpen(false);

  container.append(button, panel);
  return new Control({element: container, target});
}
