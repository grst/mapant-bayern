# Vector tile fixtures

Nine real z16 tiles from the vector pyramid, around Immenstadt im Allgäu, cut by

    nextflow run mapant-nf -profile podman,test_immenstadt   # branch feature/vector-tiles-kp

They cover an A4 page at 1:4000, which is what `tests/ocd.spec.ts` exports. Real tiles rather than
synthetic ones because what the OCAD export has to get right is exactly what karttapullautin puts
in them: every feature's `layer` (karttapullautin's class) and `isom` (the symbol), terrain in ISOM
2017-2 and the OSM shapes in the ISOM 2000 codes of the rules file. A synthetic tile would only test
the writer against the test's own idea of the input.

They are under 300 KB together: since karttapullautin chains its cliff dashes into cliff lines,
the hatching that used to be most of a tile is gone.

Alongside these the export test needs `public/templates/isom2017-2_10000.ocd`, the symbol template
every exported file is built on.
