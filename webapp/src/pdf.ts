/**
 * PDF export: the print area as a vector page.
 *
 * The orienteering map is drawn as PDF paths from the archive's vector tiles (render/isom.ts), in
 * the same ISOM style as the screen and at ISOM's symbol sizes for the scale, so the page is sharp
 * at any zoom and on any printer and stays small. The town names and the drawings are vectors and
 * text too. Only the hill shading, which is a raster by nature, is an image: rendered off screen
 * by MapLibre and laid over the map, its shadows transparent elsewhere.
 *
 * Loaded on demand, together with jsPDF: both are bigger than the rest of the app put together.
 */

import {jsPDF} from 'jspdf';
import {Map} from 'maplibre-gl';
import {fromLonLat, toLonLat, type LonLat, type XY} from './geo';
import {formatNumber} from './i18n';
import {isPrivateArea} from './isomstyle';
import {DRAWING_ACCENT, hillshadeStyle, PLACES_URL, type Visibility} from './layers';
import {
  canvasFits,
  CSS_DPI,
  mapSizeMm,
  mapSizePx,
  MM_PER_INCH,
  printExtent,
  resolutionForScale,
  webglLimit,
  zoomForResolution,
  type Orientation,
} from './print';
import {drawIsom, MM_PER_PX} from './render/isom';
import {PdfSurface, type Surface} from './render/surface';
import {areaFeatures, readTiles} from './vector/area';
import type {VectorSource} from './vector/source';

export interface PrintRequest {
  scale: number;
  orientation: Orientation;
  /** Centre of the print area, in EPSG:3857. */
  center: XY;
  source: VectorSource;
  /** The switchable layers as they are on screen: the page shows the same. */
  visible: Visibility;
  drawings: GeoJSON.FeatureCollection;
  drawingLabels: GeoJSON.FeatureCollection;
  /** Plain-text copyright notices for the footer. */
  attribution: string;
  fileName: string;
}

/**
 * Density of the hill shading, in descending order of preference. A soft raster under sharp
 * vectors needs far less than the map would: 200 dpi is a smooth gradient on paper. The lower one
 * is for a browser with a small canvas limit.
 */
const HILLSHADE_DPI = [200, 150] as const;

/** Rendering the shading for a page can take a while; don't wait forever. */
const RENDER_TIMEOUT_MS = 300_000;

export async function exportPdf(request: PrintRequest): Promise<void> {
  const {orientation, scale, center, visible} = request;
  const [mapWidth, mapHeight] = mapSizeMm(orientation);
  const [minX, minY, maxX, maxY] = printExtent(center, scale, orientation);
  const area = {minX, minY, maxX, maxY};
  const project = ([x, y]: XY): XY => [
    ((x - minX) / (maxX - minX)) * mapWidth,
    ((maxY - y) / (maxY - minY)) * mapHeight,
  ];

  // Started first: the shading is rendered by the GPU while the tiles are read and drawn.
  const hillshade = visible.hillshade ? renderHillshade(request) : null;
  const places = visible.places ? fetchPlaces() : null;

  const tiles = await readTiles(request.source, area);
  if (tiles.unreadable > 0) {
    console.warn(`PDF export: ${tiles.unreadable} tile(s) were not readable as vector tiles`);
  }
  const features = areaFeatures(tiles, area, {buffered: true});

  // Coordinates to a hundredth of a point, a 280th of a millimetre: well below what any printer
  // resolves, and a fraction of jsPDF's default sixteen digits in the file.
  const pdf = new jsPDF({orientation, unit: 'mm', format: 'a4', compress: true, floatPrecision: 2});
  const surface = new PdfSurface(pdf);
  surface.save();
  rectangle(surface, 0, 0, mapWidth, mapHeight);
  surface.clip();

  drawIsom(
    surface,
    features,
    {scale, project, include: (feature) => visible.private || !isPrivateArea(feature.properties.isom_code)},
    [0, 0, mapWidth, mapHeight],
  );

  if (hillshade) {
    pdf.addImage(await hillshade, 'PNG', 0, 0, mapWidth, mapHeight, undefined, 'FAST');
  }
  if (places) {
    drawPlaces(pdf, await places, project, [mapWidth, mapHeight]);
  }
  drawDrawings(pdf, surface, request.drawings, request.drawingLabels, project);
  surface.restore();

  pdf.setFontSize(7);
  pdf.setTextColor(70);
  pdf.setFont('helvetica', 'normal');
  pdf.text(`1:${formatNumber(scale)}`, 4, mapHeight + 4.6);
  pdf.text(latin1(request.attribution), mapWidth - 4, mapHeight + 4.6, {align: 'right'});

  pdf.save(request.fileName);
}

function rectangle(surface: Surface, x: number, y: number, width: number, height: number): void {
  surface.moveTo(x, y);
  surface.lineTo(x + width, y);
  surface.lineTo(x + width, y + height);
  surface.lineTo(x, y + height);
  surface.closePath();
}

