import './style.css';
// Bundles maplibre-gl.css together with the app's overrides of it.
import './map.css';

import {createDrawTools} from './draw';
import {fromLonLat} from './geo';
import {applyTranslations, getLang, onLangChange, setLang, t} from './i18n';
import {
  attributionText,
  MAP_MIN_ZOOM,
  STATE_LABEL_LAYER,
  stateLabelText,
  type OptionalLayer,
  type Visibility,
} from './layers';
import {prefetchArchives} from './archive';
import {createMap, domControl} from './map';
import {OCD_TEMPLATE_URL} from './ocd/config';
import {readState, writeState, type AppState, type LayerCode} from './urlstate';
import {createDrawToolbar} from './ui/drawtoolbar';
import {initZoomHint} from './ui/hint';
import {createLayerPanel, type LayerToggle} from './ui/layerpanel';
import {initNavbar} from './ui/navbar';
import {createOcdPanel} from './ui/ocdpanel';
import {createPrintPanel, type PrintSettings} from './ui/printpanel';
import {createPrintPreview} from './ui/printpreview';
import {createShareControl} from './ui/share';
import {showToast} from './ui/toast';
import {crsAt} from './states';
import {archiveSource} from './vector/source';

/** The layers the share link can switch, by their code in it. */
const LAYER_BY_CODE: Record<LayerCode, OptionalLayer> = {
  h: 'hillshade',
  l: 'places',
  p: 'private',
  c: 'cliffs',
};

function visibilityOf(codes: Set<LayerCode>): Visibility {
  return {hillshade: codes.has('h'), places: codes.has('l'), private: codes.has('p'), cliffs: codes.has('c')};
}

const initialState = readState();
setLang(initialState.lang);
initNavbar();

// The orienteering map's archive headers for the opening view, read while the map is set up.
if (initialState.zoom >= MAP_MIN_ZOOM - 1) {
  // Degrees per CSS pixel at the opening zoom (512 px tiles), over the window: a generous box.
  const span = (360 / (512 * 2 ** initialState.zoom)) * Math.max(window.innerWidth, window.innerHeight);
  prefetchArchives([initialState.lon - span, initialState.lat - span, initialState.lon + span, initialState.lat + span]);
}

const context = createMap('map', initialState, visibilityOf(initialState.layers));
const {map} = context;
const tools = createDrawTools(map);

const toggles: LayerToggle[] = (
  [
    ['h', 'layers.hillshade'],
    ['l', 'layers.places'],
    ['p', 'layers.private'],
    ['c', 'layers.cliffs'],
  ] as const
).map(([code, labelKey]) => ({
  code,
  labelKey,
  isVisible: () => context.isVisible(LAYER_BY_CODE[code]),
  setVisible: (visible) => context.setVisible(LAYER_BY_CODE[code], visible),
}));

function currentState(): AppState {
  const {lng, lat} = map.getCenter();
  return {
    zoom: map.getZoom(),
    lat,
    lon: lng,
    layers: new Set(toggles.filter((toggle) => toggle.isVisible()).map(({code}) => code)),
    lang: getLang(),
    drawings: tools.getDrawings(),
  };
}

const save = () => writeState(currentState());

function applyState(state: AppState): void {
  setLang(state.lang);
  for (const toggle of toggles) {
    toggle.setVisible(state.layers.has(toggle.code));
  }
  tools.setDrawings(state.drawings);
  map.jumpTo({center: [state.lon, state.lat], zoom: state.zoom});
}

applyState(initialState);

/** Centre of the view in EPSG:3857, which the print and OCD maths work in. */
const viewCenter = () => {
  const {lng, lat} = map.getCenter();
  return fromLonLat([lng, lat]);
};

const preview = createPrintPreview(map);
let printSettings: PrintSettings | null = null;

function refreshPreview(): void {
  if (printSettings) {
    preview.show(viewCenter(), printSettings.scale, printSettings.orientation);
  } else {
    preview.hide();
  }
}

const onSettingsChange = (settings: PrintSettings | null) => {
  printSettings = settings;
  refreshPreview();
};

