/**
 * What each thing in the vector tiles becomes on an ISOM 2017-2 map.
 *
 * Every tile feature carries its ISOM 2017-2 symbol as `isom_code`, spelt the way isom-maplibre
 * spells it ("403.000", "101.001"): mapant-nf has already translated the OpenStreetMap shapes from
 * the ISOM 2000 codes of karttapullautin's rules file, with OpenOrienteering Mapper's crosswalk. So
 * this is a matter of spelling the code the way the OCD template does ("403", "101.1"), and of the
 * few symbols the style draws as one but ISOM splits by geometry. Every number here is checked
 * against the template rather than assumed: a code it does not define is reported, not written.
 */

import {OBJECT_TYPE_AREA, OBJECT_TYPE_LINE, OBJECT_TYPE_POINT} from './ocdwriter';

export type ObjectType =
  | typeof OBJECT_TYPE_POINT
  | typeof OBJECT_TYPE_LINE
  | typeof OBJECT_TYPE_AREA;

export type GeometryKind = 'point' | 'line' | 'polygon';

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

const TYPE: Record<GeometryKind, ObjectType> = {
  point: OBJECT_TYPE_POINT,
  line: OBJECT_TYPE_LINE,
  polygon: OBJECT_TYPE_AREA,
};

/**
 * karttapullautin's classes (its `layer` property) whose symbol is not what their geometry says:
 * a slope line is a point of 101.1, and a small depression, drawn as a ring, is the point 111.
 */
const CURVES: Record<string, Symbolisation> = {
  slope_line: {code: '101.1', type: OBJECT_TYPE_POINT, pointFrom: 'start-with-angle'},
  small_depression: {code: '111', type: OBJECT_TYPE_POINT, pointFrom: 'centroid'},
};

/**
 * Symbols the style draws under one code whose variants ISOM splits by geometry: the water body
 * and its bank line, the paved area and its edge.
 */
const BY_GEOMETRY: Record<string, Partial<Record<GeometryKind, string>>> = {
  '301.000': {polygon: '301.1', line: '301.4'}, // uncrossable body of water, full colour; bank line
  '501.000': {polygon: '501.1'}, // paved area
};

/** An `isom_code` as the OCD template numbers its symbols: "403.000" is 403, "521.001" 521.1. */
export function templateCode(isomCode: string): string {
  const [major, variant = '0'] = isomCode.split('.');
  const number = Number(variant);
  return Number.isInteger(number) && number > 0 ? `${major}.${number}` : major;
}

/**
 * The symbol for one tile feature, or null when it has none (the `coverage` footprints, for one).
 */
export function symbolFor(
  properties: Record<string, string | number | boolean>,
  kind: GeometryKind,
): Symbolisation | null {
  const curve = CURVES[String(properties.layer ?? '')];
  if (curve) {
    return curve;
  }
  const isomCode = properties.isom_code;
  if (typeof isomCode !== 'string' || isomCode === '') {
    return null;
  }
  return {code: BY_GEOMETRY[isomCode]?.[kind] ?? templateCode(isomCode), type: TYPE[kind]};
}
