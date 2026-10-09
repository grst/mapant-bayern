/**
 * Draws the orienteering map onto a Surface -- a PDF page or a canvas -- in isom-maplibre's ISOM
 * 2017-2 style, the same style the screen is drawn in, so a page looks like the map.
 *
 * The style's layers are taken as they are, in their order (the IOF colour order), with their
 * filters and paint properties evaluated by MapLibre's own expression code. What this has to
 * provide is only what MapLibre does on a GPU: fills, fill patterns, lines with dashes, circles,
 * and the one icon the style uses (the depression, 111). A layer type or property beyond that is
 * reported once and left out.
 *
 * Sizes: the style gives them in CSS pixels, and isom-maplibre generated it so that at zoom 15
 * they are ISOM's at 1:10 000 on a 96 dpi page -- a contour of 0.794 px is 0.21 mm, the standard's
 * 0.14 mm enlarged 150 % -- scaling with the ground from there, as a screen map should. A printed
 * orienteering map does not: ISOM sizes its symbols on paper, at 100 % for 1:15 000 and 150 % for
 * 1:10 000 and the larger scales a club prints. So the style is evaluated at `styleZoom(scale)`,
 * the zoom where it draws those sizes, whatever the latitude.
 */

import {featureFilter, latest, normalizePropertyExpression} from '@maplibre/maplibre-gl-style-spec';
import type {Color, FeatureFilter, StylePropertyExpression} from '@maplibre/maplibre-gl-style-spec';
import type {LayerSpecification} from 'maplibre-gl';
import {ICONS} from '@metsa/isom-maplibre';
import {isomLayers} from '../isomstyle';
import type {MapFeature} from '../vector/area';
import type {XY} from '../vector/tiles';
import type {Surface} from './surface';

/** Millimetres of paper per CSS pixel: 96 to the inch. */
export const MM_PER_PX = 25.4 / 96;

/** The zoom at which isom-maplibre draws ISOM's 1:10 000 sizes, 150 % of the standard's. */
const STYLE_ZOOM = 15;

/**
 * The zoom at which the style draws ISOM's symbols at their size on paper at 1:scale: the
 * standard's own at 1:15 000 and smaller, and the 150 % of 1:10 000 at every larger scale.
 */
export function styleZoom(scale: number): number {
  return scale >= 15_000 ? STYLE_ZOOM - Math.log2(1.5) : STYLE_ZOOM;
}

export interface IsomDrawing {
  /** The map's scale denominator. */
  scale: number;
  /** EPSG:3857 to millimetres of paper, x right and y down. */
  project(point: XY): XY;
  /** Leaves a feature off. Everything the style draws is drawn otherwise. */
  include?(feature: MapFeature): boolean;
}

type Paint = Record<string, unknown>;

interface Evaluated {
  feature: {type: number; properties: MapFeature['properties']};
  map: MapFeature;
}

const GEOMETRY_TYPE = {point: 1, line: 2, polygon: 3} as const;

const warned = new Set<string>();
function warnOnce(message: string): void {
  if (!warned.has(message)) {
    warned.add(message);
    console.warn(message);
  }
}

/** A colour as `#rrggbb` and its opacity. The style spec keeps colours premultiplied. */
function colour(value: unknown): {hex: string; alpha: number} {
  const {r, g, b, a} = value as Color;
  const channel = (c: number) =>
    Math.round(Math.min(1, a > 0 ? c / a : 0) * 255)
      .toString(16)
      .padStart(2, '0');
  return {hex: `#${channel(r)}${channel(g)}${channel(b)}`, alpha: a};
}

/**
 * One paint or layout property of a layer, evaluated at the zoom for a given feature. The style's
 * are all constant or zoom-dependent; a data-driven one is evaluated per feature all the same.
 */
function property(layer: LayerSpecification, group: 'paint' | 'layout', name: string, zoom: number) {
  const value = (layer as unknown as Record<string, Paint | undefined>)[group]?.[name];
  const spec = (latest as unknown as Record<string, Record<string, unknown>>)[`${group}_${layer.type}`]?.[name];
  if (!spec) {
    return () => undefined;
  }
  const fallback = (spec as {default?: unknown}).default;
  if (value === undefined && fallback === undefined) {
    return () => undefined;
  }
  let expression: StylePropertyExpression;
  try {
    expression = normalizePropertyExpression(value ?? fallback, `${layer.id}.${group}.${name}`, spec as never);
  } catch (error) {
    warnOnce(`${layer.id}: ${name} cannot be evaluated (${String(error)})`);
    return () => undefined;
  }
  return (feature?: Evaluated['feature']) =>
    expression.evaluate({zoom}, feature as never) as unknown;
}

