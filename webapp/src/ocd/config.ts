/**
 * Where the OCD export gets its inputs besides the vector tiles (see `MAPANT_PMTILES_URL` in
 * archive.ts). Static files, so this stays a site with no backend.
 */

/**
 * The projected system to georeference the OCD file in: the one the LiDAR was flown in, so the
 * coordinates are the surveyor's own rather than web mercator's stretched ones.
 */
export const MAP_CRS = 'EPSG:25832';

/** An OCAD 12 file holding the ISOM 2017-2 symbol set and its colours, committed with the app. */
export const OCD_TEMPLATE_URL = '/templates/isom2017-2_10000.ocd';
