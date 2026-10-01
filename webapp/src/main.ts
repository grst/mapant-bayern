import './style.css';
// Bundles maplibre-gl.css together with the app's overrides of it.
import './map.css';

import {createDrawTools} from './draw';
import {fromLonLat} from './geo';
import {applyTranslations, getLang, onLangChange, setLang, t} from './i18n';
import {
  attributionText,
  createStyle,
  MAP_MIN_ZOOM,
  MAPANT_TILES_URL,
  TILES_MAX_ZOOM,
  TILES_MIN_ZOOM,
  type OptionalLayer,
  type Visibility,
} from './layers';
import {createMap, domControl} from './map';
import {exportPdf} from './print';
import {exportOcd, xyzSource} from './ocd';
import {MAP_CRS, OCD_TEMPLATE_URL} from './ocd/config';
import {gridZoneFor} from './ocd/proj';
import {readState, writeState, type AppState, type LayerCode} from './urlstate';
import {createDrawToolbar} from './ui/drawtoolbar';
import {initZoomHint} from './ui/hint';
import {createLayerPanel, type LayerToggle} from './ui/layerpanel';
import {initNavbar} from './ui/navbar';
import {createPrintPanel, type PrintSettings} from './ui/printpanel';
import {createPrintPreview} from './ui/printpreview';
import {createShareControl} from './ui/share';
import {showToast} from './ui/toast';

/** The layers the share link can switch, by their code in it. */
const LAYER_BY_CODE: Record<LayerCode, OptionalLayer> = {h: 'hillshade', l: 'places', g: 'grid'};

function visibilityOf(codes: Set<LayerCode>): Visibility {
  return {hillshade: codes.has('h'), places: codes.has('l'), grid: codes.has('g')};
}

const initialState = readState();
setLang(initialState.lang);
initNavbar();

const context = createMap('map', initialState, visibilityOf(initialState.layers));
const {map} = context;
const tools = createDrawTools(map);

const toggles: LayerToggle[] = (
  [
    ['h', 'layers.hillshade'],
    ['l', 'layers.places'],
    ['g', 'layers.grid'],
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

// Chrome created after the map, so the controls' labels are translated too.
map.addControl(domControl(createLayerPanel(toggles, save, context.onVisibilityChange)), 'top-right');
map.addControl(
  domControl(
    createPrintPanel({
      onSettingsChange: (settings) => {
        printSettings = settings;
        refreshPreview();
      },
      onExportOcd: async (settings) => {
        try {
          const response = await fetch(OCD_TEMPLATE_URL);
          if (!response.ok) {
            throw new Error(`${OCD_TEMPLATE_URL}: ${response.status}`);
          }
          const result = await exportOcd({
            ...settings,
            center: viewCenter(),
            source: xyzSource(MAPANT_TILES_URL, TILES_MIN_ZOOM, TILES_MAX_ZOOM),
            template: await response.arrayBuffer(),
            crs: MAP_CRS,
            gridZone: gridZoneFor(MAP_CRS),
          });
          if (result.objects === 0) {
            showToast(t('print.ocdEmpty'), 4000);
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
          saveFile(result.file, `mapant-bayern_1-${settings.scale}.ocd`);
          showToast(t('print.ocdReady'));
        } catch (error) {
          console.error('OCD export failed', error);
          showToast(t('print.ocdFailed'), 4000);
        }
      },
      onExport: async (settings) => {
        try {
          const visible = context.visibility();
          const {drawings, labels} = tools.collections();
          await exportPdf({
            ...settings,
            center: viewCenter(),
            style: createStyle({visible, print: true, drawings, drawingLabels: labels}),
            showTileBoundaries: visible.grid,
            // The notices of what is on the page, which is at the orienteering map's zooms.
            attribution: attributionText(MAP_MIN_ZOOM, visible),
            fileName: `mapant-bayern_1-${settings.scale}.pdf`,
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
map.addControl(domControl(createShareControl()), 'top-right');
map.addControl(domControl(createDrawToolbar(tools)), 'bottom-left');
applyTranslations();

initZoomHint(map, MAP_MIN_ZOOM);

map.on('moveend', refreshPreview);
map.on('moveend', save);
tools.onChange(save);
onLangChange(() => {
  tools.refresh();
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