/** An SVG of isom-maplibre's, as polylines in its own pixel units, with its stroke. */
interface Picture {
  width: number;
  height: number;
  lines: XY[][];
  stroke: string;
  strokeWidth: number;
}

const pictures = new Map<string, Picture | null>();

/**
 * isom-maplibre's pattern and symbol images are a single stroked path each, written with M, L,
 * H, V and A. Arcs become short polylines: a symbol is a couple of millimetres across, where a
 * sixteenth of a semicircle is far below what a printer resolves.
 */
function picture(id: string): Picture | null {
  if (pictures.has(id)) {
    return pictures.get(id)!;
  }
  const svg = (ICONS as Record<string, string>)[id];
  let result: Picture | null = null;
  if (svg) {
    const attr = (name: string) => new RegExp(`\\s${name}="([^"]*)"`).exec(svg)?.[1];
    const d = /<path[^>]*\sd="([^"]*)"/.exec(svg)?.[1] ?? '';
    const stroke = /<path[^>]*\sstroke="([^"]*)"/.exec(svg)?.[1] ?? '#000000';
    const strokeWidth = Number(/<path[^>]*\sstroke-width="([^"]*)"/.exec(svg)?.[1] ?? 1);
    result = {width: Number(attr('width')), height: Number(attr('height')), lines: parsePath(d), stroke, strokeWidth};
  }
  pictures.set(id, result);
  return result;
}

function parsePath(d: string): XY[][] {
  const tokens = d.match(/[MLHVAZ]|-?\d*\.?\d+(?:e-?\d+)?/gi) ?? [];
  const lines: XY[][] = [];
  let current: XY[] = [];
  let at: XY = [0, 0];
  let i = 0;
  const number = () => Number(tokens[i++]);
  while (i < tokens.length) {
    const command = tokens[i++];
    switch (command) {
      case 'M':
        if (current.length > 1) lines.push(current);
        at = [number(), number()];
        current = [at];
        break;
      case 'L':
        at = [number(), number()];
        current.push(at);
        break;
      case 'H':
        at = [number(), at[1]];
        current.push(at);
        break;
      case 'V':
        at = [at[0], number()];
        current.push(at);
        break;
      case 'A': {
        const [rx, ry, rotation, large, sweep, x, y] = [number(), number(), number(), number(), number(), number(), number()];
        current.push(...arc(at, [x, y], rx, ry, rotation, large === 1, sweep === 1));
        at = [x, y];
        break;
      }
      case 'Z':
      case 'z':
        if (current.length > 0) current.push(current[0]);
        break;
      default:
        warnOnce(`isom-maplibre image path command ${command} is not understood`);
        return lines;
    }
  }
  if (current.length > 1) lines.push(current);
  return lines;
}

/** An SVG elliptical arc as points, following the SVG specification's endpoint conversion. */
function arc(from: XY, to: XY, rx: number, ry: number, rotation: number, large: boolean, sweep: boolean): XY[] {
  const phi = (rotation * Math.PI) / 180;
  const [cos, sin] = [Math.cos(phi), Math.sin(phi)];
  const dx = (from[0] - to[0]) / 2;
  const dy = (from[1] - to[1]) / 2;
  const x1 = cos * dx + sin * dy;
  const y1 = -sin * dx + cos * dy;
  const lambda = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry);
  if (lambda > 1) {
    rx *= Math.sqrt(lambda);
    ry *= Math.sqrt(lambda);
  }
  const numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1;
  const factor =
    (large === sweep ? -1 : 1) *
    Math.sqrt(Math.max(0, numerator / (rx * rx * y1 * y1 + ry * ry * x1 * x1)));
  const cx1 = (factor * rx * y1) / ry;
  const cy1 = (-factor * ry * x1) / rx;
  const cx = cos * cx1 - sin * cy1 + (from[0] + to[0]) / 2;
  const cy = sin * cx1 + cos * cy1 + (from[1] + to[1]) / 2;
  const angle = (ux: number, uy: number, vx: number, vy: number) => Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
  const start = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry);
  let delta = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry);
  if (!sweep && delta > 0) delta -= 2 * Math.PI;
  if (sweep && delta < 0) delta += 2 * Math.PI;
  const steps = 16;
  const points: XY[] = [];
  for (let s = 1; s <= steps; s++) {
    const t = start + (delta * s) / steps;
    const [ex, ey] = [rx * Math.cos(t), ry * Math.sin(t)];
    points.push([cos * ex - sin * ey + cx, sin * ex + cos * ey + cy]);
  }
  return points;
}