/**
 * The PDF's built-in Helvetica covers Latin-1 (WinAnsi) only, which takes in German. Any other
 * letter loses its accents rather than turning into something else; a dash or quote outside the
 * range becomes its plain form.
 */
function latin1(text: string): string {
  return text
    .replace(/[–—]/g, '-')
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[^\u0000-ÿ]/g, (char) => char.normalize('NFD').replace(/[^\u0000-ÿ]/g, '') || '?');
}

/** Points to the map's text sizes: CSS pixels are 0.75 pt. */
const PT_PER_PX = 72 / CSS_DPI;

interface Label {
  text: string;
  at: XY;
  sizePx: number;
  bold: boolean;
  colour: string;
  haloPx: number;
  /** Lower goes first, where two would collide. */
  rank: number;
}

/**
 * Labels as the map draws them: centred on their point, a halo under each, and -- as MapLibre's
 * collision detection does -- a label left out where it would overlap one placed before it.
 */
function drawLabels(pdf: jsPDF, labels: Label[], [width, height]: [number, number], collide = true): void {
  const placed: [number, number, number, number][] = [];
  const sorted = [...labels].sort((a, b) => a.rank - b.rank);
  const fit: {label: Label; text: string}[] = [];
  for (const label of sorted) {
    const text = latin1(label.text);
    pdf.setFont('helvetica', label.bold ? 'bold' : 'normal');
    pdf.setFontSize(label.sizePx * PT_PER_PX);
    const halfWidth = pdf.getTextWidth(text) / 2 + label.haloPx * MM_PER_PX;
    const halfHeight = (label.sizePx * MM_PER_PX) / 2 + label.haloPx * MM_PER_PX;
    const [x, y] = label.at;
    const box: [number, number, number, number] = [x - halfWidth, y - halfHeight, x + halfWidth, y + halfHeight];
    if (box[2] < 0 || box[0] > width || box[3] < 0 || box[1] > height) {
      continue;
    }
    if (collide && placed.some((other) => box[0] < other[2] && other[0] < box[2] && box[1] < other[3] && other[1] < box[3])) {
      continue;
    }
    placed.push(box);
    fit.push({label, text});
  }
  // All halos first, then all text: a halo never covers a neighbour's letters.
  for (const pass of ['stroke', 'fill'] as const) {
    for (const {label, text} of fit) {
      pdf.setFont('helvetica', label.bold ? 'bold' : 'normal');
      pdf.setFontSize(label.sizePx * PT_PER_PX);
      if (pass === 'stroke') {
        pdf.setDrawColor('#ffffff');
        pdf.setLineWidth(2 * label.haloPx * MM_PER_PX);
        pdf.setLineJoin('round');
        pdf.setLineDashPattern([], 0);
      } else {
        pdf.setTextColor(label.colour);
      }
      pdf.text(text, label.at[0], label.at[1], {align: 'center', baseline: 'middle', renderingMode: pass});
    }
  }
}

interface Place {
  name: string;
  place: string;
  at: LonLat;
}

async function fetchPlaces(): Promise<Place[]> {
  const response = await fetch(PLACES_URL);
  if (!response.ok) {
    throw new Error(`${PLACES_URL}: ${response.status}`);
  }
  const collection = (await response.json()) as GeoJSON.FeatureCollection<GeoJSON.Point>;
  return collection.features.map((feature) => ({
    name: String(feature.properties?.name ?? ''),
    place: String(feature.properties?.place ?? ''),
    at: feature.geometry.coordinates as LonLat,
  }));
}

/** The town names, in the sizes and colours of the map's `places` layer (layers.ts). */
function drawPlaces(pdf: jsPDF, places: Place[], project: (point: XY) => XY, size: [number, number]): void {
  const rank: Record<string, number> = {city: 0, town: 1};
  drawLabels(
    pdf,
    places
      .filter((place) => place.name)
      .map((place) => ({
        text: place.name,
        at: project(fromLonLat(place.at)),
        sizePx: place.place === 'city' ? 15 : place.place === 'town' ? 13 : 12,
        bold: place.place !== 'village',
        colour: place.place === 'village' ? '#333333' : '#1b1b1b',
        haloPx: 1.75,
        rank: rank[place.place] ?? 2,
      })),
    size,
  );
}

