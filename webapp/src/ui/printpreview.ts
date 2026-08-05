import Feature from 'ol/Feature';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import Style from 'ol/style/Style';
import type {Coordinate} from 'ol/coordinate';
import {printOutline, type Orientation} from '../print';

export interface PrintPreview {
  layer: VectorLayer<VectorSource>;
  show(center: Coordinate, scale: number, orientation: Orientation): void;
  hide(): void;
}

/**
 * The rectangle showing what a print would cover. Lives in the live map only –
 * the print map is built from its own layers, so this never ends up on paper.
 */
export function createPrintPreview(): PrintPreview {
  const feature = new Feature();
  const layer = new VectorLayer({
    visible: false,
    source: new VectorSource({features: [feature]}),
    style: new Style({
      stroke: new Stroke({color: '#3172ad', width: 2, lineDash: [10, 6]}),
      fill: new Fill({color: 'rgba(49, 114, 173, 0.07)'}),
    }),
  });

  return {
    layer,
    show(center, scale, orientation) {
      feature.setGeometry(printOutline(center, scale, orientation));
      layer.setVisible(true);
    },
    hide() {
      layer.setVisible(false);
    },
  };
}
