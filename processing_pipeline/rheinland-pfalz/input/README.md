# Rheinland-Pfalz LAZ tile index

`laz_tiles.csv` lists every LAZ tile of the *Laserpunkte Objekte und
Gelände* (LPO/LPG) product that the Landesamt für Vermessung und
Geobasisinformation Rheinland-Pfalz publishes as OpenData under
[dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0).

**21,207 tiles, 4.71 TiB total** (index generated 2026-08-02 from the Metalink
published 2026-01-13).

RLP is the one other state that makes this easy. The tiles are plain files on a
directory-listing server, and a single statewide
[Metalink 4.0](https://datatracker.ietf.org/doc/html/rfc5854) sits beside them
carrying size and SHA-256 for each — the whole index is *one* request:

* <https://geobasis-rlp.de/data/las/current/las/> — the `.laz` files
* <https://geobasis-rlp.de/data/las/current/meta4/las_las_07.meta4> — the index
  (`07` is the Regionalschlüssel of Rheinland-Pfalz)

Finer Metalinks exist per Kreis (`las_las_<5-digit>.meta4`) and per Gemeinde
(`las_las_<8-digit>.meta4`), but they are strict subsets, so the statewide one
is all you need. Pass one to `--metalink` to index a subset.

Attribution required by the licence:
`©GeoBasis-DE / LVermGeoRP<year>, dl-de/by-2-0, www.lvermgeo.rlp.de`.

## Verification

Same tiling scheme as Bavaria, different file name:
`lpolpg_32_441_5527_1_rp.laz` is the 1 km × 1 km tile with its **lower-left**
corner at easting 441 km / northing 5527 km in EPSG:25832. Checked three ways:

* the Metalink and the directory listing agree on all 21,207 tiles — the script
  cross-checks this on every run and warns on either kind of drift;
* the LAS public headers of random tiles, fetched with an HTTP range request,
  report point extents inside the derived box and hugging its edges (e.g.
  `lpolpg_32_336_5500_1_rp.laz` → `336000.00 … 336999.99` ×
  `5500000.00 … 5500999.99`). `--verify-headers N` re-runs this;
* the declared size and SHA-256 were confirmed end-to-end by downloading
  `lpolpg_32_385_5620_1_rp.laz` and hashing it.

Note that the Metalink's `name` attribute (`LAS_441_5527_las12.laz`) is *not*
the name of the file it points at. The `tile` column uses the URL basename,
which is what actually lands on disk.

## Regenerating

```sh
uv run scripts/build_laz_tile_index.py -o input/laz_tiles.csv --verify-headers 5
```

Takes a few seconds plus whatever `--verify-headers` costs.

Same columns as Bavaria's `laz_tiles.csv` (see `../../bayern/input/README.md`), with `units`
naming the state.
