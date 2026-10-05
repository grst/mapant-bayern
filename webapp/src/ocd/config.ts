/**
 * Where the OCD export gets its inputs besides the vector tiles (see `MAPANT_TILES_BASE` in
 * archive.ts). Static files, so this stays a site with no backend.
 *
 * The projected system an OCD file is georeferenced in is the one its state's LiDAR was flown in,
 * so the coordinates are the surveyor's own rather than web mercator's stretched ones: `crsAt` in
 * states.ts.
 */

/** An OCAD 12 file holding the ISOM 2017-2 symbol set and its colours, committed with the app. */
export const OCD_TEMPLATE_URL = '/templates/isom2017-2_10000.ocd';
