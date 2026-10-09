/**
 * The orienteering map's look: the ISOM 2017-2 style of isom-maplibre, over the archive mapant-nf
 * publishes.
 *
 * The archive is in the style's own schema -- a layer per table (`contours`, `vegetation_areas`,
 * ...), each feature with its `isom_code` ("403.000") -- so the style's layers are used as they
 * are. All that changes is where they read from: the style expects one tile source per table, and
 * the archive is one source holding all of them.
 */

import type {ExpressionSpecification, LayerSpecification, Map} from 'maplibre-gl';
import isomStyle from '@metsa/isom-maplibre/style.json';
import {ICONS, isomImage, type IsomImage} from '@metsa/isom-maplibre';

/**
 * isom-maplibre's tables mix lines and areas under one code -- a lake and its bank are both
 * 301.000 -- and leave it to the layer type which is drawn how. MapLibre, though, fills a line as
 * if it were closed, and traces a polygon's outline with a line layer, including the edges a tile
 * was clipped at; mapant-nf writes the line bounding an area -- a lake's bank -- as a line of its
 * own. So each layer type keeps to its geometry.
 */
function geometryFilter(type: string): ExpressionSpecification | undefined {
  const polygon: ExpressionSpecification = ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]];
  if (type === 'fill') {
    return polygon;
  }
  if (type === 'line') {
    return ['!', polygon];
  }
  return undefined;
}

/**
 * ISOM 520, "area that shall not be entered": the olive of private ground round buildings, which
 * mapant-nf takes from OpenStreetMap. A visitor may want the map without it.
 */
export function isPrivateArea(isomCode: unknown): boolean {
  return typeof isomCode === 'string' && isomCode.startsWith('520.');
}

/**
 * The archive's `cliffs` table: the cliffs and boulders karttapullautin derives from the LiDAR,
 * which can clutter steep ground. A visitor may want the map without them.
 */
export const CLIFFS_TABLE = 'cliffs';

export interface IsomLayerOptions {
  /** The vector source holding the archive. */
  source: string;
  /** Map zoom from which the orienteering map is shown. */
  minZoom: number;
}

/**
 * The style's layers in its own order, which is the ISOM colour order, all reading the archive:
 * the white paper of its `coverage` layer, the overview pass (below z13, without contours, which
 * the archive's overview level does not have either) and the detail pass.
 *
 * Left out: the style's background, which would paint the whole world white -- the paper is drawn
 * only where there is map -- and the coverage outline it shows at low zoom, since the
 * basemap takes over there.
 */
export function isomLayers(options: IsomLayerOptions): LayerSpecification[] {
  const layers: LayerSpecification[] = [];
  for (const layer of isomStyle.layers as unknown as (LayerSpecification & {
    metadata?: Record<string, string>;
    'source-layer'?: string;
    filter?: unknown;
    minzoom?: number;
  })[]) {
    const pass = layer.metadata?.['isom:pass'];
    if (pass === 'coverage') {
      if (layer.type === 'fill' && (layer.minzoom ?? 0) > 0) {
        layers.push({...layer, id: `isom-${layer.id}`, source: options.source, minzoom: options.minZoom});
      }
      continue;
    }
    if (pass !== 'detail' && pass !== 'overview') {
      continue;
    }
    const geometry = geometryFilter(layer.type);
    layers.push({
      ...layer,
      filter: geometry ? ['all', geometry, layer.filter] : layer.filter,
      id: `isom-${layer.id}`,
      source: options.source,
      minzoom: Math.max(options.minZoom, layer.minzoom ?? 0),
    } as LayerSpecification);
  }
  return layers;
}

/** The style's images by id ("isom:407"), drawn for one pixel ratio. */
export type IsomIcons = Record<string, IsomImage>;

/**
 * Draws the style's images at `pixelRatio` rather than isom-maplibre's default, so a print at
 * 600 dpi does not magnify a screen bitmap. The point symbols come as distance fields, which
 * stay sharp however far the style magnifies them; the fill patterns come once per zoom.
 */
export async function rasterizeIsomIcons(pixelRatio: number): Promise<IsomIcons> {
  const entries = await Promise.all(
    Object.keys(ICONS).map(async (id) => [id, await isomImage(id, Math.max(2, pixelRatio))] as const),
  );
  return Object.fromEntries(entries.filter((entry): entry is [string, IsomImage] => entry[1] !== undefined));
}

/** Adds the images to a map as it asks for them. */
export function provideIsomIcons(map: Map, icons: IsomIcons | Promise<IsomIcons>): void {
  // MapLibre waits for the resolver before it counts an image as missing, so a symbol is drawn
  // with its image on the first frame that has the image at all.
  map.setMissingStyleImageResolver(async (id) => {
    const image = (await icons)[id];
    if (image && !map.hasImage(id)) {
      map.addImage(id, image.data, {pixelRatio: image.pixelRatio, sdf: image.sdf});
    }
  });
}
