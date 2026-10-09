import {formatNumber, onLangChange, t} from '../i18n';
import type {Key} from '../i18n/en';
import {printGroundSize, SCALES, type Orientation} from '../print';
import {controlButton, element, i18nText, type IconName} from './dom';
import {popover} from './popover';

export interface PrintSettings {
  scale: number;
  orientation: Orientation;
}

export interface ExportPanelOptions {
  /** Class of the control, besides `print-panel`. */
  className: string;
  icon: IconName;
  /** The button's tooltip and the panel's title. */
  titleKey: Key;
  /** What the rectangle on the map stands for. */
  hintKey: Key;
  exportKey: Key;
  busyKey: Key;
  /** Below the button: what the export is for. */
  noteKey?: Key;
  /** Fields of the export's own, between the page settings and the button. */
  extra?: HTMLElement[];
  /** Called with the current settings while the panel is open, null when closed. */
  onSettingsChange(settings: PrintSettings | null): void;
  onExport(settings: PrintSettings): Promise<void>;
}

const ORIENTATIONS: {value: Orientation; labelKey: 'print.portrait' | 'print.landscape'}[] = [
  {value: 'portrait', labelKey: 'print.portrait'},
  {value: 'landscape', labelKey: 'print.landscape'},
];

/**
 * A panel exporting the area of an A4 page: scale and paper format, the ground they cover, and
 * the export button. The PDF and the OCD export are both one.
 */
export function createExportPanel(options: ExportPanelOptions): HTMLElement {
  const settings: PrintSettings = {scale: 10000, orientation: 'portrait'};

  const container = element('div', `maplibregl-ctrl maplibregl-ctrl-group print-panel ${options.className}`);
  const button = controlButton(options.icon, options.titleKey);
  const panel = element('div', 'print-panel-body');
  panel.append(i18nText('h2', options.titleKey));

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
  panel.append(i18nText('p', options.hintKey, 'print-hint'));
  panel.append(...(options.extra ?? []));

  const exportButton = i18nText('button', options.exportKey, 'print-export');
  exportButton.type = 'button';
  panel.append(exportButton);
  if (options.noteKey) {
    panel.append(i18nText('p', options.noteKey, 'print-hint'));
  }

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
  exportButton.addEventListener('click', async () => {
    exportButton.disabled = true;
    exportButton.textContent = t(options.busyKey);
    exportButton.dataset.i18n = options.busyKey;
    await new Promise((resolve) => requestAnimationFrame(resolve));
    try {
      await options.onExport({...settings});
    } finally {
      exportButton.disabled = false;
      exportButton.textContent = t(options.exportKey);
      exportButton.dataset.i18n = options.exportKey;
    }
  });

  popover(container, button, panel, notify);

  onLangChange(refresh);
  refresh();

  container.append(button, panel);
  return container;
}

/** The PDF export. */
export function createPrintPanel(
  options: Pick<ExportPanelOptions, 'onSettingsChange' | 'onExport'>,
): HTMLElement {
  return createExportPanel({
    ...options,
    className: 'pdf-panel',
    icon: 'print',
    titleKey: 'print.title',
    hintKey: 'print.hint',
    exportKey: 'print.export',
    busyKey: 'print.busy',
  });
}
