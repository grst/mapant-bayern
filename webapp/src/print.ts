/**
 * A page's geometry: the scales, the paper, and the ground a page covers at a scale. Shared by the
 * PDF (pdf.ts), the OCD export (ocd/) and the preview rectangle, and kept free of either export's
 * weight, which is loaded only when an export is asked for.
 */

import {HALF_WORLD, mercatorDistortion, toLonLat, type XY} from './geo';

/** Paper size in millimetres. A4 only – anything else is a rare need for a map. */
const PAPER_MM = {portrait: [210, 297], landscape: [297, 210]} as const;

export type Orientation = keyof typeof PAPER_MM;

/** The scales orienteering maps are actually printed at. */
export const SCALES = [4000, 7500, 10000, 15000] as const;

/** Style sizes (fonts, line widths) are CSS pixels, 96 to the inch. */
export const CSS_DPI = 96;

export const MM_PER_INCH = 25.4;

/** Strip of paper kept free at the bottom for the scale and the copyright notices. */
export const FOOTER_MM = 7;

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
export function canvasFits(width: number, height: number): boolean {
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
export function webglLimit(): number {
  const gl = document.createElement('canvas').getContext('webgl2');
  if (!gl) {
    return 4096;
  }
  const dims = gl.getParameter(gl.MAX_VIEWPORT_DIMS) as Int32Array;
  const limit = Math.min(gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) as number, dims[0], dims[1]);
  gl.getExtension('WEBGL_lose_context')?.loseContext();
  return limit;
}

/** Size of the map area in output pixels at a given density. */
export function mapSizePx(orientation: Orientation, dpi: number): [number, number] {
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
