import Map from 'ol/Map';
import View from 'ol/View';
import {fromExtent} from 'ol/geom/Polygon';
import {get as getProjection, getPointResolution} from 'ol/proj';
import type BaseLayer from 'ol/layer/Base';
import type {Coordinate} from 'ol/coordinate';
import type {Extent} from 'ol/extent';
import type Polygon from 'ol/geom/Polygon';
import {formatNumber} from './i18n';

/** Paper size in millimetres. A4 only – anything else is a rare need for a map. */
const PAPER_MM = {portrait: [210, 297], landscape: [297, 210]} as const;

export type Orientation = keyof typeof PAPER_MM;

/** The scales orienteering maps are actually printed at. */
export const SCALES = [4000, 7500, 10000, 15000] as const;

/** OpenLayers styles (fonts, stroke widths) are expressed in CSS pixels. */
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

/** The finest density this browser will render a full page at. */
function dpiForPaper(orientation: Orientation): number {
  const usable = DENSITIES_DPI.find((dpi) => canvasFits(...mapSizePx(orientation, dpi)));
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

/** EPSG:3857 metres shrink towards the poles; one metre of ground is this many. */
function distortionAt(center: Coordinate): number {
  const projection = getProjection('EPSG:3857');
  return projection ? getPointResolution(projection, 1, center) : 1;
}

/**
 * View resolution that puts the map on paper at exactly 1:scale, for a map
 * rendered at `dpi` with one canvas pixel per pixel of output.
 *
 * One pixel is 1/dpi inch of paper, which at 1:scale is `scale/dpi` inches of
 * ground; the distortion turns that ground distance into projected units.
 */
export function resolutionForScale(scale: number, center: Coordinate, dpi = CSS_DPI): number {
  const groundMetresPerPixel = ((MM_PER_INCH / dpi) * scale) / 1000;
  return groundMetresPerPixel / distortionAt(center);
}

/** The ground area a print would cover, for the preview rectangle. */
export function printExtent(center: Coordinate, scale: number, orientation: Orientation): Extent {
  const [widthM, heightM] = printGroundSize(scale, orientation);
  const distortion = distortionAt(center);
  const halfWidth = widthM / 2 / distortion;
  const halfHeight = heightM / 2 / distortion;
  return [center[0] - halfWidth, center[1] - halfHeight, center[0] + halfWidth, center[1] + halfHeight];
}

export function printOutline(center: Coordinate, scale: number, orientation: Orientation): Polygon {
  return fromExtent(printExtent(center, scale, orientation));
}

/** Ground size of a print in metres, e.g. to show "2.0 × 2.8 km" in the UI. */
export function printGroundSize(scale: number, orientation: Orientation): [number, number] {
  const [width, height] = mapSizeMm(orientation);
  return [(width * scale) / 1000, (height * scale) / 1000];
}

/** What the print map's layers have to know about the paper they draw on. */
export interface PrintLayerOptions {
  /**
   * Factor for style sizes given in CSS pixels. The print map renders one canvas
   * pixel per pixel of output, so fonts, stroke widths and symbol radii have to
   * be scaled up by hand to keep the size they have on screen.
   */
  styleScale: number;
  /**
   * The view resolution this scale corresponds to on screen. Anything that keys
   * off the view resolution – which on the print map is `styleScale` times finer
   * than what the paper shows – can use it to stay in step with the screen.
   */
  screenResolution: number;
  /**
   * Tiles a layer has to keep at once. A page at 600 dpi covers upwards of six
   * hundred tiles, well past the 512 OpenLayers caches by default, and a cache
   * that cannot hold the page evicts tiles that are still being waited for.
   */
  tileCacheSize: number;
}

export interface PrintRequest {
  scale: number;
  orientation: Orientation;
  center: Coordinate;
  /** Fresh layers for the print map – layers cannot be shared between maps. */
  createLayers(options: PrintLayerOptions): BaseLayer[];
  /** Plain-text copyright notices for the footer. */
  attribution: string;
  fileName: string;
}

/**
 * Rendering a full page of tiles can take a while – it is upwards of six hundred
 * of them, around 20 MB – but don't wait forever.
 */
const RENDER_TIMEOUT_MS = 300_000;

/**
 * Renders the print area into an off-screen map at print density and saves it as
 * a PDF. Everything happens in the browser: a second map is built whose viewport
 * is the paper measured in output pixels, at `pixelRatio` 1.
 *
 * The pixel ratio is what decides how sharp the result is. OpenLayers picks the
 * tile zoom level from the view resolution alone and then blows the tiles up by
 * the pixel ratio, so a print map at `pixelRatio = dpi/96` fetches the tiles a
 * screen would use and magnifies them – a page of any density carrying 96 dpi of
 * map. One canvas pixel per pixel of output instead means the zoom level is chosen
 * for the paper. The price is that CSS-pixel style sizes no longer scale by
 * themselves, so the layers are asked to scale them (`PrintLayerOptions`).
 */
export async function exportPdf(request: PrintRequest): Promise<void> {
  const {orientation, scale, center} = request;
  const [mapWidthMm, mapHeightMm] = mapSizeMm(orientation);
  const dpi = dpiForPaper(orientation);
  const [widthPx, heightPx] = mapSizePx(orientation, dpi);
  const styleScale = dpi / CSS_DPI;
  // Room for the page itself even when a layer's tiles are twice as fine as the
  // page along each axis, plus a margin for the row and column that overlap it.
  const tileCacheSize = 4 * Math.ceil((widthPx / 256 + 1) * (heightPx / 256 + 1));

  const container = document.createElement('div');
  container.className = 'print-map';
  container.style.width = `${widthPx}px`;
  container.style.height = `${heightPx}px`;
  document.body.append(container);

  const map = new Map({
    target: container,
    pixelRatio: 1,
    controls: [],
    interactions: [],
    layers: request.createLayers({
      styleScale,
      screenResolution: resolutionForScale(scale, center),
      tileCacheSize,
    }),
    view: new View({
      center,
      resolution: resolutionForScale(scale, center, dpi),
      enableRotation: false,
      // The view must not snap the resolution: it is what fixes the scale.
      constrainResolution: false,
    }),
  });

  try {
    await renderComplete(map);
    // Read the canvases back in the same task, before anything else can render.
    const canvas = flattenLayers(container, widthPx, heightPx);

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
    map.setTarget(undefined);
    map.dispose();
    container.remove();
  }
}

function renderComplete(map: Map): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      console.warn('Print rendering timed out; exporting what has loaded so far');
      resolve();
    }, RENDER_TIMEOUT_MS);
    map.once('rendercomplete', () => {
      window.clearTimeout(timer);
      resolve();
    });
  });
}

