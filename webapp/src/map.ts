import {FullscreenControl, Map, NavigationControl, ScaleControl, setWorkerUrl} from 'maplibre-gl';
import type {IControl} from 'maplibre-gl';
// MapLibre parses tiles in web workers, whose script it loads from next to its own module -- which
// a bundle does not have. Vite builds the worker with its dependencies and hands over the URL.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import {t} from './i18n';
import type {Key} from './i18n/en';
import {provideIsomIcons, rasterizeIsomIcons} from './isomstyle';
import {
  attributions,
  createStyle,
  MAP_MAX_ZOOM,
  OPTIONAL_STYLE_LAYERS,
  type OptionalLayer,
  type Visibility,
} from './layers';

setWorkerUrl(workerUrl);

export interface MapContext {
  map: Map;
  isVisible(layer: OptionalLayer): boolean;
  setVisible(layer: OptionalLayer, visible: boolean): void;
  visibility(): Visibility;
  onVisibilityChange(listener: () => void): void;
}

/** Marks a MapLibre-generated button so a language switch re-labels it. */
function tagTooltip(element: Element | null, key: Key): void {
  if (element instanceof HTMLElement) {
    element.dataset.i18nTitle = key;
    element.dataset.i18nLabel = key;
    element.title = t(key);
    element.setAttribute('aria-label', t(key));
  }
}

/** Wraps an element of the app's own as a MapLibre control. */
export function domControl(element: HTMLElement): IControl {
  return {
    onAdd: () => element,
    onRemove: () => element.remove(),
  };
}

export function createMap(
  target: string,
  view: {zoom: number; lat: number; lon: number},
  initiallyVisible: Visibility,
): MapContext {
  const visible: Visibility = {...initiallyVisible};

  const map = new Map({
    container: target,
    style: createStyle({visible}),
    center: [view.lon, view.lat],
    zoom: view.zoom,
    minZoom: 0,
    maxZoom: MAP_MAX_ZOOM,
    // An orienteering map is read north-up, and no rotation keeps share links simple.
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
    maxPitch: 0,
    // The notices go into the page footer instead, see below.
    attributionControl: false,
  });
  // MapLibre's canvas is the map's tab stop and takes the arrow keys. The container stays
  // focusable for the skip link, and hands the focus on.
  map.getContainer().addEventListener('focus', () => map.getCanvas().focus());
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  map.showTileBoundaries = visible.grid;
  provideIsomIcons(map, rasterizeIsomIcons(window.devicePixelRatio));

  map.addControl(new NavigationControl({showCompass: false}), 'top-left');
  // The whole page area under the navbar, so the footer's notices stay out of the way.
  map.addControl(new FullscreenControl(), 'top-right');
  map.addControl(new ScaleControl({maxWidth: 120}), 'bottom-right');

  const container = map.getContainer();
  tagTooltip(container.querySelector('.maplibregl-ctrl-zoom-in'), 'ol.zoomIn');
  tagTooltip(container.querySelector('.maplibregl-ctrl-zoom-out'), 'ol.zoomOut');
  tagTooltip(container.querySelector('.maplibregl-ctrl-fullscreen'), 'ol.fullscreen');

  // Per-source copyright notices, written into the page footer: only those of what is on screen.
  const attributionTarget = document.getElementById('attribution');
  let shownAttribution = '';
  const updateAttribution = () => {
    const html = `<ul>${attributions(map.getZoom(), visible, map.getBounds().toArray().flat() as [number, number, number, number])
      .map((notice) => `<li>${notice}</li>`)
      .join('')}</ul>`;
    if (attributionTarget && html !== shownAttribution) {
      attributionTarget.innerHTML = html;
      shownAttribution = html;
    }
  };
  map.on('moveend', updateAttribution);
  map.on('zoom', updateAttribution);
  updateAttribution();

  // Layout properties can only be set once the style is in; the initial visibility is part of
  // the style itself, so only a change that comes earlier (a pasted link) has to wait.
  let styleReady = false;
  map.once('style.load', () => (styleReady = true));
  const whenStyleReady = (apply: () => void) => (styleReady ? apply() : map.once('style.load', apply));

  const listeners = new Set<() => void>();

  return {
    map,
    isVisible: (layer) => visible[layer],
    visibility: () => ({...visible}),
    setVisible(layer, value) {
      if (visible[layer] === value) {
        return;
      }
      visible[layer] = value;
      const styleLayer = OPTIONAL_STYLE_LAYERS[layer];
      if (styleLayer) {
        whenStyleReady(() => map.setLayoutProperty(styleLayer, 'visibility', visible[layer] ? 'visible' : 'none'));
      } else if (layer === 'grid') {
        map.showTileBoundaries = value;
      }
      updateAttribution();
      listeners.forEach((listener) => listener());
    },
    onVisibilityChange: (listener) => listeners.add(listener),
  };
}
