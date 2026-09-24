/**
 * What each thing in the vector tiles becomes on an ISOM 2017-2 map.
 *
 * The tiles carry karttapullautin's own vocabulary – a layer name plus a class – and the symbol
 * numbers here are the ISOM 2017-2 ones present in the template, checked against it rather than
 * assumed. Where karttapullautin emits ISOM 2000 codes for the shapes it draws from OpenStreetMap,
 * the translation is OpenOrienteering Mapper's own crosswalk table
 * (`symbol sets/ISOM2000-ISOM 2017-2.crt`).
 *
 * Two of these mappings are judgement, not translation, and a mapper should expect to revisit
 * them: which green shade counts as slow running, walk or fight, and what undergrowth means. They
 * are the reason this is a starting point for field work rather than a finished map.
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

/** Contours, form lines and knolls, by karttapullautin's class name. */
const CURVES: Record<string, Symbolisation> = {
  contour: line('101'),
  contour_index: line('102'),
  // ISOM has no separate depression contour: a depression is an ordinary contour that carries a
  // slope line, which is exactly how karttapullautin draws it.
  depression: line('101'),
  depression_index: line('102'),
  slope_line: point('101.1', 'start-with-angle'),
  // Drawn as a small ring, but the symbol for it is a point.
  small_depression: point('111', 'centroid'),
  formline: line('103'),
  formline_depression: line('103'),
  dotknoll: point('109'),
  uglydotknoll: point('109'),
  udepression: point('111'),
  uglyudepression: point('111'),
  '1010': point('109'),
  // karttapullautin's cliffs are the tick marks it draws across a cliff, not the cliff line, so
  // these come out as a band of short lines that a mapper replaces with a drawn cliff. Keeping
  // them is still worth more than dropping them: they are where the rock is.
  cliff2: line('202'),
  cliff3: line('201'),
  cliff4: line('201'),
};

/**
 * Where each green shade lands. The shades are a density ramp, and ISOM's three passability
 * classes have to be cut out of it somewhere; these are the cuts, for the default eleven shades.
 */
const GREEN_SLOW_RUNNING_MAX = 3;
const GREEN_WALK_MAX = 6;

function vegetationSymbol(klass: number): Symbolisation | null {
  if (klass === 1) {
    return area('401'); // open land
  }
  const shade = klass - 2; // classes start at 2 for the lightest green
  if (shade < 0) {
    return null;
  }
  if (shade <= GREEN_SLOW_RUNNING_MAX) {
    return area('406'); // vegetation: slow running
  }
  if (shade <= GREEN_WALK_MAX) {
    return area('408'); // vegetation: walk
  }
  return area('410'); // vegetation: fight
}

/** ISOM 2000 (what karttapullautin's vectorconf uses) to ISOM 2017-2, from Mapper's crosswalk. */
const OSM_CODES: Record<string, Symbolisation> = {
  '301': area('301.1'), // uncrossable body of water
  '301.1': line('301.4'), // its bank line
  '306': line('305'), // small crossable watercourse
  '310': area('308'), // marsh
  '401': area('401'), // open land
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
 * `layer` is the vector tile layer, `properties` its attributes: `k` for a karttapullautin class,
 * `c` for a raster class, `isom` for a shape's own code.
 */
export function symbolFor(
  layer: string,
  properties: Record<string, string | number | boolean>,
): Symbolisation | null {
  switch (layer) {
    case 'contours':
    case 'formlines':
    case 'knolls':
    case 'cliffs':
      return CURVES[String(properties.k)] ?? null;

    case 'vegetation':
      return vegetationSymbol(Number(properties.c));

    case 'undergrowth':
      // karttapullautin's undergrowth is a directional stripe overlay; ISOM's closest are the
      // "normal running in one direction" variants. A guess, and flagged as one.
      return Number(properties.c) >= 2 ? area('408.1') : area('406.1');

    case 'water':
      // 1 is water; 2 is the black detail drawn from the same image, which is a building.
      return Number(properties.c) === 2 ? area('521') : area('301.1');

    case 'blocks':
      // Written only with detectbuildings=1, and drawn in the colour karttapullautin reserves for
      // a detected building.
      return area('521');

    case 'osm_low':
    case 'osm_high': {
      // The T suffix marks karttapullautin's "on top of" variant of a symbol, same feature.
      const code = String(properties.isom).replace(/T$/, '');
      return OSM_CODES[code] ?? null;
    }

    default:
      return null;
  }
}
