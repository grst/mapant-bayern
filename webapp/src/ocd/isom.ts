/**
 * What each thing in the vector tiles becomes on an ISOM 2017-2 map.
 *
 * Every tile feature carries karttapullautin's class as `layer` and the ISOM symbol it chose as
 * `isom`. For the terrain that is already an ISOM 2017-2 number -- karttapullautin decides which
 * green is slow running, walk or fight (`greenshadeisom`) and which undergrowth is which -- so it is
 * used as it is. The OpenStreetMap shapes carry the ISOM 2000 codes of karttapullautin's rules file,
 * and those are translated by OpenOrienteering Mapper's own crosswalk table
 * (`symbol sets/ISOM2000-ISOM 2017-2.crt`). Every number here is checked against the template
 * rather than assumed: a code it does not define is reported, not written.
 */

import {OBJECT_TYPE_AREA, OBJECT_TYPE_LINE, OBJECT_TYPE_POINT} from './ocdwriter';

export type ObjectType =
  | typeof OBJECT_TYPE_POINT
  | typeof OBJECT_TYPE_LINE
  | typeof OBJECT_TYPE_AREA;

export interface Symbolisation {
  code: string;
  type: ObjectType;
  /**
   * Turn a line into the point symbol that represents it: the slope line on a contour is a
   * rotatable point in ISOM, and a small depression is a point rather than the ring
   * karttapullautin draws.
   */
  pointFrom?: 'start-with-angle' | 'centroid';
}

const line = (code: string): Symbolisation => ({code, type: OBJECT_TYPE_LINE});
const area = (code: string): Symbolisation => ({code, type: OBJECT_TYPE_AREA});
const point = (code: string, pointFrom?: Symbolisation['pointFrom']): Symbolisation => ({
  code,
  type: OBJECT_TYPE_POINT,
  pointFrom,
});

/**
 * The terrain classes whose symbol is not simply their `isom`: a slope line is a point of 101.1,
 * and a small depression, which karttapullautin draws as a ring, is the point symbol 111.
 */
const CURVES: Record<string, Symbolisation> = {
  slope_line: point('101.1', 'start-with-angle'),
  small_depression: point('111', 'centroid'),
};

/** The terrain symbols by ISOM 2017-2 number, and what kind of object each is. */
const TERRAIN: Record<string, Symbolisation> = {
  '101': line('101'), // contour; a depression is a contour with slope lines in ISOM
  '102': line('102'), // index contour
  '103': line('103'), // form line
  '109': point('109'), // small knoll
  '111': point('111'), // small depression
  '201': line('201'), // impassable cliff, as the cliff line karttapullautin chains
  '202': line('202'), // cliff
  '403': area('403'), // rough open land
  '406': area('406'), // vegetation: slow running
  '407': area('407'), // vegetation: slow running, good visibility (undergrowth)
  '408': area('408'), // vegetation: walk
  '409': area('409'), // vegetation: walk, good visibility (dense undergrowth)
  '410': area('410'), // vegetation: fight
};

/** ISOM 2000 (what karttapullautin's vectorconf uses) to ISOM 2017-2, from Mapper's crosswalk. */
const OSM_CODES: Record<string, Symbolisation> = {
  '301': area('301.1'), // uncrossable body of water
  '301.1': line('301.4'), // its bank line
  '306': line('305'), // small crossable watercourse
  '310': area('308'), // marsh
  '401': area('401'), // open land
  '401.1': line('415'), // its edge, as karttapullautin draws it: distinct cultivation boundary
  '414': line('415'), // distinct cultivation boundary
  '503': line('502'), // side road
  '504': line('503'), // road
  '505': line('504'), // vehicle track
  '507': line('506'), // small footpath
  '515': line('509'), // railway
  '516': line('510'), // power line
  '524': line('518'), // impassable fence
  '526': area('521'), // building
  '527': area('520'), // settlement -> area that shall not be entered
  '529': area('501.1'), // paved area
  '529.1': line('501.2'), // its bounding line
};

/**
 * The symbol for one tile feature, or null when it has none.
 *
 * `layer` is the vector tile layer -- karttapullautin's output name -- and `properties` its
 * attributes, of which `layer` (karttapullautin's class) and `isom` decide the symbol.
 */
export function symbolFor(
  layer: string,
  properties: Record<string, string | number | boolean>,
): Symbolisation | null {
  const isom = String(properties.isom ?? '');
  if (TERRAIN_LAYERS.includes(layer)) {
    return CURVES[String(properties.layer)] ?? TERRAIN[isom] ?? null;
  }
  if (OSM_LAYERS.includes(layer)) {
    // The T suffix marks karttapullautin's bridge/tunnel variant of a symbol, same feature.
    return OSM_CODES[isom.replace(/T$/, '')] ?? null;
  }
  return null;
}

/** The tile layers karttapullautin's terrain comes in; their `isom` is already ISOM 2017-2. */
const TERRAIN_LAYERS = ['contours', 'formlines', 'dotknolls', 'cliffs', 'vegetation', 'yellow', 'undergrowth'];

/** The tile layers the OpenStreetMap shapes come in, numbered in ISOM 2000. */
const OSM_LAYERS = ['osm_areas', 'osm_lines'];

export const TILE_LAYERS = [...TERRAIN_LAYERS, ...OSM_LAYERS];

/** Every `isom` value a tile layer can carry that has a symbol, for lookups built ahead of time. */
export function knownIsomValues(layer: string): string[] {
  if (TERRAIN_LAYERS.includes(layer)) {
    return Object.keys(TERRAIN);
  }
  if (OSM_LAYERS.includes(layer)) {
    return Object.keys(OSM_CODES).flatMap((code) => [code, `${code}T`]);
  }
  return [];
}
