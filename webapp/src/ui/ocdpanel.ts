import {FEATURE_GROUPS, type FeatureGroup} from '../vector/groups';
import {element, i18nText} from './dom';
import {createExportPanel, type ExportPanelOptions, type PrintSettings} from './printpanel';

export interface OcdSettings extends PrintSettings {
  /** The groups written as objects. */
  objects: Set<FeatureGroup>;
  /** The groups drawn into a background map; empty for none. */
  background: Set<FeatureGroup>;
}

export interface OcdPanelOptions {
  onSettingsChange: ExportPanelOptions['onSettingsChange'];
  onExport(settings: OcdSettings): Promise<void>;
}

/**
 * The feature groups as checkboxes, under a heading per origin: what karttapullautin derived from
 * the LiDAR, and what came from OpenStreetMap.
 */
function groupChoice(kind: 'objects' | 'background', checked: boolean): {fields: HTMLElement; selected(): Set<FeatureGroup>} {
  const fields = element('div', 'ocd-groups');
  const boxes = new Map<FeatureGroup, HTMLInputElement>();
  for (const origin of ['lidar', 'osm'] as const) {
    fields.append(i18nText('h3', origin === 'lidar' ? 'ocd.fromLidar' : 'ocd.fromOsm'));
    for (const group of FEATURE_GROUPS.filter((g) => g.origin === origin)) {
      const label = element('label');
      const checkbox = element('input');
      checkbox.type = 'checkbox';
      checkbox.checked = checked;
      checkbox.dataset[kind] = group.id;
      boxes.set(group.id, checkbox);
      label.append(checkbox, i18nText('span', group.labelKey));
      fields.append(label);
    }
  }
  return {
    fields,
    selected: () => new Set([...boxes].filter(([, box]) => box.checked).map(([group]) => group)),
  };
}

/**
 * The OCD export: the page settings of the PDF, which features to write as objects (all, to
 * begin with), and -- in a section of its own, closed and empty to begin with -- which to draw
 * into a background map instead or as well.
 */
export function createOcdPanel(options: OcdPanelOptions): HTMLElement {
  const objects = groupChoice('objects', true);
  const objectsField = element('fieldset', 'ocd-field');
  objectsField.append(i18nText('legend', 'ocd.features'), objects.fields);

  const background = groupChoice('background', false);
  const backgroundField = element('details', 'ocd-field ocd-background');
  backgroundField.append(i18nText('summary', 'ocd.background'), i18nText('p', 'ocd.backgroundHint', 'print-hint'), background.fields);

  return createExportPanel({
    className: 'ocd-panel',
    icon: 'ocd',
    titleKey: 'ocd.title',
    hintKey: 'ocd.hint',
    exportKey: 'ocd.export',
    busyKey: 'ocd.busy',
    noteKey: 'ocd.note',
    extra: [objectsField, backgroundField],
    onSettingsChange: options.onSettingsChange,
    onExport: (settings) =>
      options.onExport({...settings, objects: objects.selected(), background: background.selected()}),
  });
}
