import {Map, type StyleSpecification} from 'maplibre-gl';
import {HALF_WORLD, mercatorDistortion, toLonLat, type XY} from './geo';
import {formatNumber} from './i18n';
import {provideIsomIcons, rasterizeIsomIcons} from './isomstyle';

/** Paper size in millimetres. A4 only – anything else is a rare need for a map. */
const PAPER_MM = {portrait: [210, 297], landscape: [297, 210]} as const;

export type Orientation = keyof typeof PAPER_MM;

/** The scales orienteering maps are actually printed at. */
export const SCALES = [4000, 7500, 10000, 15000] as const;

/** Style sizes (fonts, line widths) are CSS pixels, 96 to the inch. */
const CSS_DPI = 96;

const MM_PER_INCH = 25.4;

/** Strip of paper kept free at the bottom for the scale and the copyright notices. */
const FOOTER_MM = 7;

/**
 * Output density, in descending order of preference. 600 dpi is what a map wants
 * and what a modern laser printer puts on paper; at A4 it is a canvas of 34
 * million pixels, which Chrome and Firefox allocate but Safari – capped at about
 * 16.7 million – does not. 400 dpi is the finest A4 page that stays under that
 * cap, and 300 dpi the last resort.
 */
const DENSITIES_DPI = [600, 400, 300] as const;

/** Millimetres of paper the map itself covers. */
export function mapSizeMm(orientation: Orientation): [number, number] {
  const [width, height] = PAPER_MM[orientation];
  return [width, height - FOOTER_MM];
}

/**
 * Whether the browser really hands out a canvas of this size. Over the limit,
 * Safari does not throw – it ignores every drawing operation, which would turn
 * into a blank page – so this writes a pixel and reads it back.
 */
function canvasFits(width: number, height: number): boolean {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  let usable = false;
  if (context) {
    context.fillStyle = '#ffffff';
    context.fillRect(width - 1, height - 1, 1, 1);
    const [red, , , alpha] = context.getImageData(width - 1, height - 1, 1, 1).data;
    usable = red === 255 && alpha === 255;
  }
  // Hand the memory back before the print map asks for canvases of its own.
  canvas.width = 0;
  canvas.height = 0;
  return usable;
}

/**
 * The largest drawing buffer WebGL will hand out along either axis. Over it, the browser shrinks
 * the buffer without a word and stretches the result, which would be a blurred page.
 */
function webglLimit(): number {
  const gl = document.createElement('canvas').getContext('webgl2');
  if (!gl) {
    return 4096;
  }
  const dims = gl.getParameter(gl.MAX_VIEWPORT_DIMS) as Int32Array;
  const limit = Math.min(gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) as number, dims[0], dims[1]);
  gl.getExtension('WEBGL_lose_context')?.loseContext();
  return limit;
}

/** The finest density this browser will render a full page at. */
function dpiForPaper(orientation: Orientation, glLimit: number): number {
  const usable = DENSITIES_DPI.find((dpi) => {
    const [width, height] = mapSizePx(orientation, dpi);
    return Math.max(width, height) + dpi / CSS_DPI < glLimit && canvasFits(width, height);
  });
  if (!usable) {
    console.warn('Printing at the lowest density: this browser has a small canvas limit');
    return DENSITIES_DPI[DENSITIES_DPI.length - 1];
  }
  return usable;
}

/** Size of the map area in output pixels at a given density. */
function mapSizePx(orientation: Orientation, dpi: number): [number, number] {
  const [width, height] = mapSizeMm(orientation);
  return [Math.round((width / MM_PER_INCH) * dpi), Math.round((height / MM_PER_INCH) * dpi)];
}

/** Ground metres per EPSG:3857 unit at a point: web mercator stretches towards the poles. */
function distortionAt(center: XY): number {
  return mercatorDistortion(center);
}

/**
 * View resolution, in EPSG:3857 units per pixel, that puts the map on paper at exactly 1:scale for
 * a map rendered at `dpi`.
 *
 * One pixel is 1/dpi inch of paper, which at 1:scale is `scale/dpi` inches of
 * ground; the distortion turns that ground distance into projected units.
 */
export function resolutionForScale(scale: number, center: XY, dpi = CSS_DPI): number {
  const groundMetresPerPixel = ((MM_PER_INCH / dpi) * scale) / 1000;
  return groundMetresPerPixel / distortionAt(center);
}

/** MapLibre's zoom for a resolution in EPSG:3857 units per CSS pixel: zoom 0 is one 512 px world. */
export function zoomForResolution(resolution: number): number {
  return Math.log2((2 * HALF_WORLD) / 512 / resolution);
}

/** The ground area a print would cover, as [minX, minY, maxX, maxY] in EPSG:3857. */
export function printExtent(center: XY, scale: number, orientation: Orientation): [number, number, number, number] {
  const [widthM, heightM] = printGroundSize(scale, orientation);
  const distortion = distortionAt(center);
  const halfWidth = widthM / 2 / distortion;
  const halfHeight = heightM / 2 / distortion;
  return [center[0] - halfWidth, center[1] - halfHeight, center[0] + halfWidth, center[1] + halfHeight];
}

