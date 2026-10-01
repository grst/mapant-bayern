/**
 * The orienteering map's tiles: the one PMTiles archive mapant-nf publishes (`map/mapant.pmtiles`),
 * read with HTTP range requests straight from static hosting.
 *
 * The archive is in isom-maplibre's schema: one layer per table (`contours`, `vegetation_areas`,
 * `paths`, ...) with each feature's ISOM 2017-2 `isom_code`, a `coverage` layer with the footprint
 * of the rendered tiles, 512 px tiles, and an overview level without contours above the zooms the
 * map is generalised for. Its header knows the zoom range and the bounds.
 */

import {addProtocol} from 'maplibre-gl';
import {PMTiles, Protocol} from 'pmtiles';

/**
 * Where the archive is. `VITE_MAPANT_PMTILES` points a build or the dev server elsewhere -- at a
 * test archive served next to the app, say (`VITE_MAPANT_PMTILES=/mapant.pmtiles npm run dev` with
 * the file in `public/`).
 */
export const MAPANT_PMTILES_URL: string =
  import.meta.env.VITE_MAPANT_PMTILES ?? 'https://pub-77421d3fb5d34fc09d670e81f6c2dadf.r2.dev/mapant.pmtiles';

/** What the app needs from the archive's header. */
export interface ArchiveInfo {
  minZoom: number;
  /** The deepest zoom, the only one that carries the map as karttapullautin rendered it. */
  maxZoom: number;
  bounds?: [number, number, number, number];
}

/** Used when the header cannot be read: the zooms mapant-nf cuts by default. */
const FALLBACK: ArchiveInfo = {minZoom: 10, maxZoom: 15};

export const archive = new PMTiles(new URL(MAPANT_PMTILES_URL, location.href).href);

const protocol = new Protocol();
addProtocol('pmtiles', protocol.tile);
protocol.add(archive);

/** The URL of the archive as a MapLibre vector source. */
export const MAPANT_SOURCE_URL = `pmtiles://${archive.source.getKey()}`;

/**
 * The header, read once before the style is built: the zooms decide where the OpenStreetMap
 * background hands over to the orienteering map. A failed read leaves the defaults, and the tiles
 * then fail on their own, one by one, the way a missing tile does.
 */
export const ARCHIVE: ArchiveInfo = await archive
  .getHeader()
  .then(
    (header): ArchiveInfo => ({
      minZoom: header.minZoom,
      maxZoom: header.maxZoom,
      bounds: [header.minLon, header.minLat, header.maxLon, header.maxLat],
    }),
  )
  .catch((error: unknown) => {
    console.warn(`Could not read the map archive's header (${MAPANT_PMTILES_URL})`, error);
    return FALLBACK;
  });

/** One tile's bytes, or null where the archive has none (outside the mapped area). */
export async function fetchTile(z: number, x: number, y: number, signal?: AbortSignal): Promise<ArrayBuffer | null> {
  const response = await archive.getZxy(z, x, y, signal);
  return response?.data ?? null;
}
