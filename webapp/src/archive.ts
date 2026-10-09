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
 *
 * Nothing waits for the archives up front. The map is built for the zooms mapant-nf cuts
 * (ARCHIVE_ZOOMS) and starts at once, and an archive's header -- a request to the bucket, which
 * answers range requests slowly -- is read only when a tile near its state is first asked for. A
 * visit to Bavaria reads Bavaria's header, not all of them.
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
  import.meta.env.VITE_MAPANT_TILES ?? 'https://mapant-tiles.orienteering-allgaeu.de/';

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

/**
 * The zooms mapant-nf cuts, which the map is built for before any header is read. An archive whose
 * header says otherwise is read all the same, within these zooms, and reported.
 */
export const ARCHIVE_ZOOMS = {minZoom: 10, maxZoom: 15} as const;

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

/** The states that have an archive. */
const MAPPED_STATES = STATES.filter((state) => state.archive);

/** Each state's archive, once asked for: its header read, or null where it cannot be. */
const archives = new Map<string, Promise<StateArchive | null>>();

/** The archives whose header has been read, for what has to be answered at once (attributions). */
export const LOADED_ARCHIVES: StateArchive[] = [];

const loadListeners = new Set<() => void>();

/** Called whenever another archive's header has been read. */
export function onArchiveLoaded(listener: () => void): void {
  loadListeners.add(listener);
}

/**
 * A state's archive, its header read on the first call. One that cannot be read -- not uploaded
 * yet, say -- is left out with a warning rather than costing the others.
 */
function archiveOf(state: FederalState): Promise<StateArchive | null> {
  let archive = archives.get(state.id);
  if (!archive) {
    archive = (async () => {
      if (localBase) {
        const url = new URL(state.archive!, localBase).href;
        try {
          const local = await load(state, url);
          console.info(`${state.name}: local archive ${url}`);
          return local;
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
    })().then((loaded) => {
      if (loaded) {
        const {minZoom, maxZoom} = loaded.info;
        if (minZoom !== ARCHIVE_ZOOMS.minZoom || maxZoom !== ARCHIVE_ZOOMS.maxZoom) {
          console.warn(
            `${state.name}: archive has zooms ${minZoom}-${maxZoom}, the map is built for ` +
              `${ARCHIVE_ZOOMS.minZoom}-${ARCHIVE_ZOOMS.maxZoom} (ARCHIVE_ZOOMS)`,
          );
        }
        LOADED_ARCHIVES.push(loaded);
        loadListeners.forEach((listener) => listener());
      }
      return loaded;
    });
    archives.set(state.id, archive);
  }
  return archive;
}

/**
 * Starts reading the headers of the archives a view may need, without waiting for them: called at
 * start-up with the view the page opens at, so the header is on its way while the map is still
 * being set up rather than only once it asks for its first tile.
 */
export function prefetchArchives(view: readonly number[]): void {
  for (const state of MAPPED_STATES) {
    if (!state.reach || intersects(view, state.reach)) {
      void archiveOf(state);
    }
  }
}

export function intersects(a: readonly number[], b: readonly number[]): boolean {
  return a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3];
}

/**
 * The archives a tile may be in: those of the states it is near, their headers read as needed, and
 * of those the ones whose zooms hold its level and whose bounds it touches.
 */
async function archivesFor(z: number, x: number, y: number): Promise<StateArchive[]> {
  if (z < ARCHIVE_ZOOMS.minZoom || z > ARCHIVE_ZOOMS.maxZoom) {
    return [];
  }
  const box = tileBounds(z, x, y);
  const states = MAPPED_STATES.filter((state) => !state.reach || intersects(box, state.reach));
  const loaded = await Promise.all(states.map(archiveOf));
  return loaded.filter(
    (a): a is StateArchive =>
      a !== null && z >= a.info.minZoom && z <= a.info.maxZoom && intersects(box, a.info.bounds),
  );
}

/**
 * One tile's bytes, or null where no archive has it (outside the mapped area). A tile one archive
 * holds is passed on untouched; only one on a border is decoded and merged. An archive that fails
 * costs its own side of the tile, unless every archive asked failed.
 */
export async function fetchTile(z: number, x: number, y: number, signal?: AbortSignal): Promise<ArrayBuffer | null> {
  const candidates = await archivesFor(z, x, y);
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
 * Whether a web-mercator tile lies wholly within a state that has an orienteering map, at the
 * zooms the map is shown at. There the basemap need not fetch the tile (basemap.ts): it is the
 * orienteering map that is shown, and nothing of the basemap is wanted under it -- not even where
 * the state's archive does not reach (yet), which is left empty rather than costing requests to
 * openfreemap.org.
 *
 * Errs towards false: a tile on a state's border, or anywhere the outlines cannot be read, is not
 * covered, since the ground on the other side of the border still needs its basemap.
 */
export async function isMapped(z: number, x: number, y: number): Promise<boolean> {
  if (z < ARCHIVE_ZOOMS.minZoom) {
    return false;
  }
  const box = tileBounds(z, x, y);
  for (const state of MAPPED_STATES) {
    const outline = await stateOutline(state.id).catch(() => undefined);
    // Only where the state's archive can actually be read: a state whose archive is missing keeps
    // its basemap.
    if (outline && boxInOutline(box, outline) && (await archiveOf(state))) {
      return true;
    }
  }
  return false;
}