// Chrome created after the map, so the controls' labels are translated too.
map.addControl(domControl(createLayerPanel(toggles, save, context.onVisibilityChange)), 'top-right');
map.addControl(
  domControl(
    createPrintPanel({
      onSettingsChange,
      onExport: async (settings) => {
        try {
          // Loaded on demand, with jsPDF: bigger than the rest of the app put together.
          const {exportPdf} = await import('./pdf');
          const visible = context.visibility();
          const {drawings, labels} = tools.collections();
          await exportPdf({
            ...settings,
            center: viewCenter(),
            source: archiveSource(),
            visible,
            drawings,
            drawingLabels: labels,
            // The notices of what is on the page, which is at the orienteering map's zooms.
            attribution: attributionText(
              MAP_MIN_ZOOM,
              visible,
              map.getBounds().toArray().flat() as [number, number, number, number],
              {basemap: false},
            ),
            fileName: `mapant-germany_1-${settings.scale}.pdf`,
          });
          showToast(t('print.ready'));
        } catch (error) {
          console.error('PDF export failed', error);
          showToast(t('print.failed'), 4000);
        }
      },
    }),
  ),
  'top-right',
);
map.addControl(
  domControl(
    createOcdPanel({
      onSettingsChange,
      onExport: async (settings) => {
        try {
          const [{exportOcd}, {gridZoneFor}, {zipSync}, response] = await Promise.all([
            import('./ocd'),
            import('./ocd/proj'),
            import('fflate'),
            fetch(OCD_TEMPLATE_URL),
          ]);
          if (!response.ok) {
            throw new Error(`${OCD_TEMPLATE_URL}: ${response.status}`);
          }
          const {lng, lat} = map.getCenter();
          const crs = await crsAt([lng, lat]);
          const name = `mapant-germany_1-${settings.scale}`;
          const result = await exportOcd({
            ...settings,
            center: viewCenter(),
            source: archiveSource(),
            template: await response.arrayBuffer(),
            crs,
            gridZone: gridZoneFor(crs),
            name,
          });
          if (result.tiles === 0) {
            showToast(t('ocd.empty'), 4000);
            return;
          }
          // Codes with no symbol in the template are dropped rather than written as references to
          // nothing; worth knowing about, but not worth stopping for.
          if (result.skipped.size > 0) {
            console.warn('OCD export skipped unmapped symbols', Object.fromEntries(result.skipped));
          }
          if (result.unreadable > 0) {
            console.warn(`OCD export: ${result.unreadable} tile(s) were not readable as vector tiles`);
          }
          // One file is saved as it is; with a background map, the OCD and its image go together.
          if (result.files.length === 1) {
            saveFile(result.files[0].data, result.files[0].name);
          } else {
            // The PNG is compressed already, and the OCD barely compresses at the cost of seconds.
            const entries = Object.fromEntries(
              result.files.map((file): [string, [Uint8Array, {level: 1}]] => [file.name, [file.data, {level: 1}]]),
            );
            saveFile(zipSync(entries), `${name}.zip`);
          }
          showToast(t('ocd.ready'));
        } catch (error) {
          console.error('OCD export failed', error);
          showToast(t('ocd.failed'), 4000);
        }
      },
    }),
  ),
  'top-right',
);
map.addControl(domControl(createShareControl()), 'top-right');
map.addControl(domControl(createDrawToolbar(tools)), 'bottom-left');
applyTranslations();

initZoomHint(map, MAP_MIN_ZOOM);

map.on('moveend', refreshPreview);
map.on('moveend', save);
tools.onChange(save);
onLangChange(() => {
  tools.refresh();
  if (map.getLayer(STATE_LABEL_LAYER)) {
    map.setLayoutProperty(STATE_LABEL_LAYER, 'text-field', stateLabelText());
  }
  save();
});

// Someone pasting a share link into the address bar of an open map.
window.addEventListener('hashchange', () => applyState(readState()));

save();

function saveFile(bytes: Uint8Array, fileName: string): void {
  const url = URL.createObjectURL(new Blob([bytes as BlobPart], {type: 'application/octet-stream'}));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}
