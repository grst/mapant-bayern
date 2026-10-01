/**
 * The orienteering map's look: the ISOM 2017-2 style of isom-maplibre, bridged onto the tiles
 * mapant-nf publishes.
 *
 * isom-maplibre expects one vector source per table (`contours`, `vegetation_areas`, `paths`, ...)
 * whose features carry a string `isom_code` such as "403.000". mapant-nf's pyramid is one source
 * whose layers are karttapullautin's outputs (`vegetation`, `yellow`, `osm_lines`, ...), each
 * feature carrying karttapullautin's own `isom` number -- ISOM 2017-2 for the terrain, ISOM 2000
 * for the OpenStreetMap shapes. So every symbol layer of the style is repeated once per tile layer
 * that can hold its symbol, and its `["get", "isom_code"]` is replaced by a lookup that turns the
 * tile's `isom` into the code the style expects. The translation is the OCAD export's
 * (`ocd/isom.ts`), so the screen and the OCAD file agree on what everything is.
 *
 * This is a bridge: tables, `isom_code` and ISOM 2017-2 numbering could come straight out of
 * mapant-nf instead, and then this module would shrink to pointing the style at one source (see
 * HANDOFF-isom-maplibre.md in the repository root).
 */

import type {ExpressionSpecification, LayerSpecification, Map} from 'maplibre-gl';
import isomStyle from '@metsa/isom-maplibre/style.json';
import {ICONS} from '@metsa/isom-maplibre';
import {knownIsomValues, symbolFor, TILE_LAYERS} from './ocd/isom';

/**
 * isom-maplibre writes every code with three decimals, and a few ISOM variants differently from
 * OpenOrienteering Mapper, whose numbering `ocd/isom.ts` follows: a symbol whose variants the
 * style draws alike takes the plain code.
 */
const STYLE_CODES: Record<string, string> = {
  '101.1': '101.001', // slope line
  '301.1': '301.000', // uncrossable body of water, full colour
  '301.4': '301.000', // its bank line
  '501.1': '501.000', // paved area
};

function styleCode(code: string): string {
  return STYLE_CODES[code] ?? (code.includes('.') ? code : `${code}.000`);
}

/** For each tile layer, its `isom` values and the style code each becomes. */
const CODES: Record<string, [string, string][]> = Object.fromEntries(
  TILE_LAYERS.map((layer) => [
    layer,
    knownIsomValues(layer).flatMap((isom): [string, string][] => {
      const symbol = symbolFor(layer, {isom});
      return symbol ? [[isom, styleCode(symbol.code)]] : [];
    }),
  ]),
);

/** The expression standing in for `["get", "isom_code"]` on one tile layer. */
function codeExpression(layer: string): ExpressionSpecification {
  const pairs = CODES[layer].flat();
  return ['match', ['to-string', ['get', 'isom']], ...pairs, ''] as unknown as ExpressionSpecification;
}

function replaceIsomCode(value: unknown, replacement: ExpressionSpecification): unknown {
  if (Array.isArray(value)) {
    if (value.length === 2 && value[0] === 'get' && value[1] === 'isom_code') {
      return replacement;
    }
    return value.map((item) => replaceIsomCode(item, replacement));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, replaceIsomCode(item, replacement)]),
    );
  }
  return value;
}

/**
 * isom-maplibre's tables mix lines and areas under one code -- a lake and its bank are both
 * 301 -- and leave it to the layer type which is drawn how. MapLibre, though, fills a line as if it
 * were closed, and traces a polygon's outline with a line layer. Here that outline would include
 * the edges a tile merged from four (tilemerge.ts) was cut at, and the pyramid carries the lines
 * bounding an area -- a lake's bank -- as lines of their own. So each layer type keeps to its
 * geometry.
 */
function geometryFilter(type: string): ExpressionSpecification | undefined {
  // Multi-part features report themselves as such; the pyramid's are mostly merged into them.
  const polygon: ExpressionSpecification = ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]];
  if (type === 'fill') {
    return polygon;
  }
  if (type === 'line') {
    return ['!', polygon];
  }
  return undefined;
}

