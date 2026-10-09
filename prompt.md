Develop the webapp for Mapant Bayern. Put the webapp in the `webapp` folder. The
existing index.html is just a prototype. It exists for reference and can be
removed once completed.

## Layout

- responsive design. Should work on both mobile and desktop.
- Simple navbar with title "Mapant Bayern" and menu items. Hamburger item that
  opens sidebar on mobile.
- Menu items:
  - source on github (https://github.com/grst/mapant-bayern)
  - "about" page, separate page, contents from "about.md" (WIP, will be manually
    populated later)
  - other mapant maps (https://mapant.net)
- Footer: Copyright notices (see compliance) and "Made with karttapullautin and
  [mapant-nf](https://github.com/grst/mapant-nf)".

## Functionality

- bilingual DE and EN
- display a hint "zoom in to view orienteering map" on zoom levels < 12
- default position: centered at Immenstadt i. Allgäu at zoom level 12
- simple measure and draw tools (draw line, polygon)
- generate share link for current position (and layer configuration, and
  drawings). Everything should be encoded in URL.

## Map layers

- display OSM Mapnik from zoom levels 0-11 and
  https://mapant-tiles.orienteering-allgaeu.de/mapant-bayern.pmtiles from zoom
  levels 12-18
- display mapterhorn hill shading / schummerung as additional overlay layer
- "toggle grid" layer as in the prototype
- vector overlay with city/town names for orientation (as the orienteering map
  has no labels)
- The town names and the hill shading sould be togglable in a menu.

## Complicance

- Show copyright notices that apply for each layer
  - © OpenStreetMap contributors for mapnik
  - © OpenStreetMap contributors \| © Bayerische Vermessungsverwaltung
    (CC-BY-4.0) \| © Gregor Sturm (CC-BY-NC-4.0) for mapant
  - whatever is appropriate for mapterhorn

## Architechture

- keep it simple
- use openlayers for the map
- don't reinvent the wheel - use open components for functionality wherever
  available.
- Help me find an appropriate web framework. If it's even necessary. Single page
  HTML + JS would be an option too. But if many js components are being used,
  compiling it with a js package manager could make it more maintainable.

## Deployment

- static HTML/JS/CSS
- deployed to github pages
- setup github actions to do so (test on PR, deploy on merge to main)

--------------------------------------------------------------------------------

Let's prepare the webapp for production.

As a first step, check what can be cleaned up. Remove any leftovers from
debugging and testing.

The following maps are now available:

- https://mapant-tiles.orienteering-allgaeu.de/mapant-berlin.pmtiles
- https://mapant-tiles.orienteering-allgaeu.de/mapant-nrw.pmtiles
- https://mapant-tiles.orienteering-allgaeu.de/mapant-saarland.pmtiles

Additionall mapant-bayern-v2.pmtiles is being uploaded.

--------------------------------------------------------------------------------

Let's work on improving the webapp. At this point, don't make any more
modifications to karttapullautin or the mapant-nf pipeline.

## Map viewer

- the background map should not show at zoom levels where the orienteering map
  shows in federal states that have one (to reduce network requests).
- zoom is limited at z18 currently. I'd like that users can zoom as far as
  they'd like. Or at least to level 20 or something.

## Layer menu

- offer an option to toggle viewing private property (olive areas).

## Printing

- pdf export should use the vector format. Currently the map is rendered to
  pixel graphics.

## OCD export menu

- use the correct symbol for exporting cliffs to ocad (the simple line one)
- depression lines are incorrectly rotated whan exporting to ocad
- make ocd export a separate menu from "printing". The symbol should include the
  text "ocd". The menu should, in principle, work the same as the export menu
- there should be a selection menu what map features to include in the export:
  at least vegetation (yellow/green), contours, OSM data, cliffs. Anything else
  you would recommend to list separately? If all boxes are ticked, all features
  that are visible in the webmap should be exported.
- Add a separate submenu "include as background map". From there it should be
  possible to select the same features as specified above. By default none are
  checked. Check if a background map can be embedded in the ocd directly. If
  not, export as a georecferenced image, and offer a zip bundle with ocd +
  background map in that case. If no background map is selected, a single ocd
  file should download either way.
