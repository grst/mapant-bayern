# Mapant Germany

Mapant Germany ist eine automatisch generierte Orientierungslaufkarte. Sie kann
nützlich sein für Trainingszwecke, oder um Geländeabschnitte für richtige OL
Karten zu finden. Das Projekt begann als Mapant Bayern. Weitere Bundesländer,
die offene LiDAR-Daten bereitstellen, werden nach und nach hinzugefügt.

<p align="center">
  <img src="img/overview.webp" alt="Übersicht" width="46%" />
  <img src="img/detail.webp" alt="Detailansicht" width="48%" />
</p>

Die Karte wurde mit
[karttapullautin](https://github.com/karttapullautin/karttapullautin) und der
[mapant-nf](https://github.com/grst/mapant-nf) pipeline erstellt.

- Wie die LIDAR-Kacheln verarbeitet wurden, ist in
  [`processing_pipeline`](https://github.com/grst/mapant-germany/tree/main/processing_pipeline)
  dokumentiert.
- Die Benutzeroberfläche liegt in
  [`webapp`](https://github.com/grst/mapant-germany/tree/main/webapp).

Die Karte jedes Bundeslandes kann im
[pmtiles](https://docs.protomaps.com/pmtiles/)-Format heruntergeladen werden und
darf unter der Lizenz [CC-BY-NC
4.0](https://creativecommons.org/licenses/by-nc/4.0/deed.de) weiterverwendet
werden:

- Bayern:
  [mapant-bayern-v2.pmtiles](https://mapant-tiles.orienteering-allgaeu.de/mapant-bayern-v2.pmtiles)
  (ca. 17 GB)
- Nordrhein-Westfalen:
  [mapant-nrw.pmtiles](https://mapant-tiles.orienteering-allgaeu.de/mapant-nrw.pmtiles)
  (ca. 6,6 GB)
- Saarland:
  [mapant-saarland.pmtiles](https://mapant-tiles.orienteering-allgaeu.de/mapant-saarland.pmtiles)
  (ca. 560 MB)
- Berlin:
  [mapant-berlin.pmtiles](https://mapant-tiles.orienteering-allgaeu.de/mapant-berlin.pmtiles)
  (ca. 290 MB)

Wenn du eine andere Lizenz benötigst, [melde dich
gerne](mailto:gregor@sturmcloud.org), um darüber zu sprechen.

## Datenquellen

- Geodaten Bayern LIDAR (© Bayerische Vermessungsverwaltung
  ([CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/deed.de)))
- Nordrhein-Westfalen LiDAR (© Geobasis NRW
  ([dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0)))
- Berlin LiDAR (© Geoportal Berlin / Airborne Laserscanning (ALS)
  ([dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0)))
- Saarland LiDAR (© GeoBasis DE/LVGL-SL (2025)
  ([dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0)))
- Grenzen der Bundesländer von [Natural
  Earth](https://www.naturalearthdata.com/) (gemeinfrei)
- OpenStreetMap von
  [geofabrik.de](https://download.geofabrik.de/europe/germany.html) (©
  OpenStreetMap contributors ([ODbL
  1.0](http://opendatacommons.org/licenses/odbl/)))

## Lizenz

Der Code steht unter der GNU General Public License v3.0 oder später
([`LICENSE`](https://github.com/grst/mapant-germany/blob/main/LICENSE)). Die
Kartendaten stehen unter CC-BY-NC 4.0 (siehe oben).