/** The same area as a closed lon/lat ring, for the preview rectangle. */
export function printOutline(center: XY, scale: number, orientation: Orientation): [number, number][] {
  const [minX, minY, maxX, maxY] = printExtent(center, scale, orientation);
  const corners: XY[] = [
    [minX, minY],
    [maxX, minY],
    [maxX, maxY],
    [minX, maxY],
    [minX, minY],
  ];
  return corners.map(toLonLat);
}

/** Ground size of a print in metres, e.g. to show "2.0 × 2.8 km" in the UI. */
export function printGroundSize(scale: number, orientation: Orientation): [number, number] {
  const [width, height] = mapSizeMm(orientation);
  return [(width * scale) / 1000, (height * scale) / 1000];
}

export interface PrintRequest {
  scale: number;
  orientation: Orientation;
  /** Centre of the print area, in EPSG:3857. */
  center: XY;
  /** The style for the print map: the live map's, reading the deepest tiles. */
  style: StyleSpecification;
  showTileBoundaries: boolean;
  /** Plain-text copyright notices for the footer. */
  attribution: string;
  fileName: string;
}

/**
 * Rendering a full page can take a while – it is up to a hundred of the pyramid's deepest tiles,
 * some tens of MB – but don't wait forever.
 */
const RENDER_TIMEOUT_MS = 300_000;

/**
 * Renders the print area into an off-screen map at print density and saves it as a PDF.
 * Everything happens in the browser.
 *
 * The print map is laid out at the paper's size in CSS pixels, at the zoom that puts it at the
 * requested scale, and drawn at `pixelRatio = dpi / 96`. Being vector tiles, the map is drawn anew
 * at that density rather than magnified, and every size the styles give in CSS pixels -- line
 * widths, symbols, labels -- comes out on paper at the size it has on screen. What a pixel ratio
 * does not change is which tiles MapLibre reads, so the print style declares them smaller than
 * they are (`StyleOptions.print`): the page is drawn from the pyramid's deepest level.
 */
export async function exportPdf(request: PrintRequest): Promise<void> {
  const {orientation, scale, center} = request;
  const [mapWidthMm, mapHeightMm] = mapSizeMm(orientation);
  const glLimit = webglLimit();
  const dpi = dpiForPaper(orientation, glLimit);
  const [widthPx, heightPx] = mapSizePx(orientation, dpi);
  const pixelRatio = dpi / CSS_DPI;
  // Whole CSS pixels, rounded up: the canvas is then at least the page, and the page is cut from
  // its middle. Stretching it to fit instead would put the print off its scale by up to a pixel.
  const cssWidth = Math.ceil(widthPx / pixelRatio);
  const cssHeight = Math.ceil(heightPx / pixelRatio);

  const container = document.createElement('div');
  container.className = 'print-map';
  container.style.width = `${cssWidth}px`;
  container.style.height = `${cssHeight}px`;
  document.body.append(container);

  // Ready before the map exists, so its first render finds every pattern it asks for.
  const icons = await rasterizeIsomIcons(pixelRatio);
  const map = new Map({
    container,
    style: request.style,
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
  provideIsomIcons(map, icons);
  map.showTileBoundaries = request.showTileBoundaries;

  try {
    await renderComplete(map);
    const canvas = cropToPage(map.getCanvas(), cssWidth, widthPx / pixelRatio, heightPx / pixelRatio, widthPx, heightPx);

    // Loaded on demand: jsPDF is bigger than the rest of the app put together.
    const {jsPDF} = await import('jspdf');
    const pdf = new jsPDF({orientation, unit: 'mm', format: 'a4', compress: true});
    // jsPDF decodes the PNG and deflates the samples itself, and its setting picks
    // a row filter along with the deflate level. 'FAST' is no compromise on a page
    // of these flat map colours – measured on a 1:10 000 A4 page, it came out both
    // the quickest and the smallest: 28 MB in 7 s, against 30 MB in 9 s for
    // 'MEDIUM' and 25 MB in 26 s for 'SLOW'.
    pdf.addImage(canvas.toDataURL('image/png'), 'PNG', 0, 0, mapWidthMm, mapHeightMm, undefined, 'FAST');

    pdf.setFontSize(7);
    pdf.setTextColor(70);
    pdf.text(`1:${formatNumber(scale)}`, 4, mapHeightMm + 4.6);
    pdf.text(request.attribution, mapWidthMm - 4, mapHeightMm + 4.6, {align: 'right'});

    pdf.save(request.fileName);
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

/**
 * The page, cut from the middle of the map's canvas onto an opaque one of exactly the page's
 * pixels. The canvas is normally at the requested pixel ratio; should MapLibre have lowered it to
 * stay within the canvas limit, the cut is scaled to match rather than coming out too small.
 */
function cropToPage(
  source: HTMLCanvasElement,
  cssWidth: number,
  pageCssWidth: number,
  pageCssHeight: number,
  width: number,
  height: number,
): HTMLCanvasElement {
  const target = document.createElement('canvas');
  target.width = width;
  target.height = height;
  // Opaque: the page has no transparency to keep, and it saves jsPDF from taking
  // the picture apart into colour and mask channels.
  const context = target.getContext('2d', {alpha: false});
  if (!context) {
    throw new Error('Could not create the print canvas');
  }
  // White, so transparent areas outside the map's coverage do not print as black.
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, width, height);

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
    width,
    height,
  );
  return target;
}
