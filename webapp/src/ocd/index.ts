/**
 * Export the print area as an editable OCAD file.
 *
 * The whole conversion happens in the browser, from the same vector tiles the map is drawn from:
 * read the tiles covering the print rectangle at the deepest zoom (vector/area.ts), spell each
 * feature's ISOM code the way the symbol set does, and write an OCD 12 file around a template that
 * supplies the symbol set.
 *
 * What goes in is chosen by feature group (vector/groups.ts): as objects to edit, and as a
 * background map to trace from. An OCD file cannot hold an image -- a background map is a file of
 * its own that the OCD names and places, in a parameter string of type 8 -- so a background map is
 * a georeferenced PNG beside it: drawn in the map's style, in the file's own projected system, with
 * a world file for any program that reads one. The OCD names it without a folder, so OCAD and
 * OpenOrienteering Mapper find it next to the file.
 */

import {canvasFits, MM_PER_INCH, printExtent, type Orientation} from '../print';
import {drawIsom} from '../render/isom';
import {CanvasSurface} from '../render/surface';
import {areaFeatures, readTiles, type MapFeature} from '../vector/area';
import {groupOf, type FeatureGroup} from '../vector/groups';
import type {VectorSource} from '../vector/source';
import type {Rect, XY} from '../vector/tiles';
import {symbolFor, type Symbolisation} from './isom';
import {
  OBJECT_TYPE_AREA,
  OBJECT_TYPE_LINE,
  OBJECT_TYPE_POINT,
  STRING_TYPE_BACKGROUND_MAP,
  writeOcd,
  type GeorefOptions,
  type OcdObject,
  type ParameterString,
} from './ocdwriter';
import {toProjected} from './proj';

export interface OcdExportRequest {
  /** Centre of the print area, in EPSG:3857, as the map view has it. */
  center: XY;
  scale: number;
  orientation: Orientation;
  source: VectorSource;
  /** An OCD file holding the symbol set and colours to build on. */
  template: ArrayBuffer;
  /** Projected CRS to georeference the map in, and OCAD's code for it. */
  crs: string;
  gridZone: number;
  /** The groups written as objects. */
  objects: ReadonlySet<FeatureGroup>;
  /** The groups drawn into the background map; none for no background map. */
  background: ReadonlySet<FeatureGroup>;
  /** The files' name, without extension. */
  name: string;
}

export interface ExportFile {
  name: string;
  data: Uint8Array;
}

export interface OcdExportResult {
  /** The OCD file, and the background map's image and world file if there is one. */
  files: ExportFile[];
  objects: number;
  /** Tiles with map data under the area: none means there is no map there. */
  tiles: number;
  /** Codes that had no symbol in the template, and how many objects were dropped with them. */
  skipped: Map<string, number>;
  /** Tiles that were not readable as vector tiles; see vector/area.ts. */
  unreadable: number;
}

/** 0.01 mm units per millimetre of paper. */
const PAPER_UNITS_PER_MM = 100;

/**
 * Density of the background map, in descending order of preference: 300 dpi is as fine as a
 * scan one would trace from, and an A4 page at it is 9 million pixels, under Safari's canvas cap.
 */
const BACKGROUND_DPI = [300, 200] as const;

