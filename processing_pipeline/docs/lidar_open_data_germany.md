# Airborne LiDAR as OpenData in the German states

Which of the 16 Bundeslaender publish an **airborne laserscanning point cloud**
(LAS/LAZ) that mapant-nf could be pointed at, and what it would take.

Surveyed 2026-08-02 by probing the states' own download endpoints. This is a
snapshot: several states moved on this in the last three years and more will.

Only the raw/classified **point cloud** counts here. Almost every state now
publishes DGM1/DOM1/bDOM raster elevation models as OpenData; karttapullautin
needs the points, so a raster DGM does not substitute.

## Verdict

| State | Point cloud OpenData? | Delivery | Per-tile URLs | `size` | `sha256` | Usable |
| --- | --- | --- | --- | --- | --- | --- |
| **Bayern** | yes, CC BY 4.0 | `.laz` | 71,979 | yes | **yes** | **shipped** — `input/laz_tiles.csv` |
| **Rheinland-Pfalz** | yes, dl-de/by-2-0 | `.laz` | 21,207 | yes | **yes** | **shipped** — `input/laz_tiles_rlp.csv` |
| Nordrhein-Westfalen | yes, dl-de/zero-2-0 | `.laz` | 35,860 | yes | no | needs a hashing pass |
| Brandenburg | yes, dl-de/by-2-0 | `.zip` per tile | 13,086 | approx. | no | needs repacking |
| Sachsen | yes | `.zip` per tile | ~4,600 | no | no | needs repacking |
| Thueringen | yes, dl-de/by-2-0 | `.zip` per tile, via app | app only | no | no | needs repacking |
| Berlin | yes, dl-de/zero-2-0 | 8 regional `.zip` (~200 GB) | no | no | no | needs repacking |
| Sachsen-Anhalt | partly — Halle region only | one packed dataset | no | no | no | not statewide |
| Mecklenburg-Vorpommern | no — HTTP-auth + fee | `.laz` | (25,466) | no | no | no |
| Niedersachsen | no — raster only | — | — | — | — | no |
| Baden-Wuerttemberg | no — inactive legacy product | — | — | — | — | no |
| Hessen | no — shop, fee-based | — | — | — | — | no |
| Schleswig-Holstein | no — raster only | — | — | — | — | no |
| Hamburg | no — raster only | — | — | — | — | no |
| Bremen | no — raster only | — | — | — | — | no |
| Saarland | no — not yet in OpenData | — | — | — | — | no |

## The binding constraint is `sha256`, not the tile links

Every state that publishes point clouds at all publishes something you can
enumerate. What almost none of them publish is a **checksum**, and mapant-nf's
tiles CSV contract makes `sha256` mandatory with no override — there is no
`--skip_checksum`. That is deliberate: a truncated laz does not make
karttapullautin fail, it renders whatever points it managed to read and
produces a plausible but wrong map, so the checksum is the only thing that
tells "finished" from "finished badly".

So the ranking above is really a ranking by metadata quality. Bavaria and
Rheinland-Pfalz both publish **Metalink 4.0** files carrying name, size,
SHA-256 and URL per tile, which is exactly the contract. Everyone else makes
you either compute the hashes yourself or repackage the data first.

The second constraint is that `tile` must be a bare `.laz`/`.las` filename —
it is used verbatim as the name inside karttapullautin's input folder. A state
that serves one ZIP per tile cannot be indexed straight into a CSV, however
well-behaved its URLs are.

## Per state

### Rheinland-Pfalz — done

`Laserpunkte Objekte/Gelaende` (LPO/LPG), 1 km tiles, EPSG:25832, dl-de/by-2-0.
Plain files on a directory-listing server, with a statewide Metalink beside
them:

- <https://geobasis-rlp.de/data/las/current/las/> — 21,207 `.laz`
- <https://geobasis-rlp.de/data/las/current/meta4/las_las_07.meta4> — size + SHA-256 for all of them

21,207 tiles, 4.71 TiB. Finer Metalinks exist per Kreis
(`las_las_<5-digit>.meta4`) and per Gemeinde (`las_las_<8-digit>.meta4`) but
they are strict subsets of the statewide one. See `input/README.md`.

### Nordrhein-Westfalen — everything but the checksums

`3D-Messdaten aus dem Laserscanning`, 1 km tiles, EPSG:25832, dl-de/zero-2-0.
NRW is the only other state with a genuine flat index:

- <https://www.opengeodata.nrw.de/produkte/geobasis/hm/3dm_l_las/3dm_l_las/index.json>

35,860 tiles, 3.17 TiB, each with a name, a byte size and a timestamp — and no
hash. There is none elsewhere either: the sibling `3dm_meta.zip` contains
`3dm_nw.csv`, which is per-tile acquisition metadata (date, method, accuracy,
CRS) with no hash column, and the server has no `.md5`/`.sha256` sidecars and
no Metalink.

`scripts/build_laz_tile_index_nrw.py` produces everything that can be had for
free, and `--fill-sha256` streams each tile and hashes it in flight to fill the
rest. That is a one-off ~3.2 TiB transfer, needs no disk, and resumes. For
scale: a full NRW render would download roughly that much again per pass, so
the hashing pass is not the expensive part of the project.

