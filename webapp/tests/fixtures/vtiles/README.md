# Vector tile fixtures

Nine real z16 tiles from the vector pyramid, around Immenstadt im Allgäu, cut by

    nextflow run mapant-nf -profile podman,test_immenstadt --vector_tiles true

They cover an A4 page at 1:4000, which is what `tests/ocd.spec.ts` exports. Real tiles rather than
synthetic ones because what the OCAD export has to get right is exactly what karttapullautin puts
in them: the contour and cliff classes, the vegetation class numbers, and the ISOM codes of the OSM
shapes. A synthetic tile would only test the writer against the test's own idea of the input.

They are ~3 MB together, most of it the cliff hatching -- some 170k two-point ticks per square
kilometre in this terrain, which is also why one of the nine is four times the size of its
neighbours.

Alongside these the export test needs `public/templates/isom2017-2_10000.ocd`, the symbol template
every exported file is built on.
