/**
 * Where the vector tiles come from.
 *
 * Two shapes of source, because the pipeline publishes a plain directory of tiles and the site
 * serves a single archive read over HTTP range requests. Both are static files; neither needs a
 * tile server, which is the point.
 */

import {PMTiles} from 'pmtiles';

export interface VectorSource {
  minZoom: number;
  /** The deepest zoom that was actually cut. Reading it is what makes an export complete. */
  maxZoom: number;
  /** The tile's bytes, or null where the pyramid has no tile (outside the mapped area). */
  fetchTile(z: number, x: number, y: number): Promise<ArrayBuffer | null>;
}

/** A `{z}/{x}/{y}.pbf` directory, as `tiles_vector/` in the pipeline's output. */
export function xyzSource(template: string, minZoom: number, maxZoom: number): VectorSource {
  return {
    minZoom,
    maxZoom,
    async fetchTile(z, x, y) {
      const url = template
        .replace('{z}', String(z))
        .replace('{x}', String(x))
        .replace('{y}', String(y));
      const response = await fetch(url);
      if (response.status === 404) {
        return null;
      }
      if (!response.ok) {
        throw new Error(`${url}: ${response.status} ${response.statusText}`);
      }
      return response.arrayBuffer();
    },
  };
}

/**
 * A PMTiles archive.
 *
 * The library decompresses a tile if the archive says it is compressed, so this works whether the
 * pyramid was packed with gzip or left plain.
 */
export function pmtilesSource(url: string, minZoom: number, maxZoom: number): VectorSource {
  const archive = new PMTiles(url);
  return {
    minZoom,
    maxZoom,
    async fetchTile(z, x, y) {
      const tile = await archive.getZxy(z, x, y);
      return tile?.data ?? null;
    },
  };
}
