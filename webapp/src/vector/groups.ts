/**
 * The map's features in the groups a mapper picks from when exporting: what karttapullautin
 * derived from the LiDAR, one group per kind of content a mapper redraws separately, and what
 * mapant-nf took from OpenStreetMap, split by what tends to be kept and what redrawn.
 *
 * Every feature of the archive falls in exactly one group (but the `coverage` footprints, which are
 * not map content), so ticking them all exports everything the map shows.
 */

import type {Key} from '../i18n/en';
import {isPrivateArea} from '../isomstyle';
import type {MapFeature} from './area';

export type FeatureGroup =
  | 'vegetation'
  | 'contours'
  | 'landforms'
  | 'cliffs'
  | 'water'
  | 'paths'
  | 'manmade'
  | 'private';

export interface FeatureGroupInfo {
  id: FeatureGroup;
  labelKey: Key;
  origin: 'lidar' | 'osm';
}

/** In the order they are listed. */
export const FEATURE_GROUPS: FeatureGroupInfo[] = [
  {id: 'vegetation', labelKey: 'group.vegetation', origin: 'lidar'},
  {id: 'contours', labelKey: 'group.contours', origin: 'lidar'},
  {id: 'landforms', labelKey: 'group.landforms', origin: 'lidar'},
  {id: 'cliffs', labelKey: 'group.cliffs', origin: 'lidar'},
  {id: 'water', labelKey: 'group.water', origin: 'osm'},
  {id: 'paths', labelKey: 'group.paths', origin: 'osm'},
  {id: 'manmade', labelKey: 'group.manmade', origin: 'osm'},
  {id: 'private', labelKey: 'group.private', origin: 'osm'},
];

/** The archive's tables (isom-maplibre's schema) and the group each belongs to. */
const BY_LAYER: Record<string, FeatureGroup> = {
  vegetation_areas: 'vegetation',
  contours: 'contours',
  knolls_points: 'landforms',
  cliffs: 'cliffs',
  water: 'water',
  paths: 'paths',
  manmade: 'manmade',
};

/** The group a feature belongs to, or null for what is not map content. */
export function groupOf(feature: Pick<MapFeature, 'layer' | 'properties'>): FeatureGroup | null {
  if (feature.layer === 'coverage') {
    return null;
  }
  if (isPrivateArea(feature.properties.isom_code)) {
    return 'private';
  }
  // A table this list does not know yet still reaches the file, with the man-made features.
  return BY_LAYER[feature.layer] ?? 'manmade';
}
