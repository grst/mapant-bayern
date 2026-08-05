import type Map from 'ol/Map';

/**
 * "Zoom in to view the orienteering map" – shown while the view sits below the
 * lowest zoom level the archive covers.
 */
export function initZoomHint(map: Map, minZoom: number): void {
  const hint = document.getElementById('zoom-hint');
  if (!hint) {
    return;
  }
  const view = map.getView();
  const update = () => {
    const zoom = view.getZoom();
    hint.hidden = zoom !== undefined && zoom >= minZoom;
  };
  view.on('change:resolution', update);
  update();
}
