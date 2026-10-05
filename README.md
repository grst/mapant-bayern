# Mapant Germany

Mapant Germany is an automatically generated orienteering map. It can be useful for training purposes or for identifying
new terrains to be properly mapped. It started as Mapant Bayern and covers all of Bavaria; the other federal states
follow where their LiDAR is freely available, one state at a time. At low zoom the map shows which states that is.

<p align="center">
  <img src="img/overview.webp" alt="Overview" width="46%" />
  <img src="img/detail.webp" alt="Detail" width="48%" />
</p>



It has been generated using the amazing [karttapullautin](https://github.com/karttapullautin/karttapullautin) software
and processed through the [mapant-nf](https://github.com/grst/mapant-nf) pipeline. 
 * Details on how the LIDAR tiles were processed are documented in [`processing_pipeline`](https://github.com/grst/mapant-bayern/tree/main/processing_pipeline). 
 * The user interface is available in [`webapp`](https://github.com/grst/mapant-bayern/tree/main/webapp).

The full map of Bavaria can be downloaded in [pmtiles](https://docs.protomaps.com/pmtiles/) format (ca. 180 GB) and may
 be reused under [CC-BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/deed.en) license: 

  * [mapant-bayern.pmtiles](https://mapant-tiles.orienteering-allgaeu.de/mapant-bayern.pmtiles).

If you need a different license, feel free to [reach out](mailto:gregor@sturmcloud.org) to discuss. 

## Data sources

 * Geodaten Bayern LIDAR (© Bayerische Vermessungsverwaltung ([CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/deed.en)))
 * Nordrhein-Westfalen LiDAR (© Geobasis NRW ([dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0)))
 * Test regions: LiDAR of Rheinland-Pfalz (© GeoBasis-DE / LVermGeoRP), Brandenburg (© GeoBasis-DE/LGB) and Sachsen
   (© GeoSN), all [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0)
 * Federal state boundaries from [Natural Earth](https://www.naturalearthdata.com/) (public domain)
 * OpenStreetMap obtained from [geofabrik.de](https://download.geofabrik.de/europe/germany.html) (© OpenStreetMap contributors ([ODbL 1.0](http://opendatacommons.org/licenses/odbl/)))