/** The sketches and their measurements, as the map's drawing layers show them (layers.ts). */
function drawDrawings(
  pdf: jsPDF,
  surface: Surface,
  drawings: GeoJSON.FeatureCollection,
  labels: GeoJSON.FeatureCollection,
  project: (point: XY) => XY,
): void {
  const toPaper = (position: GeoJSON.Position) => project(fromLonLat([position[0], position[1]]));
  const trace = (line: GeoJSON.Position[], close: boolean) => {
    line.map(toPaper).forEach(([x, y], i) => (i === 0 ? surface.moveTo(x, y) : surface.lineTo(x, y)));
    if (close) surface.closePath();
  };
  const polygons = drawings.features.filter((feature) => feature.geometry.type === 'Polygon');
  for (const feature of polygons) {
    (feature.geometry as GeoJSON.Polygon).coordinates.forEach((ring) => trace(ring, true));
  }
  if (polygons.length > 0) {
    surface.fill(DRAWING_ACCENT, 0.12);
  }
  for (const feature of drawings.features) {
    if (feature.geometry.type === 'LineString') {
      trace(feature.geometry.coordinates, false);
    } else if (feature.geometry.type === 'Polygon') {
      feature.geometry.coordinates.forEach((ring) => trace(ring, true));
    }
  }
  if (drawings.features.length > 0) {
    surface.stroke({color: DRAWING_ACCENT, opacity: 1, width: 3 * MM_PER_PX, cap: 'round', join: 'round'});
  }
  // Above their point, as on the map (`text-offset` of -1.2 em), and never left out.
  drawLabels(
    pdf,
    labels.features
      .filter((feature) => feature.geometry.type === 'Point')
      .map((feature) => {
        const [x, y] = toPaper((feature.geometry as GeoJSON.Point).coordinates);
        return {
          text: String(feature.properties?.text ?? ''),
          at: [x, y - 1.2 * 12 * MM_PER_PX] as XY,
          sizePx: 12,
          bold: true,
          colour: '#1b1b1b',
          haloPx: 2,
          rank: 0,
        };
      }),
    [Infinity, Infinity],
    false,
  );
}

/**
 * The hill shading of the page as a PNG with transparency, rendered by an off-screen MapLibre map
 * laid out at the paper's size in CSS pixels, at the zoom of the scale, and drawn at
 * `pixelRatio = dpi / 96`.
 */
async function renderHillshade({orientation, scale, center}: PrintRequest): Promise<string> {
  const glLimit = webglLimit();
  const dpi =
    HILLSHADE_DPI.find((candidate) => {
      const [width, height] = mapSizePx(orientation, candidate);
      return Math.max(width, height) + candidate / CSS_DPI < glLimit && canvasFits(width, height);
    }) ?? HILLSHADE_DPI[HILLSHADE_DPI.length - 1];
  const [widthPx, heightPx] = mapSizePx(orientation, dpi);
  const pixelRatio = dpi / CSS_DPI;
  // Whole CSS pixels, rounded up: the canvas is then at least the page, and the page is cut from
  // its middle. Stretching it to fit instead would put the shading off the map by up to a pixel.
  const [mapWidth, mapHeight] = mapSizeMm(orientation);
  const pageCssWidth = (mapWidth / MM_PER_INCH) * CSS_DPI;
  const pageCssHeight = (mapHeight / MM_PER_INCH) * CSS_DPI;
  const cssWidth = Math.ceil(pageCssWidth);
  const cssHeight = Math.ceil(pageCssHeight);

  const container = document.createElement('div');
  container.className = 'print-map';
  container.style.width = `${cssWidth}px`;
  container.style.height = `${cssHeight}px`;
  document.body.append(container);

  const map = new Map({
    container,
    style: hillshadeStyle(),
    center: toLonLat(center),
    zoom: zoomForResolution(resolutionForScale(scale, center)),
    minZoom: 0,
    maxZoom: 24,
    pixelRatio,
    maxCanvasSize: [glLimit, glLimit],
    interactive: false,
    attributionControl: false,
    fadeDuration: 0,
    // Read back after the render, so the drawing buffer has to survive it.
    canvasContextAttributes: {preserveDrawingBuffer: true, antialias: true},
  });
  try {
    await renderComplete(map);
    const source = map.getCanvas();
    const target = document.createElement('canvas');
    target.width = widthPx;
    target.height = heightPx;
    const context = target.getContext('2d');
    if (!context) {
      throw new Error('Could not create the hill shading canvas');
    }
    // The canvas is normally at the requested pixel ratio; should MapLibre have lowered it to
    // stay within the canvas limit, the cut is scaled to match rather than coming out too small.
    const ratio = source.width / cssWidth;
    const sourceWidth = pageCssWidth * ratio;
    const sourceHeight = pageCssHeight * ratio;
    context.drawImage(
      source,
      (source.width - sourceWidth) / 2,
      (source.height - sourceHeight) / 2,
      sourceWidth,
      sourceHeight,
      0,
      0,
      widthPx,
      heightPx,
    );
    return target.toDataURL('image/png');
  } finally {
    map.remove();
    container.remove();
  }
}

/**
 * Resolves once the map has drawn everything it is going to. That is MapLibre's `idle`, which it
 * checks for only after a frame, so a last resource that settles without asking for one -- a
 * failed request does that -- would leave it never fired. The map is therefore given another frame
 * whenever it reports itself loaded and has not gone idle yet.
 */
function renderComplete(map: Map): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      window.clearTimeout(timer);
      window.clearInterval(nudge);
      resolve();
    };
    const timer = window.setTimeout(() => {
      console.warn('Print rendering timed out; exporting what has loaded so far');
      done();
    }, RENDER_TIMEOUT_MS);
    const nudge = window.setInterval(() => {
      if (map.loaded()) {
        map.triggerRepaint();
      }
    }, 500);
    map.once('idle', done);
  });
}
