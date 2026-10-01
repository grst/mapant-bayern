# Test fixtures

`mapant.pmtiles` is a small real archive around Immenstadt im Allgäu, zooms 12-15, cut from the
mapant-nf run of `processing_pipeline/conf/test_alpsee.yml`:

    pmtiles extract results_alpsee/map/mapant.pmtiles mapant.pmtiles \
        --bbox=10.2075,47.5585,10.2210,47.5685 --minzoom=12

It covers an A4 page at 1:4000 around 47.5635 N 10.2142 E, which is what `tests/ocd.spec.ts` exports,
and the print map of `tests/print.spec.ts`. Real tiles rather than synthetic ones, because what the
OCAD export has to get right is exactly what mapant-nf puts in them: the table layers and each
feature's `isom_code`, terrain and OpenStreetMap shapes alike. A synthetic archive would only test
the export against the test's own idea of the input.

z12 and up, not only the deepest level: MapLibre requests nothing below a source's minzoom, so the
print map at 1:10 000 (z14) needs the archive to start at or above it. Most of the 3.9 MB is those
whole z12/z13 tiles.

Alongside it the export test needs `public/templates/isom2017-2_10000.ocd`, the symbol template
every exported file is built on.