export async function exportOcd(request: OcdExportRequest): Promise<OcdExportResult> {
  const {center, scale, orientation, source, template, crs, gridZone, name} = request;
  const [minX, minY, maxX, maxY] = printExtent(center, scale, orientation);
  const area: Rect = {minX, minY, maxX, maxY};

  const originProjected = toProjected(crs, center);
  const origin: XY = [Math.round(originProjected[0]), Math.round(originProjected[1])];
  /** EPSG:3857 to millimetres of paper, y up as in an OCD file and as northing runs. */
  const toPaperMm = (point: XY): XY => {
    const [easting, northing] = toProjected(crs, point);
    // Ground metres to millimetres of paper is a division by the scale.
    return [((easting - origin[0]) * 1000) / scale, ((northing - origin[1]) * 1000) / scale];
  };
  const toPaper = (point: XY): [number, number] => {
    const [x, y] = toPaperMm(point);
    return [x * PAPER_UNITS_PER_MM, y * PAPER_UNITS_PER_MM];
  };

  const tiles = await readTiles(source, area);

  const objects: OcdObject[] = [];
  if (request.objects.size > 0) {
    for (const feature of areaFeatures(tiles, area)) {
      const group = groupOf(feature);
      if (group && request.objects.has(group)) {
        const object = toObject(feature, toPaper);
        if (object) {
          objects.push(object);
        }
      }
    }
  }

  const georef: GeorefOptions = {scale, easting: origin[0], northing: origin[1], gridZone};
  const files: ExportFile[] = [];
  const strings: ParameterString[] = [];
  if (request.background.size > 0 && tiles.tiles.length > 0) {
    const features = areaFeatures(tiles, area, {buffered: true}).filter((feature) => {
      const group = groupOf(feature);
      return group !== null && request.background.has(group);
    });
    const corners: XY[] = [
      [minX, minY],
      [maxX, minY],
      [maxX, maxY],
      [minX, maxY],
    ];
    const background = await renderBackground(features, scale, corners.map(toPaperMm), toPaperMm);
    const image = `${name}_background.png`;
    files.push(
      {name: image, data: background.png},
      {name: `${name}_background.pgw`, data: new TextEncoder().encode(worldFile(background, georef))},
    );
    strings.push({type: STRING_TYPE_BACKGROUND_MAP, text: backgroundMapString(image, background)});
  }

  const {file, written, skipped} = writeOcd(template, objects, georef, strings);
  files.unshift({name: `${name}.ocd`, data: file});
  return {files, objects: written, tiles: tiles.tiles.length, skipped, unreadable: tiles.unreadable};
}

function toObject(feature: MapFeature, toPaper: (point: XY) => [number, number]): OcdObject | null {
  const {geometry} = feature;
  const symbol = symbolFor(feature.properties, geometry.kind);
  if (!symbol) {
    return null;
  }
  if (geometry.kind === 'point') {
    return {code: symbol.code, type: OBJECT_TYPE_POINT, rings: [[toPaper(geometry.point)]]};
  }
  if (geometry.kind === 'line') {
    return symbol.type === OBJECT_TYPE_POINT
      ? pointFromLine(symbol, geometry.line, toPaper)
      : {code: symbol.code, type: OBJECT_TYPE_LINE, rings: [geometry.line.map(toPaper)]};
  }
  return {code: symbol.code, type: OBJECT_TYPE_AREA, rings: geometry.rings.map((ring) => ring.map(toPaper))};
}

/**
 * The point symbol a short line stands for: karttapullautin draws a slope line as a tick from the
 * contour downhill, and ISOM's symbol for it is a rotatable point.
 */
function pointFromLine(
  symbol: Symbolisation,
  line: XY[],
  toPaper: (point: XY) => [number, number],
): OcdObject {
  if (symbol.pointFrom === 'centroid') {
    const sum = line.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y] as XY, [0, 0] as XY);
    const centre: XY = [sum[0] / line.length, sum[1] / line.length];
    return {code: symbol.code, type: OBJECT_TYPE_POINT, rings: [[toPaper(centre)]]};
  }

  // On paper, where the angle is measured: the projection turns the grid against web mercator.
  const from = toPaper(line[0]);
  const to = toPaper(line[line.length - 1]);
  // OCAD turns a symbol counter-clockwise by the object's angle, from the way it is drawn in the
  // symbol: the template's slope line, 101.1, is drawn from its point straight up. So a tick that
  // runs east is turned by -90°, which is the direction from east, less 90.
  const direction = (Math.atan2(to[1] - from[1], to[0] - from[0]) * 180) / Math.PI;
  const angle = (((direction - 90) % 360) + 360) % 360;
  return {code: symbol.code, type: OBJECT_TYPE_POINT, rings: [[from]], angle};
}

