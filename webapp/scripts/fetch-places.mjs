/**
 * Regenerates public/places.geojson – the town-name overlay for the map.
 *
 * The orienteering map carries no labels at all, so a small set of place names
 * from OpenStreetMap is drawn on top for orientation. The result is committed to
 * the repository, so neither the build nor the site depends on Overpass.
 *
 * Usage: npm run fetch-places
 */
import {writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';

const OVERPASS_URL = 'https://overpass-api.de/api/interpreter';
const OUTPUT = join(dirname(import.meta.dirname), 'public', 'places.geojson');

// Bavaria, by its OSM administrative relation (de:regionalschluessel 09 = Bayern).
const QUERY = `
[out:json][timeout:300];
area["ISO3166-2"="DE-BY"]["admin_level"="4"]->.bavaria;
node["place"~"^(city|town|village)$"]["name"](area.bavaria);
out body;
`;

const response = await fetch(OVERPASS_URL, {
  method: 'POST',
  // Overpass answers 406 without a real User-Agent.
  headers: {'User-Agent': 'mapant-bayern/1.0 (https://github.com/grst/mapant-bayern)'},
  body: new URLSearchParams({data: QUERY}),
});

if (!response.ok) {
  throw new Error(`Overpass returned ${response.status} ${response.statusText}`);
}

const {elements} = await response.json();
if (!Array.isArray(elements) || elements.length === 0) {
  throw new Error('Overpass returned no places – refusing to overwrite the existing file');
}

const round = (value) => Math.round(value * 1e5) / 1e5;

const features = elements
  .filter((element) => element.tags?.name && Number.isFinite(element.lat) && Number.isFinite(element.lon))
  .map((element) => ({
    type: 'Feature',
    geometry: {type: 'Point', coordinates: [round(element.lon), round(element.lat)]},
    properties: {name: element.tags.name, place: element.tags.place},
  }))
  // Stable order keeps the committed file's diffs small between refreshes.
  .sort((a, b) => a.properties.name.localeCompare(b.properties.name, 'de'));

writeFileSync(OUTPUT, JSON.stringify({type: 'FeatureCollection', features}));

const counts = features.reduce((acc, feature) => {
  acc[feature.properties.place] = (acc[feature.properties.place] ?? 0) + 1;
  return acc;
}, {});
const sizeKb = Math.round(Buffer.byteLength(JSON.stringify({type: 'FeatureCollection', features})) / 1024);
console.log(`Wrote ${features.length} places to ${OUTPUT} (${sizeKb} kB)`);
console.log(Object.entries(counts).map(([place, count]) => `  ${place}: ${count}`).join('\n'));
