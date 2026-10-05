/**
 * The orienteering map's tiles: one PMTiles archive per federal state, as mapant-nf publishes them
 * (`map/mapant.pmtiles`, renamed after the state), read with HTTP range requests straight from
 * static hosting. Which states have one is in states.ts.
 *
 * The archives are in isom-maplibre's schema: one layer per table (`contours`, `vegetation_areas`,
 * `paths`, ...) with each feature's ISOM 2017-2 `isom_code`, a `coverage` layer with the footprint
 * of the rendered tiles, 512 px tiles, and an overview level without contours above the zooms the
 * map is generalised for. Each header knows its zoom range and bounds.
 *
 * To the rest of the app they are one map: fetchTile() asks every archive whose bounds the tile
 * touches, and a tile on a border between two -- each holding its own side, buffer included -- is
 * merged into one.
 */

import {PMTiles} from 'pmtiles';
import {tileBounds} from './geo';
import {boxInOutline, stateOutline, STATES, type FederalState} from './states';
import {mergeTiles} from './tilemerge';

/**
 * Where the archives are: each state's `archive` is resolved against this. `VITE_MAPANT_TILES`
 * points a build or the dev server elsewhere -- at test archives served next to the app, say
 * (`VITE_MAPANT_TILES=/tiles/ npm run dev` with the files in `public/tiles/`).
 */
export const MAPANT_TILES_BASE: string =
  import.meta.env.VITE_MAPANT_TILES ?? 'https://pub-77421d3fb5d34fc09d670e81f6c2dadf.r2.dev/';

/**
 * For local testing: archives looked for here first, each falling back to MAPANT_TILES_BASE where
 * there is none -- so a test run's archive in `public/tiles/` is drawn next to the published ones.
 * `npm run dev:local` sets it to `/tiles/` after linking the pipeline's results there
 * (scripts/link-local-tiles.sh).
 */
const LOCAL_TILES_BASE: string | undefined = import.meta.env.VITE_MAPANT_LOCAL_TILES;

/** What the app needs from an archive's header. */
export interface ArchiveInfo {
  minZoom: number;
  /** The deepest zoom, the only one that carries the map as karttapullautin rendered it. */
  maxZoom: number;
  /** West, south, east, north. */
  bounds?: [number, number, number, number];
}

/** Used when no header can be read: the zooms mapant-nf cuts by default. */
const FALLBACK: ArchiveInfo = {minZoom: 10, maxZoom: 15};

export interface StateArchive {
  state: FederalState;
  url: string;
  info: ArchiveInfo & {bounds: [number, number, number, number]};
  pmtiles: PMTiles;
}

const base = new URL(MAPANT_TILES_BASE, location.href);
const localBase = LOCAL_TILES_BASE ? new URL(LOCAL_TILES_BASE, location.href) : undefined;

/** A state's archive at `url`, with its header read; throws where there is none. */
async function load(state: FederalState, url: string): Promise<StateArchive> {
  const pmtiles = new PMTiles(url);
  const header = await pmtiles.getHeader();
  return {
    state,
    url,
    pmtiles,
    info: {
      minZoom: header.minZoom,
      maxZoom: header.maxZoom,
      bounds: [header.minLon, header.minLat, header.maxLon, header.maxLat],
    },
  };
}

/**
 * The archives whose header could be read, before the style is built: the zooms decide where the
 * OpenFreeMap basemap hands over to the orienteering map, and the bounds which archive a tile is
 * asked of. An archive that cannot be read -- not uploaded yet, say -- is left out with a warning
 * rather than costing the others.
 */
export const ARCHIVES: StateArchive[] = (
  await Promise.all(
    STATES.filter((state) => state.archive).map(async (state): Promise<StateArchive | null> => {
      if (localBase) {
        const url = new URL(state.archive!, localBase).href;
        try {
          const archive = await load(state, url);
          console.info(`${state.name}: local archive ${url}`);
          return archive;
        } catch {
          // None here (the dev server answers a missing file with the app's HTML): the published one.
        }
      }
      const url = new URL(state.archive!, base).href;
      try {
        return await load(state, url);
      } catch (error: unknown) {
        console.warn(`Could not read the map archive of ${state.name} (${url})`, error);
        return null;
      }
    }),
  )
).filter((archive): archive is StateArchive => archive !== null);

/** All archives together: the widest zoom range and the bounds around them all. */
export const ARCHIVE: ArchiveInfo = ARCHIVES.length
  ? {
      minZoom: Math.min(...ARCHIVES.map((a) => a.info.minZoom)),
      maxZoom: Math.max(...ARCHIVES.map((a) => a.info.maxZoom)),
      bounds: [
        Math.min(...ARCHIVES.map((a) => a.info.bounds[0])),
        Math.min(...ARCHIVES.map((a) => a.info.bounds[1])),
        Math.max(...ARCHIVES.map((a) => a.info.bounds[2])),
        Math.max(...ARCHIVES.map((a) => a.info.bounds[3])),
      ],
    }
  : FALLBACK;

export function intersects(a: readonly number[], b: readonly number[]): boolean {
  return a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3];
}

/** The archives a tile may be in: those whose zooms hold its level and whose bounds it touches. */
function archivesFor(z: number, x: number, y: number): StateArchive[] {
  const box = tileBounds(z, x, y);
  return ARCHIVES.filter((a) => z >= a.info.minZoom && z <= a.info.maxZoom && intersects(box, a.info.bounds));
}

/**
 * One tile's bytes, or null where no archive has it (outside the mapped area). A tile one archive
 * holds is passed on untouched; only one on a border is decoded and merged. An archive that fails
 * costs its own side of the tile, unless every archive asked failed.
 */
export async function fetchTile(z: number, x: number, y: number, signal?: AbortSignal): Promise<ArrayBuffer | null> {
  const candidates = archivesFor(z, x, y);
  const results = await Promise.allSettled(candidates.map((a) => a.pmtiles.getZxy(z, x, y, signal)));
  const tiles: ArrayBuffer[] = [];
  for (const result of results) {
    if (result.status === 'fulfilled' && result.value?.data) {
      tiles.push(result.value.data);
    }
  }
  if (tiles.length === 0) {
    const failure = results.find((result): result is PromiseRejectedResult => result.status === 'rejected');
    if (failure && results.every((result) => result.status === 'rejected')) {
      throw failure.reason;
    }
    return null;
  }
  return tiles.length === 1 ? tiles[0] : mergeTiles(tiles);
}

/**
 * Whether a web-mercator tile lies wholly within mapped ground: inside an archive's bounds and its
 * zooms, and inside its state's outline -- the bounds alone would take in a neighbour's ground, as
 * the Allgäu test region's take in Austria. Where it does, the orienteering map's paper covers
 * everything under it, and the basemap need not fetch the tile (basemap.ts).
 *
 * Errs towards false: a tile on a state's border, or anywhere the outlines cannot be read, is not
 * covered.
 */
export async function isMapped(z: number, x: number, y: number): Promise<boolean> {
  const box = tileBounds(z, x, y);
  for (const archive of ARCHIVES) {
    const [west, south, east, north] = archive.info.bounds;
    if (z < archive.info.minZoom || box[0] < west || box[1] < south || box[2] > east || box[3] > north) {
      continue;
    }
    const outline = await stateOutline(archive.state.id).catch(() => undefined);
    if (outline && boxInOutline(box, outline)) {
      return true;
    }
  }
  return false;
}
