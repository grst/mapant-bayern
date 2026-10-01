import type {Map} from 'maplibre-gl';

/**
 * "Zoom in to view the orienteering map" – shown while the view sits below the
 * lowest zoom level the vector pyramid covers.
 */
export function initZoomHint(map: Map, minZoom: number): void {
  const hint = document.getElementById('zoom-hint');
  if (!hint) {
    return;
  }
  const update = () => {
    hint.hidden = map.getZoom() >= minZoom;
  };
  map.on('zoom', update);
  update();
}
