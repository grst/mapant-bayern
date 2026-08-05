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

/**
 * Output density. 300 dpi is where the archive itself runs out of detail: at
 * 1:10 000 it asks for 0.85 m per pixel, and the z18 tiles hold about 0.4 m.
 */
const DPI = 300;

/** OpenLayers styles (fonts, stroke widths) are expressed in CSS pixels. */
const CSS_DPI = 96;

const MM_PER_INCH = 25.4;

/** Strip of paper kept free at the bottom for the scale and the copyright notices. */
const FOOTER_MM = 7;

/** Millimetres of paper the map itself covers. */
export function mapSizeMm(orientation: Orientation): [number, number] {
  const [width, height] = PAPER_MM[orientation];
  return [width, height - FOOTER_MM];
}

/** Size of the map area in CSS pixels – what the view resolution is relative to. */
function mapSizePx(orientation: Orientation): [number, number] {
  const [width, height] = mapSizeMm(orientation);
  return [Math.round((width / MM_PER_INCH) * CSS_DPI), Math.round((height / MM_PER_INCH) * CSS_DPI)];
}

/**
 * View resolution that puts the map on paper at exactly 1:scale.
 *
 * One CSS pixel is 1/96 inch of paper, which at 1:scale is `scale/96` inches of
 * ground. EPSG:3857 metres shrink towards the poles, so that ground distance has
 * to be divided by the local distortion to get projected units.
 */
export function resolutionForScale(scale: number, center: Coordinate): number {
  const projection = getProjection('EPSG:3857');
  const groundMetresPerPixel = ((MM_PER_INCH / CSS_DPI) * scale) / 1000;
  const distortion = projection ? getPointResolution(projection, 1, center) : 1;
  return groundMetresPerPixel / distortion;
}

/** The ground area a print would cover, for the preview rectangle. */
export function printExtent(center: Coordinate, scale: number, orientation: Orientation): Extent {
  const resolution = resolutionForScale(scale, center);
  const [width, height] = mapSizePx(orientation);
  const halfWidth = (width / 2) * resolution;
  const halfHeight = (height / 2) * resolution;
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

export interface PrintRequest {
  scale: number;
  orientation: Orientation;
  center: Coordinate;
  /** Fresh layers for the print map – layers cannot be shared between maps. */
  layers: BaseLayer[];
  /** Plain-text copyright notices for the footer. */
  attribution: string;
  fileName: string;
}

/** Rendering a full page of tiles can take a while; don't wait forever. */
const RENDER_TIMEOUT_MS = 180_000;

/**
 * Renders the print area into an off-screen map at print density and saves it as
 * a PDF. Everything happens in the browser: a second map is built at the paper's
 * pixel size with `pixelRatio` set from the target DPI, so labels and line widths
 * keep the proportions they have on screen while tiles are fetched at a zoom
 * level fine enough for 300 dpi.
 */
export async function exportPdf(request: PrintRequest): Promise<void> {
  const {orientation, scale, center} = request;
  const [mapWidthMm, mapHeightMm] = mapSizeMm(orientation);
  const [widthPx, heightPx] = mapSizePx(orientation);

  const container = document.createElement('div');
  container.className = 'print-map';
  container.style.width = `${widthPx}px`;
  container.style.height = `${heightPx}px`;
  document.body.append(container);

  const map = new Map({
    target: container,
    pixelRatio: DPI / CSS_DPI,
    controls: [],
    interactions: [],
    layers: request.layers,
    view: new View({
      center,
      resolution: resolutionForScale(scale, center),
      enableRotation: false,
      // The view must not snap the resolution: it is what fixes the scale.
      constrainResolution: false,
    }),
  });

  try {
    await renderComplete(map);
    // Read the canvases back in the same task, before anything else can render.
    const pixelRatio = DPI / CSS_DPI;
    const canvas = flattenLayers(container, Math.round(widthPx * pixelRatio), Math.round(heightPx * pixelRatio), pixelRatio);

    // Loaded on demand: jsPDF is bigger than the rest of the app put together.
    const {jsPDF} = await import('jspdf');
    const pdf = new jsPDF({orientation, unit: 'mm', format: 'a4', compress: true});
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
 * The example composites at pixelRatio 1, where a layer canvas maps 1:1 onto the
 * output. Here it does not: the canvas layers are `pixelRatio` times bigger than
 * their CSS box and carry a matching down-scale in their CSS transform, while the
 * WebGL canvas is stretched to its box by CSS instead. Both are handled by going
 * through the canvas' layout size:
 *
 *   device transform = scale(pixelRatio) · cssTransform · scale(boxSize / canvasSize)
 */
function flattenLayers(
  container: HTMLElement,
  width: number,
  height: number,
  pixelRatio: number,
): HTMLCanvasElement {
  const target = document.createElement('canvas');
  target.width = width;
  target.height = height;
  const context = target.getContext('2d');
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
    context.setTransform(
      pixelRatio * a * boxScaleX,
      pixelRatio * b * boxScaleX,
      pixelRatio * c * boxScaleY,
      pixelRatio * d * boxScaleY,
      pixelRatio * e,
      pixelRatio * f,
    );
    context.drawImage(canvas, 0, 0);
  });

  context.globalAlpha = 1;
  context.setTransform(1, 0, 0, 1, 0, 0);
  return target;
}