/**
 * Composites every layer canvas of a map into one, in the spirit of the
 * OpenLayers "Export PDF" example (the WebGL layers keep their drawing buffer, so
 * they can be read back here).
 *
 * The print map renders at pixelRatio 1, so a layer canvas maps 1:1 onto the
 * output – except that a layer may carry a CSS transform, and a WebGL canvas is
 * sized by its drawing buffer and stretched to its box by CSS. Both are handled
 * by going through the canvas' layout size:
 *
 *   output transform = cssTransform · scale(boxSize / canvasSize)
 */
function flattenLayers(container: HTMLElement, width: number, height: number): HTMLCanvasElement {
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

  container.querySelectorAll<HTMLCanvasElement>('.ol-layer canvas, canvas.ol-layer').forEach((canvas) => {
    if (canvas.width === 0 || canvas.height === 0) {
      return;
    }
    const parent = canvas.parentNode as HTMLElement | null;
    const opacity = (parent?.style.opacity || canvas.style.opacity) as string;
    context.globalAlpha = opacity === '' ? 1 : Number(opacity);

    // CSS pixels per canvas pixel. offsetWidth is the layout size, i.e. before
    // the CSS transform is applied.
    const boxScaleX = (canvas.offsetWidth || canvas.width) / canvas.width;
    const boxScaleY = (canvas.offsetHeight || canvas.height) / canvas.height;
    const matrix = canvas.style.transform.match(/^matrix\(([^(]*)\)$/);
    const [a, b, c, d, e, f] = matrix ? matrix[1].split(',').map(Number) : [1, 0, 0, 1, 0, 0];
    context.setTransform(a * boxScaleX, b * boxScaleX, c * boxScaleY, d * boxScaleY, e, f);
    context.drawImage(canvas, 0, 0);
  });

  context.globalAlpha = 1;
  context.setTransform(1, 0, 0, 1, 0, 0);
  return target;
}
