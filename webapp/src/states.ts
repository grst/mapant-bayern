/**
 * The federal states: what each publishes of its LiDAR, and the map archive mapant-nf rendered
 * from it, where there is one. Each state is served as a PMTiles archive of its own; archive.ts
 * reads them all as one map.
 *
 * The status follows Jens Wiesehahn's overview (https://wiesehahn.github.io/posts/lidar_availability/),
 * as does the table in processing_pipeline/README.md. The outlines
 * are public/states.geojson (scripts/fetch-states.sh), keyed on the ISO 3166-2 code.
 */

import {inPolygon, type LonLat} from './geo';

export type LidarStatus = 'rendered' | 'free' | 'fee' | 'none';

/** The statuses, best first. */
export const STATUSES: LidarStatus[] = ['rendered', 'free', 'fee', 'none'];

/** The projected systems German state LiDAR comes in, and that an OCD export is written in. */
export type StateCrs = 'EPSG:25832' | 'EPSG:25833';

export interface FederalState {
  /** ISO 3166-2, as in public/states.geojson. */
  id: string;
  name: string;
  status: LidarStatus;
  crs: StateCrs;
  /**
   * The state's archive, relative to MAPANT_TILES_BASE. Also there for a state rendered only in
   * part -- a test region -- whose status is still that of its LiDAR.
   */
  archive?: string;
  /** The LiDAR's copyright notice, shown while the state's map is on screen. */
  attribution?: string;
}

const link = (href: string, text: string) => `<a href="${href}" target="_blank" rel="noopener">${text}</a>`;
const DL_DE_BY = link('https://www.govdata.de/dl-de/by-2-0', 'dl-de/by-2-0');
const DL_DE_ZERO = link('https://www.govdata.de/dl-de/zero-2-0', 'dl-de/zero-2-0');

export const STATES: FederalState[] = [
  {
    id: 'DE-BY',
    name: 'Bayern',
    status: 'rendered',
    crs: 'EPSG:25832',
    archive: 'mapant-bayern.pmtiles',
    attribution:
      `© ${link('https://geodaten.bayern.de/opengeodata/', 'Bayerische Vermessungsverwaltung')} ` +
      `(${link('https://creativecommons.org/licenses/by/4.0/', 'CC-BY-4.0')})`,
  },
  {
    id: 'DE-RP',
    name: 'Rheinland-Pfalz',
    status: 'free',
    crs: 'EPSG:25832',
    archive: 'rheinland-pfalz.pmtiles',
    attribution: `© ${link('https://lvermgeo.rlp.de', 'GeoBasis-DE / LVermGeoRP')} (${DL_DE_BY})`,
  },
  {
    id: 'DE-NW',
    name: 'Nordrhein-Westfalen',
    status: 'rendered',
    crs: 'EPSG:25832',
    archive: 'mapant-nrw.pmtiles',
    attribution: `© ${link('https://www.bezreg-koeln.nrw.de/geobasis-nrw', 'Geobasis NRW')} (${DL_DE_ZERO})`,
  },
  {
    id: 'DE-BB',
    name: 'Brandenburg',
    status: 'free',
    crs: 'EPSG:25833',
    archive: 'brandenburg.pmtiles',
    attribution: `© ${link('https://geobasis-bb.de', 'GeoBasis-DE/LGB')} (${DL_DE_BY})`,
  },
  {
    id: 'DE-SN',
    name: 'Sachsen',
    status: 'free',
    crs: 'EPSG:25833',
    archive: 'sachsen.pmtiles',
    attribution: `© ${link('https://www.geodaten.sachsen.de', 'GeoSN')} (${DL_DE_BY})`,
  },
  {id: 'DE-TH', name: 'Thüringen', status: 'free', crs: 'EPSG:25832'},
  {id: 'DE-BE', name: 'Berlin', status: 'free', crs: 'EPSG:25833'},
  // Thinned to 4 points/m².
  {id: 'DE-SL', name: 'Saarland', status: 'free', crs: 'EPSG:25832'},
  {id: 'DE-BW', name: 'Baden-Württemberg', status: 'fee', crs: 'EPSG:25832'},
  {id: 'DE-NI', name: 'Niedersachsen', status: 'fee', crs: 'EPSG:25832'},
  {id: 'DE-MV', name: 'Mecklenburg-Vorpommern', status: 'fee', crs: 'EPSG:25833'},
  {id: 'DE-HB', name: 'Bremen', status: 'fee', crs: 'EPSG:25832'},
  {id: 'DE-HE', name: 'Hessen', status: 'fee', crs: 'EPSG:25832'},
  // Free for the Halle region only; the rest of the state against a fee.
  {id: 'DE-ST', name: 'Sachsen-Anhalt', status: 'fee', crs: 'EPSG:25832'},
  {id: 'DE-HH', name: 'Hamburg', status: 'none', crs: 'EPSG:25832'},
  {id: 'DE-SH', name: 'Schleswig-Holstein', status: 'none', crs: 'EPSG:25832'},
];

