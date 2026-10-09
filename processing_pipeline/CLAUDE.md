## One folder per state

Each folder follows [`bayern/`](bayern/):

  | Path                                  | What it is                                                                                                                                   |
  | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
  | `input/laz_tiles.csv`                 | the samplesheet: one row per tile, in mapant-nf's [tiles CSV contract](https://github.com/grst/mapant-nf/blob/main/assets/schema_tiles.json) |
  | `input/README.md`                     | where the index comes from and how it was checked                                                                                            |
  | `input/download_osm.sh`               | fetches the state's OSM extract from geofabrik                                                                                               |
  | `scripts/`                            | how the samplesheet was built, and `benchmark_download.sh` for the tile server                                                               |
  | `conf/production.yml`                 | the full run over the state                                                                                                                  |
  | `conf/test_<region>.yml`              | a production-scale test region, where there is one                                                                                           |
  | `run_prod.sh`, `run_test_<region>.sh` | launch the runs                                                                                                                              |

The zip states share one indexer, [`common/build_zip_tile_index.py`](common/build_zip_tile_index.py),
which each `scripts/build_laz_tile_index.sh` calls with its source.
mapant-nf downloads a `.zip`
tile, unpacks the `.laz` inside and checks size and checksum where the samplesheet has them -- both
optional, the checksum as a bare SHA-256 or `sha1:<hex>`.

**The new states are rendered with Bavaria's settings for now**: the same karttapullautin ini,
OSM rules, zooms and grid size (`../bayern/conf/`), until each has had a parameter sweep of its own.
Sachsen's grids are 8 x 8 tiles rather than 16 x 16, because its tiles are 2 km: the same ground per
grid.
The run scripts pin mapant-nf `1619f9c` (grst/mapant-nf#2), the first revision with zip
support and optional sizes and checksums; `MAPANT_NF_REVISION` overrides it.

## Test regions

  | State               | Region                       | Box (lat, lon)                       | Config                                                                            |
  | ------------------- | ---------------------------- | ------------------------------------ | --------------------------------------------------------------------------------- |
  | Rheinland-Pfalz     | Koblenz, Rhein and Mosel     | 50.4328, 7.5245 -- 50.2242, 7.7608   | [`test_koblenz.yml`](rheinland-pfalz/conf/test_koblenz.yml)                       |
  | Nordrhein-Westfalen | Teutoburger Wald             | 51.9524, 8.6506 -- 51.8288, 8.9846   | [`test_teutoburger_wald.yml`](nordrhein-westfalen/conf/test_teutoburger_wald.yml) |
  | Brandenburg         | Barnim and Schorfheide       | 52.8056, 13.2518 -- 52.6325, 13.9321 | [`test_barnim.yml`](brandenburg/conf/test_barnim.yml)                             |
  | Sachsen             | Dresden and the Elbsandstein | 51.1799, 13.5232 -- 50.9139, 14.0085 | [`test_dresden.yml`](sachsen/conf/test_dresden.yml)                               |

How each one went is in its state's README.
