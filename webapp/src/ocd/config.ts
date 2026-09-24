/**
 * Where the OCD export gets its inputs.
 *
 * Both are static files, so this stays a site with no backend: the vector pyramid is served as
 * plain tiles (or a PMTiles archive), and the symbol set comes from a template committed with the
 * app. The URLs are build-time settings so a deployment can point at its own copies without a code
 * change; the defaults are what a local `npm run dev` finds.
 */

/**
 * The vector tiles. `mapant-nf --vector_tiles true` publishes exactly this tree as
 * `tiles_vector/`; copy or symlink it into `public/vtiles/` to try the export locally.
 */
export const VECTOR_TILES_URL =
  import.meta.env.VITE_MAPANT_VECTOR_TILES ?? '/vtiles/{z}/{x}/{y}.pbf';

/**
 * The pyramid's zoom range. The export always reads the deepest level, because that is the only
 * one that carries the map as it was rendered: every level above it is deliberately generalised
 * for the screen -- form lines and knolls left off, the vegetation traced from a coarser grid, the
 * cliff hatching sampled -- which is right for an overview and wrong for a map to survey from.
 */
export const VECTOR_MIN_ZOOM = Number(import.meta.env.VITE_MAPANT_VECTOR_MIN_ZOOM ?? 13);
export const VECTOR_MAX_ZOOM = Number(import.meta.env.VITE_MAPANT_VECTOR_MAX_ZOOM ?? 16);

/**
 * The projected system to georeference the OCD file in: the one the LiDAR was flown in, so the
 * coordinates are the surveyor's own rather than web mercator's stretched ones.
 */
export const MAP_CRS = import.meta.env.VITE_MAPANT_CRS ?? 'EPSG:25832';

/** An OCAD 12 file holding the ISOM 2017-2 symbol set and its colours. */
export const OCD_TEMPLATE_URL =
  import.meta.env.VITE_OCD_TEMPLATE ?? '/templates/isom2017-2_10000.ocd';
