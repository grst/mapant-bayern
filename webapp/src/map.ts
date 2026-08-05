import Map from 'ol/Map';
import View from 'ol/View';
import Attribution from 'ol/control/Attribution';
import Control from 'ol/control/Control';
import FullScreen from 'ol/control/FullScreen';
import ScaleLine from 'ol/control/ScaleLine';
import Zoom from 'ol/control/Zoom';
import {defaults as defaultInteractions} from 'ol/interaction/defaults';
import {fromLonLat} from 'ol/proj';
import {t} from './i18n';
import type {Key} from './i18n/en';
import {createLayers, MAPANT_MAX_ZOOM, type AppLayers} from './layers';

export interface MapContext {
  map: Map;
  layers: AppLayers;
  /** Top-right column that the layer and share controls render into. */
  controlStack: HTMLElement;
}

/** Marks an OpenLayers-generated button so a language switch re-labels it. */
function tagTooltip(element: Element | null, key: Key): void {
  if (element instanceof HTMLElement) {
    element.dataset.i18nTitle = key;
    element.title = t(key);
  }
}

export function createMap(target: string, view: {zoom: number; lat: number; lon: number}): MapContext {
  const layers = createLayers();

  const controlStack = document.createElement('div');
  controlStack.className = 'ol-control map-control-stack';

  const controls = [
    new Zoom({zoomInTipLabel: t('ol.zoomIn'), zoomOutTipLabel: t('ol.zoomOut')}),
    new Control({element: controlStack}),
    new FullScreen({tipLabel: t('ol.fullscreen'), target: controlStack}),
    new ScaleLine({minWidth: 80}),
  ];

  // Per-layer copyright notices: OpenLayers only lists the layers that are
  // actually being rendered, and the control writes them into the page footer.
  const attributionTarget = document.getElementById('attribution');
  if (attributionTarget) {
    controls.push(new Attribution({target: attributionTarget, collapsible: false}));
  }

  const map = new Map({
    target,
    layers: [layers.osm, layers.mapant, layers.hillshade, layers.places, layers.grid],
    controls,
    // The map container has a `tabindex` so it can be panned with the keyboard,
    // and a Map built without explicit interactions then only drags and wheel
    // zooms while that container has the focus. On a touch screen that costs a
    // tap before the map reacts to a swipe at all, so the focus condition goes.
    interactions: defaultInteractions({onFocusOnly: false}),
    view: new View({
      center: fromLonLat([view.lon, view.lat]),
      zoom: view.zoom,
      minZoom: 1,
      maxZoom: MAPANT_MAX_ZOOM,
      // An orienteering map is read north-up, and no rotation keeps share links simple.
      enableRotation: false,
    }),
  });

  const viewport = map.getViewport();
  tagTooltip(viewport.querySelector('.ol-zoom-in'), 'ol.zoomIn');
  tagTooltip(viewport.querySelector('.ol-zoom-out'), 'ol.zoomOut');
  tagTooltip(viewport.querySelector('.ol-full-screen button'), 'ol.fullscreen');

  return {map, layers, controlStack};
}
