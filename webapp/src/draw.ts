import {Marker} from 'maplibre-gl';
import type {GeoJSONSource, Map, MapMouseEvent} from 'maplibre-gl';
import {closeRing, snapToShareGrid, type Drawing, type DrawingType} from './drawings';
import {interiorPoint, lineLength, ringArea, type LonLat} from './geo';
import {formatNumber} from './i18n';
import {DRAWING_ACCENT, EMPTY_COLLECTION} from './layers';

/** How close, in screen pixels, a click has to be to a vertex to finish the sketch there. */
const FINISH_TOLERANCE_PX = 10;

export function formatLength(line: LonLat[]): string {
  const metres = lineLength(line);
  return metres >= 1000 ? `${formatNumber(metres / 1000, 2)} km` : `${formatNumber(metres, 0)} m`;
}

export function formatArea(ring: LonLat[]): string {
  const squareMetres = ringArea(ring);
  if (squareMetres >= 1e6) {
    return `${formatNumber(squareMetres / 1e6, 2)} km²`;
  }
  if (squareMetres >= 1e4) {
    return `${formatNumber(squareMetres / 1e4, 2)} ha`;
  }
  return `${formatNumber(squareMetres, 0)} m²`;
}

/** Where the measurement is written: end of a line, inside a polygon. */
function label(type: DrawingType, coordinates: LonLat[]): {at: LonLat; text: string} {
  return type === 'p'
    ? {at: interiorPoint(coordinates), text: formatArea(coordinates)}
    : {at: coordinates[coordinates.length - 1], text: formatLength(coordinates)};
}

function geometry(type: DrawingType, coordinates: LonLat[]): GeoJSON.Geometry {
  return type === 'p'
    ? {type: 'Polygon', coordinates: [closeRing(coordinates)]}
    : {type: 'LineString', coordinates};
}

export interface DrawTools {
  setMode(mode: DrawingType | null): void;
  getMode(): DrawingType | null;
  onModeChange(listener: (mode: DrawingType | null) => void): void;
  onChange(listener: () => void): void;
  getDrawings(): Drawing[];
  setDrawings(drawings: Drawing[]): void;
  undo(): void;
  clear(): void;
  /** The finished sketches and their labels as GeoJSON, e.g. for the print map's style. */
  collections(): {drawings: GeoJSON.FeatureCollection; labels: GeoJSON.FeatureCollection};
  /** Re-renders the measurement labels, e.g. after a language switch. */
  refresh(): void;
}

