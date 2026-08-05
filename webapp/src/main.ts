import './style.css';
// Bundles ol.css together with the app's overrides of it.
import './map.css';

import {fromLonLat, toLonLat} from 'ol/proj';
import {createDrawTools} from './draw';
import {applyTranslations, getLang, onLangChange, setLang} from './i18n';
import {MAPANT_MIN_ZOOM} from './layers';
import {createMap} from './map';
import {DEFAULT_VIEW, readState, writeState, type AppState} from './urlstate';
import {createDrawToolbar} from './ui/drawtoolbar';
import {initZoomHint} from './ui/hint';
import {createLayerPanel, type LayerToggle} from './ui/layerpanel';
import {initNavbar} from './ui/navbar';
import {createShareControl} from './ui/share';

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

// Chrome created after the map, so the controls' labels are translated too.
map.addControl(createLayerPanel(toggles, save, controlStack));
map.addControl(createShareControl(controlStack));
map.addControl(createDrawToolbar(tools));
applyTranslations();

initZoomHint(map, MAPANT_MIN_ZOOM);

map.on('moveend', save);
tools.onChange(save);
onLangChange(() => {
  tools.refresh();
  save();
});

// Someone pasting a share link into the address bar of an open map.
window.addEventListener('hashchange', () => applyState(readState()));

save();
