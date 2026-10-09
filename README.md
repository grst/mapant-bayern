# Mapant Germany

Mapant Germany is an automatically generated orienteering map. It can be useful
for training purposes or for identifying new terrains to be properly mapped. The
project started as Mapant Bayern. Other federal states that provide open LiDAR
data are beeing added.

<p align="center">
  <img src="img/overview.webp" alt="Overview" width="46%" />
  <img src="img/detail.webp" alt="Detail" width="48%" />
</p>

It has been generated using the amazing
[karttapullautin](https://github.com/karttapullautin/karttapullautin) software
and processed through the [mapant-nf](https://github.com/grst/mapant-nf)
pipeline.

- Details on how the LIDAR tiles were processed are documented in
  [`processing_pipeline`](https://github.com/grst/mapant-germany/tree/main/processing_pipeline).
- The user interface is available in
  [`webapp`](https://github.com/grst/mapant-germany/tree/main/webapp).

The map of each state can be downloaded in
[pmtiles](https://docs.protomaps.com/pmtiles/) format and may be reused under
[CC-BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/deed.en) license:

- Bayern:
  [mapant-bayern-v2.pmtiles](https://mapant-tiles.orienteering-allgaeu.de/mapant-bayern-v2.pmtiles)
  (ca. 17 GB)
- Nordrhein-Westfalen:
  [mapant-nrw.pmtiles](https://mapant-tiles.orienteering-allgaeu.de/mapant-nrw.pmtiles)
  (ca. 6.6 GB)
- Saarland:
  [mapant-saarland.pmtiles](https://mapant-tiles.orienteering-allgaeu.de/mapant-saarland.pmtiles)
  (ca. 560 MB)
- Berlin:
  [mapant-berlin.pmtiles](https://mapant-tiles.orienteering-allgaeu.de/mapant-berlin.pmtiles)
  (ca. 290 MB)

If you need a different license, feel free to [reach
out](mailto:gregor@sturmcloud.org) to discuss.

## Data sources

- Geodaten Bayern LIDAR (© Bayerische Vermessungsverwaltung
  ([CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/deed.en)))
- Nordrhein-Westfalen LiDAR (© Geobasis NRW
  ([dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0)))
- Berlin LiDAR (© Geoportal Berlin / Airborne Laserscanning (ALS)
  ([dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0)))
- Saarland LiDAR (© GeoBasis DE/LVGL-SL (2025)
  ([dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0)))
- Federal state boundaries from [Natural
  Earth](https://www.naturalearthdata.com/) (public domain)
- OpenStreetMap obtained from
  [geofabrik.de](https://download.geofabrik.de/europe/germany.html) (©
  OpenStreetMap contributors ([ODbL
  1.0](http://opendatacommons.org/licenses/odbl/)))

## Licence

The code is licensed under the GNU General Public License v3.0 or later
([`LICENSE`](https://github.com/grst/mapant-germany/blob/main/LICENSE)). The map
data is CC-BY-NC 4.0 (see above).
