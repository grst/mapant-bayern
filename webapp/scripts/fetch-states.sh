#!/usr/bin/env bash
# Writes public/states.geojson: Germany's 16 federal states, simplified for the overview zooms, from
# Natural Earth's 1:10m admin-1 boundaries (public domain), and public/state-labels.geojson, a point
# inside each to label it at. Each feature carries its ISO 3166-2 code as `id` and its name; what is
# known about the state's LiDAR lives in src/states.ts, keyed on `id`.
#
# Needs curl, unzip and ogr2ogr (GDAL) on PATH.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -sSfL -o "$tmp/ne.zip" https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip
unzip -q "$tmp/ne.zip" -d "$tmp"
# ~200 m tolerance: shown only below the orienteering map's zooms, where that is under a pixel.
ogr2ogr -f GeoJSON public/states.geojson "$tmp/ne_10m_admin_1_states_provinces.shp" \
    -dialect sqlite \
    -sql "SELECT iso_3166_2 AS id, name, ST_SimplifyPreserveTopology(geometry, 0.002) AS geometry
          FROM ne_10m_admin_1_states_provinces WHERE adm0_a3 = 'DEU' ORDER BY iso_3166_2" \
    -lco COORDINATE_PRECISION=5 -lco RFC7946=YES
# A point inside each state, not its centroid, which can fall outside (Brandenburg's is in Berlin).
# Brandenburg's point on surface lands next to Berlin, whose label it then hides, so it is set by
# hand, south of Berlin.
ogr2ogr -f GeoJSON public/state-labels.geojson "$tmp/ne_10m_admin_1_states_provinces.shp" \
    -dialect sqlite \
    -sql "SELECT iso_3166_2 AS id, name,
                 CASE WHEN iso_3166_2 = 'DE-BB' THEN MakePoint(13.45, 52.0, 4326)
                      ELSE ST_PointOnSurface(geometry) END AS geometry
          FROM ne_10m_admin_1_states_provinces WHERE adm0_a3 = 'DEU' ORDER BY iso_3166_2" \
    -lco COORDINATE_PRECISION=4 -lco RFC7946=YES
