/**
 * Where the vector tiles come from: a plain directory of static tiles, as the pipeline publishes
 * it. No tile server needed, which is the point.
 */

export interface VectorSource {
  minZoom: number;
  /** The deepest zoom that was actually cut. Reading it is what makes an export complete. */
  maxZoom: number;
  /** The tile's bytes, or null where the pyramid has no tile (outside the mapped area). */
  fetchTile(z: number, x: number, y: number): Promise<ArrayBuffer | null>;
}

/** A `{z}/{x}/{y}.pbf` directory, as `tiles_vector/` in the pipeline's output. */
export function xyzSource(template: string, minZoom: number, maxZoom: number): VectorSource {
  return {
    minZoom,
    maxZoom,
    async fetchTile(z, x, y) {
      const url = template
        .replace('{z}', String(z))
        .replace('{x}', String(x))
        .replace('{y}', String(y));
      const response = await fetch(url);
      if (response.status === 404) {
        return null;
      }
      if (!response.ok) {
        throw new Error(`${url}: ${response.status} ${response.statusText}`);
      }
      return response.arrayBuffer();
    },
  };
}
