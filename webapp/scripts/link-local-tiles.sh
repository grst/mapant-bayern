#!/usr/bin/env bash
# Links each state's newest mapant-nf result (processing_pipeline/<state>/results_*/map/mapant.pmtiles)
# into public/tiles/ under the name src/states.ts gives the state's archive, for
# `npm run dev:local`: the app reads those first and the published archives for every other state.
#
# Bavaria included: its local result is a test region (the Allgäu), which then stands in for the
# published map of the whole state. --no-bayern leaves it out, so the published one is read.
set -euo pipefail
cd "$(dirname "$0")/.."
pipeline=../processing_pipeline
mkdir -p public/tiles
find public/tiles -maxdepth 1 -name '*.pmtiles' -type l -delete

for dir in "$pipeline"/*/; do
    state="$(basename "$dir")"
    case "$state" in
        bayern) [ "${1:-}" = --no-bayern ] && continue; name=mapant-bayern.pmtiles ;;
        nordrhein-westfalen) name=mapant-nrw.pmtiles ;;
        common|docs) continue ;;
        *) name="${state}.pmtiles" ;;
    esac
    # The newest run, if there are several test regions.
    newest="$(ls -t "$dir"results_*/map/mapant.pmtiles 2> /dev/null | head -n 1 || true)"
    [ -n "$newest" ] || continue
    # Relative, so the link works wherever the repository is mounted (host or container).
    ln -s "$(realpath --relative-to=public/tiles "$newest")" "public/tiles/${name}"
    printf '%-24s <- %s\n' "$name" "${newest#"$pipeline"/}"
done