/** The shading of each status at the overview zooms. */
export const STATUS_COLORS: Record<LidarStatus, string> = {
  rendered: '#2f8f4e',
  free: '#3172ad',
  fee: '#d9962b',
  none: '#8c8c8c',
};

/** The outlines, served with the site, and a point inside each to label it at. */
export const STATES_URL = new URL('states.geojson', location.href).href;
export const STATE_LABELS_URL = new URL('state-labels.geojson', location.href).href;

let outlines: Promise<GeoJSON.FeatureCollection> | undefined;

/** The outlines, read once, when first asked for. */
function loadOutlines(): Promise<GeoJSON.FeatureCollection> {
  outlines ??= fetch(STATES_URL)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`${STATES_URL}: ${response.status}`);
      }
      return response.json() as Promise<GeoJSON.FeatureCollection>;
    })
    .catch((error: unknown) => {
      // Asked again next time rather than failing for the rest of the visit.
      outlines = undefined;
      throw error;
    });
  return outlines;
}

/** A state's outline as polygons of rings, outer ring first. */
export type Outline = LonLat[][][];

function polygonsOf(geometry: GeoJSON.Geometry): Outline {
  const polygons =
    geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.type === 'MultiPolygon' ? geometry.coordinates : [];
  return polygons as Outline;
}

/** A state's outline, if the outlines can be read. */
export async function stateOutline(id: string): Promise<Outline | undefined> {
  const feature = (await loadOutlines()).features.find((f) => f.properties?.id === id);
  return feature ? polygonsOf(feature.geometry) : undefined;
}

/** The state a point is in, if it is in Germany. */
export async function stateAt(point: LonLat): Promise<FederalState | undefined> {
  for (const feature of (await loadOutlines()).features) {
    if (polygonsOf(feature.geometry).some((rings) => inPolygon(point, rings))) {
      return STATES.find((state) => state.id === feature.properties?.id);
    }
  }
  return undefined;
}

/**
 * Whether a box lies wholly inside an outline: its corners inside, and no vertex of the outline
 * -- outer ring or hole -- inside the box, which is where an edge would cross it.
 */
export function boxInOutline([west, south, east, north]: readonly number[], outline: Outline): boolean {
  const corners: LonLat[] = [[west, south], [east, south], [east, north], [west, north]];
  if (!corners.every((corner) => outline.some((rings) => inPolygon(corner, rings)))) {
    return false;
  }
  return !outline.some((rings) =>
    rings.some((ring) => ring.some(([lon, lat]) => lon > west && lon < east && lat > south && lat < north)),
  );
}

/**
 * The projected system for a map at a point: its state's, where the point is in one, else the
 * UTM zone it falls in (zone 33 from 12° east).
 */
export async function crsAt(point: LonLat): Promise<StateCrs> {
  const state = await stateAt(point).catch(() => undefined);
  return state?.crs ?? (point[0] >= 12 ? 'EPSG:25833' : 'EPSG:25832');
}
