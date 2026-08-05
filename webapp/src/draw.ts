import Feature from 'ol/Feature';
import Overlay from 'ol/Overlay';
import Draw from 'ol/interaction/Draw';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import LineString from 'ol/geom/LineString';
import Point from 'ol/geom/Point';
import Polygon from 'ol/geom/Polygon';
import {unByKey} from 'ol/Observable';
import {getArea, getLength} from 'ol/sphere';
import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import Style from 'ol/style/Style';
import Text from 'ol/style/Text';
import CircleStyle from 'ol/style/Circle';
import type Map from 'ol/Map';
import type {FeatureLike} from 'ol/Feature';
import type Geometry from 'ol/geom/Geometry';
import type {EventsKey} from 'ol/events';
import {
  closeRing,
  fromShareCoordinate,
  snapToShareGrid,
  toShareCoordinate,
  type Drawing,
  type DrawingType,
} from './drawings';
import {formatNumber} from './i18n';

const ACCENT = '#e2136e';

/**
 * The look of a finished sketch. Sizes are CSS pixels, multiplied by `scale` so
 * the print map – which renders at one canvas pixel per pixel of output – draws
 * them at the width they have on screen (see print.ts).
 */
function createDrawingStyle(scale: number): (feature: FeatureLike) => Style[] {
  const geometryStyle = new Style({
    stroke: new Stroke({color: ACCENT, width: 3 * scale}),
    fill: new Fill({color: 'rgba(226, 19, 110, 0.12)'}),
    image: new CircleStyle({
      radius: 4 * scale,
      fill: new Fill({color: ACCENT}),
    }),
  });

  const labelStyle = new Style({
    text: new Text({
      font: `bold ${12 * scale}px system-ui, sans-serif`,
      fill: new Fill({color: '#1b1b1b'}),
      backgroundFill: new Fill({color: 'rgba(255, 255, 255, 0.85)'}),
      padding: [2 * scale, 4 * scale, 2 * scale, 4 * scale],
      offsetY: -12 * scale,
      overflow: true,
    }),
  });

  return (feature: FeatureLike) => {
    const geometry = feature.getGeometry();
    const styles = [geometryStyle];
    const point = geometry ? labelPoint(geometry as Geometry) : undefined;
    if (point) {
      labelStyle.setGeometry(point);
      labelStyle.getText()?.setText(measure(geometry as Geometry));
      styles.push(labelStyle);
    }
    return styles;
  };
}

export function formatLength(line: LineString): string {
  const metres = getLength(line);
  return metres >= 1000 ? `${formatNumber(metres / 1000, 2)} km` : `${formatNumber(metres, 0)} m`;
}

export function formatArea(polygon: Polygon): string {
  const squareMetres = getArea(polygon);
  if (squareMetres >= 1e6) {
    return `${formatNumber(squareMetres / 1e6, 2)} km²`;
  }
  if (squareMetres >= 1e4) {
    return `${formatNumber(squareMetres / 1e4, 2)} ha`;
  }
  return `${formatNumber(squareMetres, 0)} m²`;
}

function measure(geometry: Geometry | undefined): string {
  if (geometry instanceof Polygon) {
    return formatArea(geometry);
  }
  if (geometry instanceof LineString) {
    return formatLength(geometry);
  }
  return '';
}

/** Where the measurement is written: end of a line, centre of a polygon. */
function labelPoint(geometry: Geometry): Point | undefined {
  if (geometry instanceof Polygon) {
    return geometry.getInteriorPoint();
  }
  if (geometry instanceof LineString) {
    return new Point(geometry.getLastCoordinate());
  }
  return undefined;
}

/**
 * Moves a finished geometry onto the grid the share link stores, so what is
 * measured on screen is exactly what a shared link measures. The shift is below
 * a decimetre; the difference in a reported area would not be.
 */
function snapGeometry(geometry: Geometry): void {
  if (geometry instanceof Polygon) {
    geometry.setCoordinates(geometry.getCoordinates().map((ring) => ring.map(snapToShareGrid)));
  } else if (geometry instanceof LineString) {
    geometry.setCoordinates(geometry.getCoordinates().map(snapToShareGrid));
  }
}

