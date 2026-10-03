/**
 * The background map below the orienteering map's zooms: OpenFreeMap's "Liberty" style, vector
 * tiles in the OpenMapTiles schema (src/basemap/liberty.json, see scripts/fetch-basemap.mjs).
 *
 * Adapted to sit in the app's own style, which has one glyph host and no sprite of its own:
 *
 * - every layer ends at the zoom the orienteering map starts at, so nothing is fetched from
 *   openfreemap.org while the orienteering map is on screen, and layers that start deeper are
 *   dropped;
 * - the fonts are the two the site serves itself (Bold becomes Medium, Italic Regular), and names
 *   are the local name in Latin script -- the served glyphs cover Latin only, and the town names
 *   on the orienteering map are local names too;
 * - the sprite is the style's, as the `default` sprite, so its icon names need no prefix.
 */

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

/** The basemap's sources, prefixed `basemap-`, and its layers up to `untilZoom` (exclusive). */
export function basemap(untilZoom: number): Basemap {
  const id = (name: string) => `basemap-${name}`;
  const sources: Record<string, SourceSpecification> = {};
  for (const [name, source] of Object.entries(liberty.sources)) {
    sources[id(name)] = source as SourceSpecification;
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
