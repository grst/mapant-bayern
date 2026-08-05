Develop the webapp for Mapant Bayern. Put the webapp in the `webapp` folder. The existing index.html is just a prototype. It exists for reference and can be removed once completed. 

## Layout

 * responsive design. Should work on both mobile and desktop. 
 * Simple navbar with title "Mapant Bayern" and menu items. Hamburger item that opens sidebar on mobile. 
 * Menu items: 
    * source on github (https://github.com/grst/mapant-bayern)
    * "about" page, separate page, contents from "about.md" (WIP, will be manually populated later)
    * other mapant maps (https://mapant.net)
 * Footer: Copyright notices (see compliance) and "Made with karttapullautin and [mapant-nf](https://github.com/grst/mapant-nf)".

## Functionality

 * bilingual DE and EN
 * display a hint "zoom in to view orienteering map" on zoom levels < 12
 * default position: centered at Immenstadt i. Allgäu at zoom level 12
 * simple measure and draw tools (draw line, polygon)
 * generate share link for current position (and layer configuration, and drawings). Everything should be encoded in URL.

## Map layers

 * display OSM Mapnik from zoom levels 0-11 and https://mapant-tiles.orienteering-allgaeu.de/mapant-bayern.pmtiles from zoom levels 12-18
 * display mapterhorn hill shading / schummerung as additional overlay layer
 * "toggle grid" layer as in the prototype
 * vector overlay with city/town names for orientation (as the orienteering map has no labels)
 * The town names and the hill shading sould be togglable in a menu. 

## Complicance

* Show copyright notices that apply for each layer 
    - © OpenStreetMap contributors for mapnik
    - © OpenStreetMap contributors | © Bayerische Vermessungsverwaltung (CC-BY-4.0) | © Gregor Sturm (CC-BY-NC-4.0) for mapant
    - whatever is appropriate for mapterhorn 

## Architechture

* keep it simple
* use openlayers for the map
* don't reinvent the wheel - use open components for functionality wherever available. 
* Help me find an appropriate web framework. If it's even necessary. Single page HTML + JS would be an option too. But if many js components are being used, compiling it with a js package manager could make it more maintainable. 

## Deployment

* static HTML/JS/CSS
* deployed to github pages
* setup github actions to do so (test on PR, deploy on merge to main)
