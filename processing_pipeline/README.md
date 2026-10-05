# Processing pipelines

This folder documents how the maps are rendered, one folder per federal state. Every state is
rendered with the same [mapant-nf](https://github.com/grst/mapant-nf) pipeline; what differs is
the tile index (`input/laz_tiles.csv`), the OSM extract and the run configuration. The
`karttapullautin_param_tuning` folder next to this one contains an agent skill to optimize
karttapullautin params based on real orienteering maps from omaps.me that exist in the area.

## LiDAR point clouds in Germany

Which of the 16 states publish an airborne laserscanning point cloud, and whether it can be
fetched tile by tile -- which is what mapant-nf needs. The status follows Jens Wiesehahn's
[LiDAR availability overview](https://wiesehahn.github.io/posts/lidar_availability/) (updated
2026-03), and so does the webapp's shading (`webapp/src/states.ts`). How each state delivers its
data, and how the tile indices were built, is in
[`docs/lidar_open_data_germany.md`](docs/lidar_open_data_germany.md) (surveyed 2026-08).

| State | Point cloud | Licence | Delivery | Tiles | Folder |
| --- | --- | --- | --- | --- | --- |
| Bayern | **mapant rendered** | CC BY 4.0 | `.laz` per 1 km tile | 71,979 | [`bayern/`](bayern/) |
| Rheinland-Pfalz | free | dl-de/by-2-0 | `.laz` per 1 km tile | 21,207 | [`rheinland-pfalz/`](rheinland-pfalz/) |
| Nordrhein-Westfalen | free | dl-de/zero-2-0 | `.laz` per 1 km tile, no checksum | 35,860 | [`nordrhein-westfalen/`](nordrhein-westfalen/) |
| Brandenburg | free | dl-de/by-2-0 | `.zip` per 1 km tile, no checksum | 13,086 | [`brandenburg/`](brandenburg/) |
| Sachsen | free | dl-de/by-2-0 | `.zip` per 2 km tile, partly SHA-1 | 4,981 | [`sachsen/`](sachsen/) |
| Thüringen | free | dl-de/by-2-0 | `.zip` per 1 km tile (2014-2019), no checksum | 17,127 | [`thueringen/`](thueringen/) |
| Berlin | free | dl-de/by-2-0 | 8 regional `.zip` of 1-37 GB | -- | not per tile |
| Hessen | free | dl-de/by-2-0 | through the Geodaten-online shop, by area | -- | not per tile |
| Saarland | free, thinned to 4 pts/m² | dl-de/by-2-0 | download portal, by area | -- | not per tile |
| Sachsen-Anhalt | free, Halle region only | dl-de/by-2-0 | one packed dataset | -- | not statewide |
| Baden-Württemberg | against a fee (3-80 €/km²) | | | | |
| Niedersachsen | against a fee (3.75-30 €/km²) | | | | |
| Mecklenburg-Vorpommern | against a fee (10-80 €/km²) | | | | |
| Bremen | against a fee (80 €/km²) | | | | |
| Hamburg | not available | | | | |
| Schleswig-Holstein | not available | | | | |

A state gets a folder here when its point cloud is free **and** can be downloaded per tile. Berlin
would need its bundles unpacked to local storage first; that is deliberately not done here.
Hessen and Saarland hand out their free point clouds by area through their portals, which a tiles
CSV cannot point at.

## One folder per state

Each folder follows [`bayern/`](bayern/):

| Path | What it is |
| --- | --- |
| `input/laz_tiles.csv` | the samplesheet: one row per tile, in mapant-nf's [tiles CSV contract](https://github.com/grst/mapant-nf/blob/main/assets/schema_tiles.json) |
| `input/README.md` | where the index comes from and how it was checked |
| `input/download_osm.sh` | fetches the state's OSM extract from geofabrik |
| `scripts/` | how the samplesheet was built, and `benchmark_download.sh` for the tile server |
| `conf/production.yml` | the full run over the state |
| `conf/test_<region>.yml` | a production-scale test region, where there is one |
| `run_prod.sh`, `run_test_<region>.sh` | launch the runs |

The zip states share one indexer, [`common/build_zip_tile_index.py`](common/build_zip_tile_index.py),
which each `scripts/build_laz_tile_index.sh` calls with its source. mapant-nf downloads a `.zip`
tile, unpacks the `.laz` inside and checks size and checksum where the samplesheet has them -- both
optional, the checksum as a bare SHA-256 or `sha1:<hex>`.

**The new states are rendered with Bavaria's settings for now**: the same karttapullautin ini,
OSM rules, zooms and grid size (`../bayern/conf/`), until each has had a parameter sweep of its own.
Sachsen's grids are 8 x 8 tiles rather than 16 x 16, because its tiles are 2 km: the same ground per
grid. The run scripts pin mapant-nf `1619f9c` (grst/mapant-nf#2), the first revision with zip
support and optional sizes and checksums; `MAPANT_NF_REVISION` overrides it.

## Test regions

| State | Region | Box (lat, lon) | Config |
| --- | --- | --- | --- |
| Rheinland-Pfalz | Koblenz, Rhein and Mosel | 50.4328, 7.5245 -- 50.2242, 7.7608 | [`test_koblenz.yml`](rheinland-pfalz/conf/test_koblenz.yml) |
| Nordrhein-Westfalen | Teutoburger Wald | 51.9524, 8.6506 -- 51.8288, 8.9846 | [`test_teutoburger_wald.yml`](nordrhein-westfalen/conf/test_teutoburger_wald.yml) |
| Brandenburg | Barnim and Schorfheide | 52.8056, 13.2518 -- 52.6325, 13.9321 | [`test_barnim.yml`](brandenburg/conf/test_barnim.yml) |
| Sachsen | Dresden and the Elbsandstein | 51.1799, 13.5232 -- 50.9139, 14.0085 | [`test_dresden.yml`](sachsen/conf/test_dresden.yml) |

How each one went is in its state's README.