export interface IsomLayerOptions {
  /** The vector source holding mapant-nf's tiles. */
  source: string;
  /** A GeoJSON source with the pyramid's footprint, drawn as white paper under the map. */
  coverageSource: string;
  /** Map zoom from which the orienteering map is shown. */
  minZoom: number;
}

/**
 * The style's layers, rewired onto mapant-nf's tiles and in the style's own order, which is the
 * ISOM colour order.
 *
 * Left out: the style's background, which would paint the whole world white; its overview pass,
 * a lighter stand-in for the per-table sources at low zoom that a single pyramid does not need --
 * its upper levels are generalised already; and its sub-z10 "maps are here" patches, since the
 * OpenStreetMap background takes over below the orienteering map.
 */
export function isomLayers(options: IsomLayerOptions): LayerSpecification[] {
  const layers: LayerSpecification[] = [];
  for (const layer of isomStyle.layers as unknown as (LayerSpecification & {
    metadata?: Record<string, string>;
    'source-layer'?: string;
    minzoom?: number;
  })[]) {
    const pass = layer.metadata?.['isom:pass'];
    if (pass === 'coverage' && layer.type === 'fill' && (layer.minzoom ?? 0) > 0) {
      const {'source-layer': _sourceLayer, ...paper} = layer;
      layers.push({...paper, id: `isom-${layer.id}`, source: options.coverageSource, minzoom: options.minZoom});
      continue;
    }
    if (pass !== 'detail') {
      continue;
    }
    const code = layer.metadata?.['isom:code'];
    for (const tileLayer of TILE_LAYERS) {
      if (!CODES[tileLayer].some(([, styleCodeOf]) => styleCodeOf === code)) {
        continue;
      }
      const rewired = replaceIsomCode(layer, codeExpression(tileLayer)) as typeof layer & {filter?: unknown};
      const filter = geometryFilter(layer.type)
        ? ['all', geometryFilter(layer.type), rewired.filter]
        : rewired.filter;
      layers.push({
        ...rewired,
        filter,
        id: `isom-${layer.id}-${tileLayer}`,
        source: options.source,
        'source-layer': tileLayer,
        minzoom: options.minZoom,
      } as LayerSpecification);
    }
  }
  return layers;
}

/** The style's patterns and point symbols as bitmaps, keyed by their image id ("isom:407"). */
export type IsomIcons = Record<string, ImageData>;

/**
 * Rasterises the style's SVG images. At `pixelRatio` rather than isom-maplibre's fixed 2x, so a
 * print at 600 dpi does not magnify a screen bitmap.
 */
export async function rasterizeIsomIcons(pixelRatio: number): Promise<IsomIcons> {
  const ratio = Math.max(2, Math.ceil(pixelRatio));
  const entries = await Promise.all(
    Object.entries(ICONS).map(async ([id, svg]) => {
      const image = new Image();
      image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
      await image.decode();
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(image.width * ratio);
      canvas.height = Math.round(image.height * ratio);
      const context = canvas.getContext('2d')!;
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      return [id, context.getImageData(0, 0, canvas.width, canvas.height)] as const;
    }),
  );
  return Object.fromEntries(entries);
}

/** Adds the images to a map as it asks for them; `pixelRatio` is the one they were rasterised at. */
export function provideIsomIcons(map: Map, icons: IsomIcons | Promise<IsomIcons>, pixelRatio: number): void {
  const ratio = Math.max(2, Math.ceil(pixelRatio));
  // MapLibre waits for the resolver before it counts an image as missing, so a symbol is drawn
  // with its image on the first frame that has the image at all.
  map.setMissingStyleImageResolver(async (id) => {
    const ready = await icons;
    if (ready[id] && !map.hasImage(id)) {
      map.addImage(id, ready[id], {pixelRatio: ratio});
    }
  });
}
