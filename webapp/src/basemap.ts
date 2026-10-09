/**
 * The background map: OpenFreeMap's "Liberty" style, vector tiles in the OpenMapTiles schema
 * (src/basemap/liberty.json, see scripts/fetch-basemap.mjs) -- alone below the orienteering map's
 * zooms, and from there on only outside the states that have an orienteering map.
 *
 * Adapted to sit in the app's own style, which has one glyph host and no sprite of its own:
 *
 * - every layer ends at `untilZoom`, and layers that start deeper are dropped;
 * - with `skipTile`, its vector tiles are fetched through the `basemap-tiles` protocol, which
 *   answers a tile that wholly lies within a mapped state, at the map's zooms, with nothing
 *   instead of fetching it: nothing is fetched from openfreemap.org where the orienteering map is
 *   what is shown;
 * - the fonts are the two the site serves itself (Bold becomes Medium, Italic Regular), and names
 *   are the local name in Latin script -- the served glyphs cover Latin only, and the town names
 *   on the orienteering map are local names too;
 * - the sprite is the style's, as the `default` sprite, so its icon names need no prefix.
 */

import {addProtocol} from 'maplibre-gl';
import type {
  ExpressionSpecification,
  LayerSpecification,
  SourceSpecification,
  SpriteSpecification,
} from 'maplibre-gl';
import liberty from './basemap/liberty.json';

export const BASEMAP_ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> ' +
  '© <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a>';

const FONTS: Record<string, string> = {
  'Noto Sans Regular': 'Noto Sans Regular',
  'Noto Sans Bold': 'Noto Sans Medium',
  'Noto Sans Italic': 'Noto Sans Regular',
};

const LOCAL_NAME: ExpressionSpecification = ['coalesce', ['get', 'name:latin'], ['get', 'name']];

type StyleLayer = LayerSpecification & {
  source?: string;
  minzoom?: number;
  maxzoom?: number;
  layout?: Record<string, unknown>;
};

export interface Basemap {
  sources: Record<string, SourceSpecification>;
  layers: LayerSpecification[];
  sprite: SpriteSpecification;
}

/** Whether a vector tile may be left out, because the orienteering map is shown there instead. */
export type SkipTile = (z: number, x: number, y: number) => Promise<boolean>;

let skip: SkipTile = async () => false;

// The vector source's TileJSON, with its tile URLs pointed at `basemap-tiles`.
addProtocol('basemap-tilejson', async (request, abortController) => {
  const url = request.url.replace('basemap-tilejson://', '');
  const response = await fetch(url, {signal: abortController.signal});
  if (!response.ok) {
    throw new Error(`${url}: ${response.status}`);
  }
  const tilejson = (await response.json()) as {tiles: string[]};
  return {data: {...tilejson, tiles: tilejson.tiles.map((tile) => `basemap-tiles://${tile}`)}};
});

addProtocol('basemap-tiles', async (request, abortController) => {
  const url = request.url.replace('basemap-tiles://', '');
  const zxy = /\/(\d+)\/(\d+)\/(\d+)\.pbf$/.exec(url);
  if (zxy && (await skip(Number(zxy[1]), Number(zxy[2]), Number(zxy[3])))) {
    return {data: new ArrayBuffer(0)};
  }
  const response = await fetch(url, {signal: abortController.signal});
  if (!response.ok) {
    throw new Error(`${url}: ${response.status}`);
  }
  return {data: await response.arrayBuffer()};
});

/**
 * The basemap's sources, prefixed `basemap-`, and its layers up to `untilZoom` (exclusive; Infinity
 * for all). With `skipTile`, vector tiles it accepts are not fetched (see above).
 */
export function basemap(untilZoom: number, skipTile?: SkipTile): Basemap {
  const id = (name: string) => `basemap-${name}`;
  const sources: Record<string, SourceSpecification> = {};
  for (const [name, source] of Object.entries(liberty.sources)) {
    const vector = source as SourceSpecification & {url?: string};
    sources[id(name)] =
      skipTile && vector.type === 'vector' && vector.url
        ? {...vector, url: `basemap-tilejson://${vector.url}`}
        : vector;
  }
  if (skipTile) {
    skip = skipTile;
  }
  const layers: LayerSpecification[] = [];
  for (const layer of liberty.layers as unknown as StyleLayer[]) {
    if ((layer.minzoom ?? 0) >= untilZoom || layer.type === 'fill-extrusion') {
      continue;
    }
    const adapted: StyleLayer = {...layer, id: id(layer.id), maxzoom: Math.min(layer.maxzoom ?? 24, untilZoom)};
    if (layer.source) {
      adapted.source = id(layer.source);
    }
    if (layer.layout && 'text-font' in layer.layout) {
      const fonts = layer.layout['text-font'] as string[];
      adapted.layout = {
        ...layer.layout,
        'text-font': fonts.map((font) => FONTS[font] ?? 'Noto Sans Regular'),
        // Route shields and the like show a `ref`; only names are replaced.
        ...(JSON.stringify(layer.layout['text-field']).includes('name')
          ? {'text-field': LOCAL_NAME}
          : {}),
      };
    }
    layers.push(adapted as LayerSpecification);
  }
  return {sources, layers, sprite: [{id: 'default', url: liberty.sprite}]};
}
