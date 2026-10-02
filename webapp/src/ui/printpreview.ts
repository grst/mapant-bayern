import type {GeoJSONSource, Map} from 'maplibre-gl';
import type {XY} from '../geo';
import {EMPTY_COLLECTION} from '../layers';
import {printOutline, type Orientation} from '../print';

export interface PrintPreview {
  show(center: XY, scale: number, orientation: Orientation): void;
  hide(): void;
}

/**
 * The rectangle showing what a print would cover. Lives in the live map only –
 * the print map is built from its own style, so this never ends up on paper.
 */
export function createPrintPreview(map: Map): PrintPreview {
  let outline: GeoJSON.FeatureCollection = EMPTY_COLLECTION;
  const render = () => map.getSource<GeoJSONSource>('print-preview')?.setData(outline);

  map.on('load', () => {
    map.addSource('print-preview', {type: 'geojson', data: outline});
    map.addLayer({
      id: 'print-preview-fill',
      type: 'fill',
      source: 'print-preview',
      paint: {'fill-color': 'rgba(49, 114, 173, 0.07)'},
    });
    map.addLayer({
      id: 'print-preview-line',
      type: 'line',
      source: 'print-preview',
      paint: {'line-color': '#3172ad', 'line-width': 2, 'line-dasharray': [5, 3]},
    });
  });

  return {
    show(center, scale, orientation) {
      outline = {
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            properties: {},
            geometry: {type: 'Polygon', coordinates: [printOutline(center, scale, orientation)]},
          },
        ],
      };
      render();
    },
    hide() {
      outline = EMPTY_COLLECTION;
      render();
    },
  };
}
