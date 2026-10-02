# karttapullautin configuration for mapant-bayern

`osm.txt` is the OSM rules file (karttapullautin's `vectorconf`): which OpenStreetMap shapes are
drawn, and as which ISOM 2000 symbol. One rule per line, `description|ISOM code|conditions`,
conditions `key=value` or `key!=value` joined by `&`, first match wins; an absent tag compares
equal to the empty string. mapant-nf makes every key a rule tests a shapefile column, and translates
the ISOM 2000 codes to ISOM 2017-2 in the tiles.

What it changes from karttapullautin's own `osm.txt`:

* **Railways**: only lines in use (`rail`, `light_rail`, `narrow_gauge`, `tram`, `subway`,
  `funicular`, `monorail`, `preserved`). `railway!=` also drew abandoned, disused and razed lines --
  north of Immenstadt, for one, where a removed siding still showed.
* **Private ground round buildings** in olive (527, ISOM 2017-2 520 "area that shall not be
  entered"): `landuse` `residential`, `farmyard`, `industrial`, `commercial`, `retail`, `garages`.
  karttapullautin's rules have the residential rule switched off (`landusedisabled=`).
* **Power lines**: `power=line` and `power=minor_line` (516). The original `power!=` would match
  every way once `power` is a column, towers and all; and it was never a column before, so power
  lines were missing altogether.
* **Pylons**: OSM's `power=tower` and `power=pole` nodes, as `516P` rules. karttapullautin draws
  a bar across the power line at each of them (ISOM 510: "the bars show the exact location of the
  pylons").
* **Lakes and rivers** as rules of their own, both 301: a `river` is `natural=water` with
  `water=river|stream|canal|ditch|drain`, or `waterway=riverbank`; anything else with
  `natural=water` or a `water` tag is a `lake`. The pullauta inis set `contour_mask=lake`:
  karttapullautin leaves out the contours, form lines and knolls inside lakes (LiDAR has no ground
  on open water, so they would be interpolation), but keeps them across rivers.
* The fence rule (`barrier!=`, 524) is called `barrier`; it was mislabelled `power line`.
