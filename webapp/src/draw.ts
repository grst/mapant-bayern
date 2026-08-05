import Feature from 'ol/Feature';
import Overlay from 'ol/Overlay';
import Draw from 'ol/interaction/Draw';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import LineString from 'ol/geom/LineString';
import Point from 'ol/geom/Point';
import Polygon from 'ol/geom/Polygon';
import {fromLonLat, toLonLat} from 'ol/proj';
import {getArea, getLength} from 'ol/sphere';
import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import Style from 'ol/style/Style';
import Text from 'ol/style/Text';
import CircleStyle from 'ol/style/Circle';
import type Map from 'ol/Map';
import type {FeatureLike} from 'ol/Feature';
import type Geometry from 'ol/geom/Geometry';
import type {Drawing, DrawingType} from './drawings';
import {formatNumber} from './i18n';

const ACCENT = '#e2136e';

const geometryStyle = new Style({
  stroke: new Stroke({color: ACCENT, width: 3}),
  fill: new Fill({color: 'rgba(226, 19, 110, 0.12)'}),
  image: new CircleStyle({
    radius: 4,
    fill: new Fill({color: ACCENT}),
  }),
});

const labelStyle = new Style({
  text: new Text({
    font: 'bold 12px system-ui, sans-serif',
    fill: new Fill({color: '#1b1b1b'}),
    backgroundFill: new Fill({color: 'rgba(255, 255, 255, 0.85)'}),
    padding: [2, 4, 2, 4],
    offsetY: -12,
    overflow: true,
  }),
});

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

function drawingStyle(feature: FeatureLike): Style[] {
  const geometry = feature.getGeometry();
  const styles = [geometryStyle];
  const point = geometry ? labelPoint(geometry as Geometry) : undefined;
  if (point) {
    labelStyle.setGeometry(point);
    labelStyle.getText()?.setText(measure(geometry as Geometry));
    styles.push(labelStyle);
  }
  return styles;
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
  /** Re-renders the measurement labels, e.g. after a language switch. */
  refresh(): void;
}

export function createDrawTools(map: Map): DrawTools {
  const source = new VectorSource();
  const layer = new VectorLayer({source, style: drawingStyle});

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
      interaction = new Draw({source, type: mode === 'p' ? 'Polygon' : 'LineString'});
      interaction.on('drawstart', (event) => {
        const geometry = event.feature.getGeometry();
        geometry?.on('change', () => {
          const point = labelPoint(geometry);
          tooltipElement.textContent = measure(geometry);
          tooltip.setPosition(point?.getCoordinates());
        });
      });
      interaction.on('drawend', () => {
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
          return [{t: 'p', c: geometry.getCoordinates()[0].slice(0, -1).map(toLonLatPair)}];
        }
        if (geometry instanceof LineString) {
          return [{t: 'l', c: geometry.getCoordinates().map(toLonLatPair)}];
        }
        return [];
      }),

    setDrawings: (drawings) => {
      source.clear();
      source.addFeatures(
        drawings.map((drawing) => {
          const coordinates = drawing.c.map((pair) => fromLonLat(pair));
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

    // Units and decimal separators are language dependent, so the labels have
      // to be re-rendered when the language changes.
    refresh: () => layer.changed(),
  };
}

function toLonLatPair(coordinate: number[]): [number, number] {
  const [lon, lat] = toLonLat(coordinate);
  return [round(lon), round(lat)];
}

/** 5 decimals is roughly a metre – plenty for a shared sketch, and much shorter. */
function round(value: number): number {
  return Math.round(value * 1e5) / 1e5;
}

function closeRing(coordinates: number[][]): number[][] {
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  if (first && last && (first[0] !== last[0] || first[1] !== last[1])) {
    return [...coordinates, first];
  }
  return coordinates;
}
