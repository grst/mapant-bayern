/**
 * Reprojection for the OCD export.
 *
 * The map view and the vector tiles are in web mercator, which is no use for a georeferenced map:
 * distances in it are stretched by the latitude, so a scale bar would be wrong. An OCD file is
 * therefore written in the projected system the LiDAR was flown in -- for Bavaria ETRS89 / UTM
 * zone 32N -- where a metre is a metre.
 *
 * proj4, since this needs a projection beyond web mercator and lon/lat.
 */

import proj4 from 'proj4';
import type {XY} from './tiles';

const WEB_MERCATOR = 'EPSG:3857';

/** The systems the pipeline can produce, by their EPSG code. */
const DEFINITIONS: Record<string, string> = {
  // ETRS89 / UTM zones 32N and 33N, which is what German state LiDAR comes in.
  'EPSG:25832': '+proj=utm +zone=32 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs',
  'EPSG:25833': '+proj=utm +zone=33 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs',
};

/**
 * OCAD's own code for a coordinate system: the grid identifier times 1000 plus the zone, with 63
 * being ETRS89/UTM. Taken from OpenOrienteering Mapper's table
 * (`src/fileformats/ocd_georef_fields.cpp`), which is the only published mapping of these.
 */
const GRID_ZONES: Record<string, number> = {
  'EPSG:25832': 63005,
  'EPSG:25833': 63006,
};

for (const [code, definition] of Object.entries(DEFINITIONS)) {
  proj4.defs(code, definition);
}

export function isSupportedCrs(code: string): boolean {
  return code in DEFINITIONS;
}

export function gridZoneFor(code: string): number {
  const zone = GRID_ZONES[code];
  if (zone === undefined) {
    throw new Error(`no OCAD coordinate system code known for ${code}`);
  }
  return zone;
}

/** Web mercator to the given projected system. */
export function toProjected(code: string, point: XY): XY {
  if (!isSupportedCrs(code)) {
    throw new Error(`unsupported coordinate reference system: ${code}`);
  }
  const [x, y] = proj4(WEB_MERCATOR, code, [point[0], point[1]]);
  return [x, y];
}