/** The zoom an image of the style is drawn for: `isom:407@z16` for 16, the plain one for 15. */
function imageZoom(id: string): number {
  const match = /@z(\d+)$/.exec(id);
  return match ? Number(match[1]) : STYLE_ZOOM;
}

/**
 * Draws the map's features in the style's order. `bounds` is the page area in millimetres, which
 * fill patterns are laid out over.
 */
export function drawIsom(
  surface: Surface,
  features: MapFeature[],
  drawing: IsomDrawing,
  bounds: [number, number, number, number],
): void {
  const zoom = styleZoom(drawing.scale);
  const candidates: Evaluated[] = features
    .filter((feature) => !drawing.include || drawing.include(feature))
    .map((map) => ({map, feature: {type: GEOMETRY_TYPE[map.geometry.kind], properties: map.properties}}));
  const byLayer = new Map<string, Evaluated[]>();
  for (const candidate of candidates) {
    const list = byLayer.get(candidate.map.layer);
    if (list) {
      list.push(candidate);
    } else {
      byLayer.set(candidate.map.layer, [candidate]);
    }
  }
  const projected = new Map<MapFeature, XY[][]>();
  const geometryOf = (feature: MapFeature): XY[][] => {
    let rings = projected.get(feature);
    if (!rings) {
      const {geometry} = feature;
      rings =
        geometry.kind === 'point'
          ? [[drawing.project(geometry.point)]]
          : geometry.kind === 'line'
            ? [geometry.line.map(drawing.project)]
            : geometry.rings.map((ring) => ring.map(drawing.project));
      projected.set(feature, rings);
    }
    return rings;
  };

  for (const layer of isomLayers({source: 'mapant', minZoom: 0})) {
    const {minzoom = 0, maxzoom = 24} = layer as {minzoom?: number; maxzoom?: number};
    const sourceLayer = (layer as {'source-layer'?: string})['source-layer'];
    if (zoom < minzoom || zoom >= maxzoom || !sourceLayer) {
      continue;
    }
    if ((layer as {layout?: {visibility?: string}}).layout?.visibility === 'none') {
      continue;
    }
    const filter: FeatureFilter = featureFilter((layer as {filter?: unknown}).filter as never, `${layer.id}.filter`);
    const matching = (byLayer.get(sourceLayer) ?? []).filter(({feature}) => filter.filter({zoom}, feature as never));
    if (matching.length === 0) {
      continue;
    }
    switch (layer.type) {
      case 'fill':
        drawFill(surface, layer, matching, zoom, geometryOf, bounds);
        break;
      case 'line':
        drawLine(surface, layer, matching, zoom, geometryOf);
        break;
      case 'circle':
        drawCircle(surface, layer, matching, zoom, geometryOf);
        break;
      case 'symbol':
        drawIcon(surface, layer, matching, zoom, geometryOf);
        break;
      default:
        warnOnce(`${layer.id}: ${layer.type} layers are not drawn on a page`);
    }
  }
}

type GeometryOf = (feature: MapFeature) => XY[][];

/** Features grouped by what a property evaluates to for them, so each group is one paint. */
function groupBy<T>(matching: Evaluated[], key: (feature: Evaluated['feature']) => T): Map<string, {value: T; features: Evaluated[]}> {
  const groups = new Map<string, {value: T; features: Evaluated[]}>();
  for (const evaluated of matching) {
    const value = key(evaluated.feature);
    const k = JSON.stringify(value);
    const group = groups.get(k);
    if (group) {
      group.features.push(evaluated);
    } else {
      groups.set(k, {value, features: [evaluated]});
    }
  }
  return groups;
}