export interface DrawTools {
  layer: VectorLayer<VectorSource>;
  setMode(mode: DrawingType | null): void;
  getMode(): DrawingType | null;
  onModeChange(listener: (mode: DrawingType | null) => void): void;
  onChange(listener: () => void): void;
  getDrawings(): Drawing[];
  setDrawings(drawings: Drawing[]): void;
  undo(): void;
  clear(): void;
  /**
   * A second layer over the same drawings. Layers belong to one map at a time,
   * so the print map needs its own – sharing the source keeps them in step.
   */
  printCopy(styleScale: number): VectorLayer<VectorSource>;
  /** Re-renders the measurement labels, e.g. after a language switch. */
  refresh(): void;
}

export function createDrawTools(map: Map): DrawTools {
  const source = new VectorSource();
  const layer = new VectorLayer({source, style: createDrawingStyle(1)});

  const modeListeners = new Set<(mode: DrawingType | null) => void>();
  const changeListeners = new Set<() => void>();
  let mode: DrawingType | null = null;
  let interaction: Draw | undefined;

  // Live measurement while a geometry is being drawn.
  const tooltipElement = document.createElement('div');
  tooltipElement.className = 'measure-tooltip';
  const tooltip = new Overlay({
    element: tooltipElement,
    offset: [0, -12],
    positioning: 'bottom-center',
    stopEvent: false,
  });
  map.addOverlay(tooltip);
  tooltip.setPosition(undefined);

  const emitChange = () => changeListeners.forEach((listener) => listener());

  function setMode(next: DrawingType | null): void {
    if (interaction) {
      map.removeInteraction(interaction);
      interaction = undefined;
    }
    tooltip.setPosition(undefined);
    mode = next;

    if (mode) {
      let sketchListener: EventsKey | undefined;
      interaction = new Draw({source, type: mode === 'p' ? 'Polygon' : 'LineString'});
      interaction.on('drawstart', (event) => {
        const geometry = event.feature.getGeometry();
        sketchListener = geometry?.on('change', () => {
          const point = labelPoint(geometry);
          tooltipElement.textContent = measure(geometry);
          tooltip.setPosition(point?.getCoordinates());
        });
      });
      interaction.on('drawend', (event) => {
        if (sketchListener) {
          unByKey(sketchListener);
          sketchListener = undefined;
        }
        const geometry = event.feature.getGeometry();
        if (geometry) {
          snapGeometry(geometry);
        }
        tooltip.setPosition(undefined);
        // The feature is only in the source after this handler returns.
        setTimeout(emitChange, 0);
      });
      map.addInteraction(interaction);
    }
    modeListeners.forEach((listener) => listener(mode));
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mode) {
      interaction?.abortDrawing();
      setMode(null);
    }
  });

  return {
    layer,
    setMode,
    getMode: () => mode,
    onModeChange: (listener) => modeListeners.add(listener),
    onChange: (listener) => changeListeners.add(listener),

    getDrawings: () =>
      source.getFeatures().flatMap((feature): Drawing[] => {
        const geometry = feature.getGeometry();
        if (geometry instanceof Polygon) {
          // Drop the repeated closing coordinate; closeRing() puts it back.
          return [{t: 'p', c: geometry.getCoordinates()[0].slice(0, -1).map(toShareCoordinate)}];
        }
        if (geometry instanceof LineString) {
          return [{t: 'l', c: geometry.getCoordinates().map(toShareCoordinate)}];
        }
        return [];
      }),

    setDrawings: (drawings) => {
      source.clear();
      source.addFeatures(
        drawings.map((drawing) => {
          const coordinates = drawing.c.map(fromShareCoordinate);
          return new Feature(
            drawing.t === 'p' ? new Polygon([closeRing(coordinates)]) : new LineString(coordinates),
          );
        }),
      );
    },

    undo: () => {
      const features = source.getFeatures();
      const last = features[features.length - 1];
      if (last) {
        source.removeFeature(last);
        emitChange();
      }
    },

    clear: () => {
      if (source.getFeatures().length > 0) {
        source.clear();
        emitChange();
      }
    },

    printCopy: (styleScale) => new VectorLayer({source, style: createDrawingStyle(styleScale)}),

    // Units and decimal separators are language dependent, so the labels have to
    // be re-rendered when the language changes.
    refresh: () => layer.changed(),
  };
}