export function createDrawTools(map: Map): DrawTools {
  /** Finished sketches, on the share grid (see drawings.ts). */
  let drawings: Drawing[] = [];
  let mode: DrawingType | null = null;
  /** The vertices placed so far, and where the pointer is. */
  let sketch: LonLat[] = [];
  let pointer: LonLat | undefined;

  const modeListeners = new Set<(mode: DrawingType | null) => void>();
  const changeListeners = new Set<() => void>();
  const emitChange = () => changeListeners.forEach((listener) => listener());

  // Live measurement while a geometry is being drawn. A DOM marker, so it stays on screen only.
  const tooltipElement = document.createElement('div');
  tooltipElement.className = 'measure-tooltip';
  const tooltip = new Marker({element: tooltipElement, anchor: 'bottom', offset: [0, -12]});

  function collections() {
    return {
      drawings: {
        type: 'FeatureCollection' as const,
        features: drawings.map((drawing) => ({
          type: 'Feature' as const,
          properties: {},
          geometry: geometry(drawing.t, drawing.c),
        })),
      },
      labels: {
        type: 'FeatureCollection' as const,
        features: drawings.map((drawing) => {
          const {at, text} = label(drawing.t, drawing.c);
          return {type: 'Feature' as const, properties: {text}, geometry: {type: 'Point' as const, coordinates: at}};
        }),
      },
    };
  }

  const source = (id: string) => map.getSource<GeoJSONSource>(id);

  function render(): void {
    const {drawings: shapes, labels} = collections();
    source('drawings')?.setData(shapes);
    source('drawing-labels')?.setData(labels);
  }

  function renderSketch(): void {
    const vertices = pointer ? [...sketch, pointer] : sketch;
    const features: GeoJSON.Feature[] = vertices.map((coordinates) => ({
      type: 'Feature',
      properties: {},
      geometry: {type: 'Point', coordinates},
    }));
    if (mode && vertices.length >= 2) {
      features.push({type: 'Feature', properties: {}, geometry: geometry(mode, vertices)});
    }
    source('sketch')?.setData({type: 'FeatureCollection', features});

    if (mode && vertices.length >= 2) {
      const {at, text} = label(mode, vertices);
      tooltipElement.textContent = text;
      tooltip.setLngLat(at).addTo(map);
    } else {
      tooltip.remove();
    }
  }

  map.on('load', () => {
    map.addSource('sketch', {type: 'geojson', data: EMPTY_COLLECTION});
    map.addLayer({
      id: 'sketch-fill',
      type: 'fill',
      source: 'sketch',
      filter: ['==', ['geometry-type'], 'Polygon'],
      paint: {'fill-color': 'rgba(226, 19, 110, 0.08)'},
    });
    map.addLayer({
      id: 'sketch-line',
      type: 'line',
      source: 'sketch',
      filter: ['!=', ['geometry-type'], 'Point'],
      paint: {'line-color': DRAWING_ACCENT, 'line-width': 2, 'line-dasharray': [3, 2]},
    });
    map.addLayer({
      id: 'sketch-vertices',
      type: 'circle',
      source: 'sketch',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {'circle-radius': 4, 'circle-color': DRAWING_ACCENT},
    });
    render();
  });

  const nearScreen = (a: LonLat, b: LonLat) => {
    const pa = map.project(a);
    const pb = map.project(b);
    return Math.hypot(pa.x - pb.x, pa.y - pb.y) <= FINISH_TOLERANCE_PX;
  };

  /** Keeps the sketch if it is a shape, snapped onto the share grid; drops it otherwise. */
  function finish(): void {
    const minimum = mode === 'p' ? 3 : 2;
    if (mode && sketch.length >= minimum) {
      drawings.push({t: mode, c: sketch.map(snapToShareGrid)});
      render();
      emitChange();
    }
    sketch = [];
    pointer = undefined;
    renderSketch();
  }

  function onClick(event: MapMouseEvent): void {
    const point: LonLat = [event.lngLat.lng, event.lngLat.lat];
    const last = sketch[sketch.length - 1];
    // Clicking the last vertex again finishes, as does closing a polygon on its first one.
    if (last && sketch.length >= 2 && nearScreen(point, last)) {
      finish();
      return;
    }
    if (mode === 'p' && sketch.length >= 3 && nearScreen(point, sketch[0])) {
      finish();
      return;
    }
    sketch.push(point);
    renderSketch();
  }

  function onMove(event: MapMouseEvent): void {
    if (sketch.length > 0) {
      pointer = [event.lngLat.lng, event.lngLat.lat];
      renderSketch();
    }
  }

  function onDoubleClick(event: MapMouseEvent): void {
    // The first click of the pair has finished the sketch already, and the second started a new
    // one on the same spot -- which is dropped here for having a single vertex.
    event.preventDefault();
    finish();
  }

  function setMode(next: DrawingType | null): void {
    sketch = [];
    pointer = undefined;
    map.off('click', onClick);
    map.off('mousemove', onMove);
    map.off('dblclick', onDoubleClick);
    mode = next;
    if (mode) {
      map.on('click', onClick);
      map.on('mousemove', onMove);
      map.on('dblclick', onDoubleClick);
      map.doubleClickZoom.disable();
      map.getCanvas().style.cursor = 'crosshair';
    } else {
      map.doubleClickZoom.enable();
      map.getCanvas().style.cursor = '';
    }
    renderSketch();
    modeListeners.forEach((listener) => listener(mode));
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mode) {
      setMode(null);
    }
  });

  return {
    setMode,
    getMode: () => mode,
    onModeChange: (listener) => modeListeners.add(listener),
    onChange: (listener) => changeListeners.add(listener),

    getDrawings: () => drawings.map((drawing) => ({t: drawing.t, c: [...drawing.c]})),

    setDrawings: (next) => {
      drawings = next.map((drawing) => ({t: drawing.t, c: drawing.c.map(snapToShareGrid)}));
      render();
    },

    undo: () => {
      if (drawings.length > 0) {
        drawings.pop();
        render();
        emitChange();
      }
    },

    clear: () => {
      if (drawings.length > 0) {
        drawings = [];
        render();
        emitChange();
      }
    },

    collections,

    // Units and decimal separators are language dependent, so the labels have to be re-rendered
    // when the language changes.
    refresh: render,
  };
}
