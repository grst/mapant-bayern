/**
 * Where the vector tiles come from: the map's PMTiles archive, read with range requests from
 * static hosting. No tile server needed, which is the point.
 */

import {ARCHIVE_ZOOMS, fetchTile} from '../archive';

export interface VectorSource {
  minZoom: number;
  /** The deepest zoom that was actually cut. Reading it is what makes an export complete. */
  maxZoom: number;
  /** The tile's bytes, or null where the archive has no tile (outside the mapped area). */
  fetchTile(z: number, x: number, y: number): Promise<ArrayBuffer | null>;
}

/** The archive the map is drawn from (archive.ts). */
export function archiveSource(): VectorSource {
  return {minZoom: ARCHIVE_ZOOMS.minZoom, maxZoom: ARCHIVE_ZOOMS.maxZoom, fetchTile: (z, x, y) => fetchTile(z, x, y)};
}