function tracePolygons(surface: Surface, features: Evaluated[], geometryOf: GeometryOf): [number, number, number, number] {
  const box: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const {map} of features) {
    for (const ring of geometryOf(map)) {
      ring.forEach(([x, y], i) => {
        if (i === 0) surface.moveTo(x, y);
        else surface.lineTo(x, y);
        box[0] = Math.min(box[0], x);
        box[1] = Math.min(box[1], y);
        box[2] = Math.max(box[2], x);
        box[3] = Math.max(box[3], y);
      });
      surface.closePath();
    }
  }
  return box;
}

function drawFill(
  surface: Surface,
  layer: LayerSpecification,
  matching: Evaluated[],
  zoom: number,
  geometryOf: GeometryOf,
  bounds: [number, number, number, number],
): void {
  const pattern = property(layer, 'paint', 'fill-pattern', zoom);
  const fillColour = property(layer, 'paint', 'fill-color', zoom);
  const opacity = property(layer, 'paint', 'fill-opacity', zoom);
  const groups = groupBy(matching, (feature) => {
    const image = pattern(feature) as {name?: string} | string | undefined;
    return {
      image: typeof image === 'string' ? image : image?.name,
      colour: colour(fillColour(feature)),
      opacity: Number(opacity(feature) ?? 1),
    };
  });
  for (const {value, features} of groups.values()) {
    if (!value.image) {
      tracePolygons(surface, features, geometryOf);
      surface.fill(value.colour.hex, value.colour.alpha * value.opacity);
      continue;
    }
    const image = picture(value.image);
    if (!image) {
      warnOnce(`${layer.id}: no picture for the pattern ${value.image}`);
      continue;
    }
    surface.save();
    const box = tracePolygons(surface, features, geometryOf);
    surface.clip();
    drawPattern(surface, image, (2 ** (zoom - imageZoom(value.image)) * MM_PER_PX), intersect(box, bounds), value.opacity);
    surface.restore();
  }
}

function intersect(a: number[], b: number[]): [number, number, number, number] {
  return [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.min(a[2], b[2]), Math.min(a[3], b[3])];
}

/**
 * A fill pattern tiled over a box, aligned to the page's origin so that areas next to each other
 * continue each other's stripes. A stroke that crosses its tile from edge to edge -- the stripes
 * of undergrowth and marsh -- is drawn as one line across the whole box rather than once per tile.
 */
function drawPattern(
  surface: Surface,
  image: Picture,
  mmPerUnit: number,
  [x0, y0, x1, y1]: [number, number, number, number],
  opacity: number,
): void {
  if (!(x1 > x0 && y1 > y0)) {
    return;
  }
  const width = image.width * mmPerUnit;
  const height = image.height * mmPerUnit;
  const columns = [Math.floor(x0 / width), Math.ceil(x1 / width)];
  const rows = [Math.floor(y0 / height), Math.ceil(y1 / height)];
  for (const line of image.lines) {
    const vertical = line.length === 2 && line[0][0] === line[1][0] && Math.abs(line[0][1] - line[1][1]) >= image.height;
    const horizontal = line.length === 2 && line[0][1] === line[1][1] && Math.abs(line[0][0] - line[1][0]) >= image.width;
    for (let column = columns[0]; column < columns[1]; column++) {
      const x = column * width;
      if (vertical) {
        surface.moveTo(x + line[0][0] * mmPerUnit, y0);
        surface.lineTo(x + line[0][0] * mmPerUnit, y1);
        continue;
      }
      for (let row = rows[0]; row < rows[1]; row++) {
        const y = row * height;
        if (horizontal) {
          if (column === columns[0]) {
            surface.moveTo(x0, y + line[0][1] * mmPerUnit);
            surface.lineTo(x1, y + line[0][1] * mmPerUnit);
          }
          continue;
        }
        line.forEach(([px, py], i) => {
          const point: XY = [x + px * mmPerUnit, y + py * mmPerUnit];
          if (i === 0) surface.moveTo(...point);
          else surface.lineTo(...point);
        });
      }
    }
  }
  // The pattern's colour is baked into its image.
  surface.stroke({
    color: image.stroke,
    opacity,
    width: image.strokeWidth * mmPerUnit,
    cap: 'butt',
    join: 'miter',
  });
}