### Brandenburg, Sachsen, Thueringen, Berlin — repacking required

All four publish usable point clouds; none serves a bare `.laz`.

- **Brandenburg** — <https://data.geobasis-bb.de/geobasis/daten/als/laz/>,
  13,086 `als_33<E>-<N>.zip`, 1 km, EPSG:25833, dl-de/by-2-0. An Apache
  listing, so enumeration is trivial, but sizes are only rendered
  human-readable (`103M`) and there are no hashes.
- **Sachsen** — 2 km tiles, EPSG:25833, `lsc_33<E>_<N>_2_sn_laz.zip`, served
  from a Nextcloud share
  (`https://geocloud.landesvermessung.sachsen.de/public.php/dav/files/EpkzyJHScGb5ndd/`).
  The tile list is reachable from the `batchConfig` embedded in
  <https://www.geodaten.sachsen.de/batch-download-4719.html>.
- **Thueringen** — three epochs (2010-13, 2014-19, 2020-25), delivered as ZIP
  through the `dladownload` app at
  <https://geoportal.geoportal-th.de/gaialight-th/_apps/dladownload/dl-dhm.html>.
  No static index.
- **Berlin** — LAS 1.4, ~10 pts/m², 1 km tiles, dl-de/zero-2-0, but bundled
  into 8 regional ZIPs of 1–50 GB behind an ATOM feed
  (<https://gdi.berlin.de/data/a_als/atom/>). No per-tile URLs at all.

For any of these the route is the same: download and unpack once to local
storage, then build a CSV of `file://` URLs with locally computed sizes and
hashes. The pipeline verifies a `file://` URL exactly like an `https://` one,
so this works — it just needs the disk. Berlin is the most tractable of the
four at ~200 GB total, and is small enough to be a good second test region.

### The rest

- **Sachsen-Anhalt** — 3D-Messdaten are free, but coverage is limited to the
  Halle metropolitan region and delivery is a single packed dataset rather
  than tiles.
- **Mecklenburg-Vorpommern** — the ALS ATOM feed
  (<https://www.geodaten-mv.de/dienste/als_atom>) is tantalising: it lists
  25,466 per-tile `.laz` URLs (`3dm_33_<E>_<N>_1.laz`, EPSG:25833) *with a
  bbox on every entry*. But the download endpoint answers `401` with
  `WWW-Authenticate: Basic realm="als_download"`, and the feed's own rights
  statement makes external use permission- and fee-liable. The June 2024
  OpenData release did not cover ALS.
- **Niedersachsen** — the OpenGeoData catalogue (DCAT feed of
  <https://ni-lgln-opengeodata.hub.arcgis.com/>) lists DGM1, DOM1 and bDOM20
  only. Point clouds remain a priced product.
- **Baden-Wuerttemberg** — the portal's product catalogue
  (`https://opengeodata.lgl-bw.de/assets/config/local/odp-products.json`) has
  exactly one point-cloud entry, `Laserscandaten 2000-2005` (ALS_1,
  ~0.8 pts/m²), and it is flagged `"active": false`. The current ALS_2
  (2016-21, 8 pts/m²) and ALS_3 campaigns are not offered as point clouds;
  what is offered in LAZ is the *gridded* DGM, which has no vegetation returns
  and so would render contours without forest.
- **Hessen** — DGM1/DOM1/DOP20/LoD2 are OpenData since 2022, but Airborne
  Laserscanning sits in the fee-based shop component of
  <https://gds.hessen.de/>.
- **Schleswig-Holstein** — the download portal
  (<https://geodaten.schleswig-holstein.de/gaialight-sh/_apps/dladownload/>)
  offers DGM1, DGM5 and bDOM; there is no point-cloud client.
- **Hamburg** — Transparenzportal publishes DGM1 and bDOM. The 2022 ALS point
  cloud is used to derive them and the LoD building models, but is not
  itself published.
- **Bremen** — the OpenData product overview lists DGM 1/5 and DOM 1/5, no
  point cloud.
- **Saarland** — the OpenData portal launched in 2025 currently covers ALKIS,
  orthophotos and SAPOS RINEX; terrain models and 3D products are announced to
  follow, point clouds are not yet among them.

## If you extend this

Two things are worth checking before writing a new indexer:

1. **Does the source publish per-file SHA-256?** Look for a `.meta4` (Metalink)
   directory next to the data — that is the AdV-flavoured convention and it
   carries name, size and hash. Bavaria and Rheinland-Pfalz both have one. If
   there is none, budget a full-volume streaming hash pass.
2. **Is the served file a bare `.laz`?** A per-tile ZIP means a local
   unpacking step and a `file://` CSV, not a URL CSV.

The bounding box is usually the easy part: every German ALS product surveyed
here encodes the lower-left corner in kilometres in the file name, and the
tile edge is 1 km (2 km in Sachsen and BW). Both indexers verify that
assumption against the LAS public header via an HTTP range request
(`--verify-headers N`) rather than trusting it.
