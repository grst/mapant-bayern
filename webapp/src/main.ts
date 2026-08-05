import './style.css';
// Bundles ol.css together with the app's overrides of it.
import './map.css';

import {fromLonLat, toLonLat} from 'ol/proj';
import type BaseLayer from 'ol/layer/Base';
import {createDrawTools} from './draw';
import {applyTranslations, getLang, onLangChange, setLang, t} from './i18n';
import {attributionText, createLayers, MAPANT_MIN_ZOOM} from './layers';
import {createMap} from './map';
import {exportPdf, type PrintLayerOptions} from './print';
import {DEFAULT_VIEW, readState, writeState, type AppState} from './urlstate';
import {createDrawToolbar} from './ui/drawtoolbar';
import {initZoomHint} from './ui/hint';
import {createLayerPanel, type LayerToggle} from './ui/layerpanel';
import {initNavbar} from './ui/navbar';
import {createPrintPanel, type PrintSettings} from './ui/printpanel';
import {createPrintPreview} from './ui/printpreview';
import {createShareControl} from './ui/share';
import {showToast} from './ui/toast';

const initialState = readState();
setLang(initialState.lang);
initNavbar();

const {map, layers, controlStack} = createMap('map', initialState);
const tools = createDrawTools(map);
map.addLayer(tools.layer);

const toggles: LayerToggle[] = [
  {code: 'h', labelKey: 'layers.hillshade', layer: layers.hillshade},
  {code: 'l', labelKey: 'layers.places', layer: layers.places},
  {code: 'g', labelKey: 'layers.grid', layer: layers.grid},
];

function currentState(): AppState {
  const view = map.getView();
  const [lon, lat] = toLonLat(view.getCenter() ?? []);
  return {
    zoom: view.getZoom() ?? DEFAULT_VIEW.zoom,
    lat: lat ?? DEFAULT_VIEW.lat,
    lon: lon ?? DEFAULT_VIEW.lon,
    layers: new Set(toggles.filter(({layer}) => layer.getVisible()).map(({code}) => code)),
    lang: getLang(),
    drawings: tools.getDrawings(),
  };
}

const save = () => writeState(currentState());

function applyState(state: AppState): void {
  setLang(state.lang);
  for (const {code, layer} of toggles) {
    layer.setVisible(state.layers.has(code));
  }
  tools.setDrawings(state.drawings);
  const view = map.getView();
  view.setCenter(fromLonLat([state.lon, state.lat]));
  view.setZoom(state.zoom);
}

applyState(initialState);

/**
 * Layers for the print map. Layers belong to a single map, so they are rebuilt
 * from scratch; the visibility of the live ones is what the user asked to see.
 */
function printLayers(options: PrintLayerOptions): BaseLayer[] {
  const fresh = createLayers(options);
  for (const key of ['osm', 'mapant', 'hillshade', 'places', 'grid'] as const) {
    fresh[key].setVisible(layers[key].getVisible());
  }
  return [
    fresh.osm,
    fresh.mapant,
    fresh.hillshade,
    fresh.places,
    fresh.grid,
    tools.printCopy(options.styleScale),
  ];
}

const preview = createPrintPreview();
map.addLayer(preview.layer);
let printSettings: PrintSettings | null = null;

function refreshPreview(): void {
  const center = map.getView().getCenter();
  if (printSettings && center) {
    preview.show(center, printSettings.scale, printSettings.orientation);
  } else {
    preview.hide();
  }
}

// Chrome created after the map, so the controls' labels are translated too.
map.addControl(createLayerPanel(toggles, save, controlStack));
map.addControl(
  createPrintPanel(
    {
      onSettingsChange: (settings) => {
        printSettings = settings;
        refreshPreview();
      },
      onExport: async (settings) => {
        const center = map.getView().getCenter();
        if (!center) {
          return;
        }
        try {
          await exportPdf({
            ...settings,
            center,
            createLayers: printLayers,
            attribution: attributionText(layers),
            fileName: `mapant-bayern_1-${settings.scale}.pdf`,
          });
          showToast(t('print.ready'));
        } catch (error) {
          console.error('PDF export failed', error);
          showToast(t('print.failed'), 4000);
        }
      },
    },
    controlStack,
  ),
);
map.addControl(createShareControl(controlStack));
map.addControl(createDrawToolbar(tools));
applyTranslations();

initZoomHint(map, MAPANT_MIN_ZOOM);

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