function drawLine(surface: Surface, layer: LayerSpecification, matching: Evaluated[], zoom: number, geometryOf: GeometryOf): void {
  const lineColour = property(layer, 'paint', 'line-color', zoom);
  const width = property(layer, 'paint', 'line-width', zoom);
  const opacity = property(layer, 'paint', 'line-opacity', zoom);
  const dash = property(layer, 'paint', 'line-dasharray', zoom);
  const cap = property(layer, 'layout', 'line-cap', zoom);
  const join = property(layer, 'layout', 'line-join', zoom);
  const groups = groupBy(matching, (feature) => ({
    colour: colour(lineColour(feature)),
    width: Number(width(feature) ?? 1),
    opacity: Number(opacity(feature) ?? 1),
    dash: dash(feature) as number[] | undefined,
    cap: (cap(feature) ?? 'butt') as 'butt' | 'round' | 'square',
    join: (join(feature) ?? 'miter') as 'miter' | 'round' | 'bevel',
  }));
  for (const {value, features} of groups.values()) {
    if (!(value.width > 0)) {
      continue;
    }
    for (const {map} of features) {
      for (const line of geometryOf(map)) {
        line.forEach(([x, y], i) => (i === 0 ? surface.moveTo(x, y) : surface.lineTo(x, y)));
      }
    }
    const widthMm = value.width * MM_PER_PX;
    // MapLibre gives a dash pattern in line widths.
    const dashMm = value.dash?.length ? value.dash.map((d) => d * widthMm) : undefined;
    surface.stroke({
      color: value.colour.hex,
      opacity: value.colour.alpha * value.opacity,
      width: widthMm,
      dash: dashMm,
      cap: value.cap,
      join: value.join,
    });
  }
}

function drawCircle(surface: Surface, layer: LayerSpecification, matching: Evaluated[], zoom: number, geometryOf: GeometryOf): void {
  const circleColour = property(layer, 'paint', 'circle-color', zoom);
  const radius = property(layer, 'paint', 'circle-radius', zoom);
  const opacity = property(layer, 'paint', 'circle-opacity', zoom);
  const groups = groupBy(matching, (feature) => ({
    colour: colour(circleColour(feature)),
    radius: Number(radius(feature) ?? 5),
    opacity: Number(opacity(feature) ?? 1),
  }));
  for (const {value, features} of groups.values()) {
    for (const {map} of features) {
      for (const [[x, y]] of geometryOf(map)) {
        surface.circle(x, y, value.radius * MM_PER_PX);
      }
    }
    surface.fill(value.colour.hex, value.colour.alpha * value.opacity);
  }
}

/**
 * A point symbol: the icon's strokes, centred on the point, at `icon-size` times the image's own
 * size, in `icon-color` -- the style tints its symbols, which are drawn as distance fields on
 * screen. Not rotated: the style aligns them to the map, which is north up on a page.
 */
function drawIcon(surface: Surface, layer: LayerSpecification, matching: Evaluated[], zoom: number, geometryOf: GeometryOf): void {
  if ((layer as {layout?: Record<string, unknown>}).layout?.['text-field'] !== undefined) {
    warnOnce(`${layer.id}: text is not drawn on a page`);
  }
  const imageName = property(layer, 'layout', 'icon-image', zoom);
  const size = property(layer, 'layout', 'icon-size', zoom);
  const iconColour = property(layer, 'paint', 'icon-color', zoom);
  const opacity = property(layer, 'paint', 'icon-opacity', zoom);
  const groups = groupBy(matching, (feature) => {
    const image = imageName(feature) as {name?: string} | string | undefined;
    return {
      image: typeof image === 'string' ? image : image?.name,
      size: Number(size(feature) ?? 1),
      colour: colour(iconColour(feature)),
      opacity: Number(opacity(feature) ?? 1),
    };
  });
  for (const {value, features} of groups.values()) {
    const image = value.image ? picture(value.image) : null;
    if (!image) {
      warnOnce(`${layer.id}: no picture for the icon ${value.image}`);
      continue;
    }
    const mmPerUnit = value.size * MM_PER_PX;
    const [cx, cy] = [image.width / 2, image.height / 2];
    for (const {map} of features) {
      for (const [[x, y]] of geometryOf(map)) {
        for (const line of image.lines) {
          line.forEach(([px, py], i) => {
            const point: XY = [x + (px - cx) * mmPerUnit, y + (py - cy) * mmPerUnit];
            if (i === 0) surface.moveTo(...point);
            else surface.lineTo(...point);
          });
        }
      }
    }
    surface.stroke({
      color: value.colour.hex,
      opacity: value.colour.alpha * value.opacity,
      width: image.strokeWidth * mmPerUnit,
      cap: 'butt',
      join: 'round',
    });
  }
}