interface Background {
  png: Uint8Array;
  /** The image's top left corner in millimetres of paper, y up. */
  left: number;
  top: number;
  widthPx: number;
  heightPx: number;
  mmPerPx: number;
}

/**
 * The background map: the features drawn as the map draws them, onto an image aligned with the
 * file's paper -- which is the projected grid, turned against web mercator by the meridian
 * convergence -- and covering the print area's corners there. Transparent where there is nothing.
 */
async function renderBackground(
  features: MapFeature[],
  scale: number,
  corners: XY[],
  toPaperMm: (point: XY) => XY,
): Promise<Background> {
  const left = Math.min(...corners.map(([x]) => x));
  const right = Math.max(...corners.map(([x]) => x));
  const bottom = Math.min(...corners.map(([, y]) => y));
  const top = Math.max(...corners.map(([, y]) => y));
  const size = (dpi: number): [number, number] => [
    Math.ceil(((right - left) / MM_PER_INCH) * dpi),
    Math.ceil(((top - bottom) / MM_PER_INCH) * dpi),
  ];
  const dpi = BACKGROUND_DPI.find((candidate) => canvasFits(...size(candidate))) ?? BACKGROUND_DPI[BACKGROUND_DPI.length - 1];
  const [widthPx, heightPx] = size(dpi);
  const mmPerPx = MM_PER_INCH / dpi;

  const canvas = document.createElement('canvas');
  canvas.width = widthPx;
  canvas.height = heightPx;
  const context = canvas.getContext('2d');
  if (!context) {
    throw new Error('Could not create the background map canvas');
  }
  const surface = new CanvasSurface(context, 1 / mmPerPx);
  drawIsom(
    surface,
    features,
    {
      scale,
      // Millimetres from the image's top left corner, y down.
      project: (point) => {
        const [x, y] = toPaperMm(point);
        return [x - left, top - y];
      },
    },
    [0, 0, widthPx * mmPerPx, heightPx * mmPerPx],
  );

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
  canvas.width = 0;
  canvas.height = 0;
  if (!blob) {
    throw new Error('Could not encode the background map');
  }
  return {png: new Uint8Array(await blob.arrayBuffer()), left, top, widthPx, heightPx, mmPerPx};
}

/**
 * The type-8 string placing the image on the map, as OpenOrienteering Mapper writes it for OCD
 * 11 and later (`OcdFileExport::stringForTemplate`): `x`/`y` the image's centre in millimetres of
 * paper, y up; `u`/`v` millimetres per pixel; `a`/`b` the rotation, none here, since the image is
 * already aligned with the paper; `s1` shown, `r1` among the background favourites, `d0` undimmed.
 */
function backgroundMapString(fileName: string, {left, top, widthPx, heightPx, mmPerPx}: Background): string {
  const x = left + (widthPx * mmPerPx) / 2;
  const y = top - (heightPx * mmPerPx) / 2;
  return [
    fileName,
    's1',
    'r1',
    `u${mmPerPx.toFixed(10)}`,
    `v${mmPerPx.toFixed(10)}`,
    `x${x.toFixed(6)}`,
    `y${y.toFixed(6)}`,
    'a0',
    'b0',
    'd0',
  ].join('\t');
}

/**
 * The image's world file, in the file's projected system: pixel size in metres, no rotation, and
 * the centre of the top left pixel.
 */
function worldFile({left, top, mmPerPx}: Background, {scale, easting, northing}: GeorefOptions): string {
  const metresPerMm = scale / 1000;
  const pixel = mmPerPx * metresPerMm;
  return [
    pixel,
    0,
    0,
    -pixel,
    easting + (left + mmPerPx / 2) * metresPerMm,
    northing + (top - mmPerPx / 2) * metresPerMm,
  ]
    .map((value) => value.toFixed(10))
    .join('\n')
    .concat('\n');
}

export {archiveSource} from '../vector/source';
export type {VectorSource} from '../vector/source';
