#!/usr/bin/env bash
# Download Berlin Airborne Laserscanning (ALS) point clouds (LAZ, EPSG:25833).
#
# Source:  https://gdi.berlin.de/geonetwork/srv/ger/catalog.search#/metadata/f4a8997d-4dea-382f-aa3a-d452f4bf3943
# Feed:    https://gdi.berlin.de/data/a_als/atom/0.atom (INSPIRE ATOM download service)
# License: Datenlizenz Deutschland - Zero - Version 2.0
#
# The data is published as 9 regional ZIP archives (~248 GB total) of 1x1 km LAZ tiles.
# Tile overview: https://gdi.berlin.de/data/a_als/atom/Blattschnitt2x2km.gif
#
# Usage:
#   ./download_berlin_laz.sh [-o OUTDIR] [-x] [-k] [-j JOBS] [REGION ...]
#
#   REGION   one or more of: Mitte Nord Nordost Nordwest Ost Sued Suedost Suedwest West
#            (default: all regions)
#   -o DIR   output directory (default: ./berlin_als)
#   -x       extract the ZIPs after download (into DIR/laz/<Region>/)
#   -k       keep ZIPs after extraction (only with -x; default: delete them)
#   -j N     number of parallel downloads (default: 1)
#   -l       only list available regions and sizes, then exit
#
# Downloads are resumable: just re-run the script after an interruption.

set -euo pipefail

FEED_URL="https://gdi.berlin.de/data/a_als/atom/0.atom"
OUTDIR="./berlin_als"
EXTRACT=0
KEEP_ZIP=0
JOBS=1
LIST_ONLY=0

while getopts "o:xkj:lh" opt; do
    case "$opt" in
        o) OUTDIR="$OPTARG" ;;
        x) EXTRACT=1 ;;
        k) KEEP_ZIP=1 ;;
        j) JOBS="$OPTARG" ;;
        l) LIST_ONLY=1 ;;
        h|*) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    esac
done
shift $((OPTIND - 1))

for cmd in curl; do
    command -v "$cmd" >/dev/null || { echo "Error: '$cmd' is required." >&2; exit 1; }
done
if [[ $EXTRACT -eq 1 ]] && ! command -v unzip >/dev/null; then
    echo "Error: 'unzip' is required for -x." >&2; exit 1
fi

# Fetch the dataset feed and extract "URL<TAB>title" for every ZIP link.
echo "Fetching download feed: $FEED_URL"
mapfile -t ENTRIES < <(
    curl -fsSL "$FEED_URL" \
        | grep -o '<link[^>]*href="[^"]*\.zip"[^>]*>' \
        | sed -E 's/.*href="([^"]*)".*title="([^"]*)".*/\1\t\2/'
)
[[ ${#ENTRIES[@]} -gt 0 ]] || { echo "Error: no ZIP links found in feed." >&2; exit 1; }

if [[ $LIST_ONLY -eq 1 ]]; then
    printf '%-10s %s\n' "REGION" "DESCRIPTION"
    for e in "${ENTRIES[@]}"; do
        url="${e%%$'\t'*}"; title="${e#*$'\t'}"
        name="$(basename "$url" .zip)"
        printf '%-10s %s\n' "$name" "$title"
    done
    exit 0
fi

# Select regions.
SELECTED=()
if [[ $# -eq 0 ]]; then
    for e in "${ENTRIES[@]}"; do SELECTED+=("${e%%$'\t'*}"); done
else
    for region in "$@"; do
        match=""
        for e in "${ENTRIES[@]}"; do
            url="${e%%$'\t'*}"
            if [[ "$(basename "$url" .zip)" == "$region" ]]; then match="$url"; fi
        done
        [[ -n "$match" ]] || { echo "Error: unknown region '$region' (use -l to list)." >&2; exit 1; }
        SELECTED+=("$match")
    done
fi

mkdir -p "$OUTDIR/zip"

download_one() {
    local url="$1" outdir="$2" extract="$3" keep="$4"
    local name file remote_size local_size
    name="$(basename "$url" .zip)"
    file="$outdir/zip/$name.zip"

    remote_size="$(curl -fsSIL "$url" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-length"{s=$2} END{print s}')"
    local_size="$(stat -c %s "$file" 2>/dev/null || echo 0)"

    if [[ -f "$outdir/laz/$name/.done" ]]; then
        echo "[$name] already extracted, skipping."
        return 0
    fi

    if [[ -n "$remote_size" && "$local_size" == "$remote_size" ]]; then
        echo "[$name] already downloaded ($remote_size bytes)."
    else
        echo "[$name] downloading $url ($((remote_size / 1024 / 1024)) MiB) ..."
        curl -fL --retry 10 --retry-delay 10 --retry-all-errors \
             -C - -o "$file" "$url"
        local_size="$(stat -c %s "$file")"
        if [[ -n "$remote_size" && "$local_size" != "$remote_size" ]]; then
            echo "[$name] ERROR: size mismatch ($local_size != $remote_size). Re-run to resume." >&2
            return 1
        fi
        echo "[$name] download complete."
    fi

    if [[ "$extract" -eq 1 ]]; then
        echo "[$name] testing and extracting ..."
        unzip -tq "$file" >/dev/null
        mkdir -p "$outdir/laz/$name"
        unzip -oq "$file" -d "$outdir/laz/$name"
        touch "$outdir/laz/$name/.done"
        [[ "$keep" -eq 1 ]] || rm -f "$file"
        echo "[$name] extracted to $outdir/laz/$name"
    fi
}
export -f download_one

echo "Downloading ${#SELECTED[@]} region(s) to $OUTDIR with $JOBS parallel job(s)."
printf '%s\n' "${SELECTED[@]}" \
    | xargs -P "$JOBS" -I{} bash -c 'download_one "$@"' _ {} "$OUTDIR" "$EXTRACT" "$KEEP_ZIP"

echo "All done."


# repackage as laz
IMG=docker.io/pdal/pdal:latest; podman pull "$IMG" && cd $OUTDIR && for z in *.zip; do unzip -oq "$z" && find . -maxdepth 1 -name '*.las' -printf '%f\0' | IMG="$IMG" xargs -0 -P "$(nproc)" -I{} sh -c 'podman run --rm -v "$PWD":/data:z -w /data "$IMG" pdal translate --writers.las.forward=all "$1" "${1%.las}.laz" && rm -- "$1"' _ {}; done