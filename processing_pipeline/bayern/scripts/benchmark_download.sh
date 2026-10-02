#!/usr/bin/env bash
# Measure how fast laz tiles can actually be fetched from the tile server, the way this pipeline
# fetches them: many whole files in flight at once, for long enough to reach steady state.
#
#   scripts/benchmark_download.sh                        # the tracked 23-URL Bavaria fixture
#   scripts/benchmark_download.sh --csv tiles.csv        # the real samplesheet: a much better sample
#   scripts/benchmark_download.sh --dry-run              # what it would transfer, and from where
#   scripts/benchmark_download.sh --levels '1 8 56' --duration 30
#   scripts/benchmark_download.sh --tsv bench.tsv        # keep the numbers
#
# Nothing is written to disk (every transfer goes to /dev/null), so it can run before the scratch
# volume exists and it measures the network rather than the filesystem. The striped NVMe does
# gigabytes per second; if that is what you doubt, fio is the tool, not this.
#
# ---------------------------------------------------------------------------
# Why not `curl -o /dev/null -w '%{speed_download}' <one tile>`
# ---------------------------------------------------------------------------
# That one-liner is what README.md suggests, and its 30 MB/s is the number the entire schedule
# currently hangs on -- "the download alone is over seven days and dwarfs the compute". It is one
# connection fetching one file, and the run is neither. Four ways it misleads:
#
#   1. Wrong concurrency, by a factor of ~56. bin/fetch_laz.py runs params.download_jobs curls at
#      once *within one grid task*, and PULLAUTA_GRID's maxForks lets several grids do that
#      simultaneously: 8 x 7 = 56 concurrent transfers on -profile c8id. A single-stream number
#      cannot tell you whether that helps or whether the server simply divides the same total among
#      however many connections you open.
#   2. That distinction is the whole decision. If the cap is per connection, more streams buy more
#      throughput and download_jobs should go up. If the cap is on the aggregate, no amount of
#      parallelism moves it, and the honest conclusion is that the run needs a bulk transfer or a
#      mirror rather than a bigger instance. The two look identical from one stream.
#   3. One file is mostly ramp-up. TCP slow start, TLS, DNS and the server's own first-byte latency
#      are amortised over a couple of hundred megabytes, and a laz file that happens to be small
#      measures little else.
#   4. One URL, measured repeatedly, measures a warm cache. Every re-run of that command asks for
#      the same object; the 19 TB the run needs is 72,000 distinct objects, read once each.
#
# What this script does instead: for each connection count in --levels, it runs --duration seconds of
# real transfers with that many workers, each pulling whole files back-to-back from its own disjoint
# slice of a shuffled URL list -- the same curl invocation, flags and User-Agent as
# bin/fetch_laz.py, so the server sees the traffic it will see during the run. It then reports
# aggregate and per-connection throughput per level, where the knee is, and what the best rate
# implies for the full input volume.
#
# ---------------------------------------------------------------------------
# On being a good citizen
# ---------------------------------------------------------------------------
# geodaten.bayern.de is a public open-data server, not a load-test target. Two consequences:
#
#   * The traffic is bounded by --duration x the rate it achieves, and the sweep stops once
#     --budget-gb has been moved. Both are printed before anything is transferred, and --dry-run
#     shows the plan without touching the network.
#   * The User-Agent identifies the pipeline and marks the request as a benchmark, so the provider's
#     logs distinguish this from a run. As README.md says: a 19 TB pull deserves a conversation with
#     the data provider before it starts, and arriving with measurements is how to have it.
set -euo pipefail

readonly DEFAULT_CSV='tests/fixtures/laz_tiles_kemptner_wald.csv'
readonly USER_AGENT='mapant/1.0 (+https://github.com/grst/mapant) download benchmark'

# The levels bracket what -profile c8id actually opens: 56 = params.download_jobs 8 x PULLAUTA_GRID
# maxForks 7. 64 is there to show whether 56 is already past the knee.
CSV="$DEFAULT_CSV"
LEVELS='1 4 8 16 32 56 64'
DURATION=12
BUDGET_GB=20
# 1.27x at grid_size 16: every grid re-fetches its one-tile halo, so the bytes on the wire exceed the
# sum of the samplesheet. conf/c8id.config and README.md have the table (1.44x at grid_size 10).
HALO_FACTOR=1.27
# From conf/c8id.config, and only used to turn a recommended total connection count back into the two
# knobs that produce it.
MAXFORKS=7
VOLUME_TB=''
TSV=''
SHUFFLE=1
DRY_RUN=0

log() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,/^# ---/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --csv) CSV="${2:?--csv needs a path}"; shift 2 ;;
            --levels) LEVELS="${2:?--levels needs a list, e.g. '1 8 56'}"; shift 2 ;;
            --duration) DURATION="${2:?--duration needs seconds}"; shift 2 ;;
            --budget-gb) BUDGET_GB="${2:?--budget-gb needs a number}"; shift 2 ;;
            --halo-factor) HALO_FACTOR="${2:?--halo-factor needs a number}"; shift 2 ;;
            --maxforks) MAXFORKS="${2:?--maxforks needs a number}"; shift 2 ;;
            --volume-tb) VOLUME_TB="${2:?--volume-tb needs a number}"; shift 2 ;;
            --tsv) TSV="${2:?--tsv needs a path}"; shift 2 ;;
            # A grid's files are a contiguous block of the samplesheet, so --sequential reproduces one
            # grid's actual request pattern. Shuffled is the default because it is the honest
            # measurement: it cannot be flattered by a cache warmed by the previous level.
            --sequential) SHUFFLE=0; shift ;;
            --dry-run) DRY_RUN=1; shift ;;
            -h|--help) usage; exit 0 ;;
            *) die "unknown argument: $1 (try --help)" ;;
        esac
    done
    [ "$DURATION" -ge 1 ] 2> /dev/null || die "--duration must be a positive integer, got '${DURATION}'"
    [ "$MAXFORKS" -ge 1 ] 2> /dev/null || die "--maxforks must be a positive integer, got '${MAXFORKS}'"
}

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
# The samplesheet schema (assets/schema_tiles.json) fixes the column *names*, not their order, and
# permits extra columns -- Bavaria's export carries a `units` column. So look both up by name, the
# way nf-schema does, rather than trusting position.
extract_urls() {
    awk -F, '
        { sub(/\r$/, "") }
        NR == 1 {
            for (i = 1; i <= NF; i++) { col[$i] = i }
            if (!("url" in col)) { exit 1 }
            u = col["url"]
            next
        }
        $u != "" { print $u }
    ' "$CSV"
}

read_csv() {
    [ -f "$CSV" ] || die "no such file: ${CSV}"

    URLS=()
    if [ "$SHUFFLE" -eq 1 ]; then
        mapfile -t URLS < <(extract_urls | shuf)
    else
        mapfile -t URLS < <(extract_urls)
    fi
    [ "${#URLS[@]}" -gt 0 ] || die "${CSV} has no 'url' column, or no data rows"

    # The samplesheet's own byte total is the best available estimate of what the run must move; the
    # halo factor turns it into bytes on the wire. The fixture is 8.75 GB, which extrapolates to
    # nothing useful, so fall back to README.md's Bavaria figure and say so.
    CSV_BYTES="$(awk -F, '
        { sub(/\r$/, "") }
        NR == 1 { for (i = 1; i <= NF; i++) { col[$i] = i }; s = col["size_bytes"]; next }
        s && $s ~ /^[0-9]+$/ { total += $s }
        END { printf "%.0f", total + 0 }
    ' "$CSV")"

    if [ -n "$VOLUME_TB" ]; then
        VOLUME_SOURCE="--volume-tb"
    else
        VOLUME_TB="$(awk -v b="$CSV_BYTES" -v h="$HALO_FACTOR" 'BEGIN { printf "%.4f", b * h / 1e12 }')"
        VOLUME_SOURCE="${CSV} x ${HALO_FACTOR} halo"
        if awk -v v="$VOLUME_TB" 'BEGIN { exit !(v < 1) }'; then
            log "note: ${CSV} covers only ${VOLUME_TB} TB, too little to extrapolate from -- using"
            log "      README.md's 19 TB Bavaria figure instead. Pass --csv <the real samplesheet>"
            log "      or --volume-tb for your own dataset."
            VOLUME_TB=19
            VOLUME_SOURCE="README.md's Bavaria estimate"
        fi
    fi
}

# One HEAD before anything else: it fails fast on a typo or an unreachable server, and the response
# headers are worth having in the record -- which server software, whether HTTP/2 is offered, and the
# file size the rest of the numbers are about.
probe_server() {
    local url="${URLS[0]}" out
    log "probing ${url}"
    # -I so this costs no body bytes. The write-out line is tagged so one grep can select it along
    # with the headers worth recording: which server software, whether HTTP/2 is on offer, and any
    # cache header that would explain a suspiciously good result later.
    out="$(curl -fsSI --location --max-time 30 --user-agent "$USER_AGENT" \
        --write-out 'benchmark: HTTP/%{http_version} %{http_code}, %{time_total}s to headers\n' \
        "$url")" || die "HEAD ${url} failed -- the server is unreachable or the URL is stale"
    printf '%s\n' "$out" \
        | grep -iE '^(HTTP/|benchmark:|server:|content-length:|accept-ranges:|age:|x-cache:)' \
        | tr -d '\r' | sed 's/^/  /'
}

# ---------------------------------------------------------------------------
# One level of the sweep
# ---------------------------------------------------------------------------
# Each worker is bin/fetch_laz.py's inner loop: one curl per whole file, sequentially, with the same
# flags -- so P workers reproduce `--jobs P` exactly, minus the checksumming (which is CPU on this
# side and invisible to the server).
worker() {
    local outfile="$1" deadline="$2"
    shift 2
    local urls=("$@")
    local n="${#urls[@]}" i=0 remaining url

    while :; do
        remaining=$(( deadline - EPOCHSECONDS ))
        [ "$remaining" -gt 0 ] || break
        url="${urls[$(( i % n ))]}"
        i=$(( i + 1 ))
        # --max-time keeps the last transfer from overrunning the level; its partial bytes still
        # count, which is correct for a throughput measurement. The flags before it are copied from
        # bin/fetch_laz.py's curl().
        curl --silent --show-error --location --fail \
            --connect-timeout 30 \
            --speed-limit 1024 --speed-time 120 \
            --user-agent "$USER_AGENT" \
            --max-time "$remaining" \
            --write-out '%{size_download} %{http_code} %{speed_download}\n' \
            --output /dev/null \
            "$url" >> "$outfile" 2>> "${outfile%.out}.err" || true
    done
}

WORKER_PIDS=()

cleanup() {
    local pid
    for pid in ${WORKER_PIDS[@]+"${WORKER_PIDS[@]}"}; do
        # The curl is the child of the worker subshell, so it has to be killed first or it keeps
        # downloading after the shell it belonged to is gone.
        pkill -P "$pid" 2> /dev/null || true
        kill "$pid" 2> /dev/null || true
    done
    [ -z "${TMPDIR_BENCH:-}" ] || rm -rf "$TMPDIR_BENCH"
}

# run_level <connections>; appends one row to $RESULTS
run_level() {
    local conns="$1"
    local dir="${TMPDIR_BENCH}/level_${conns}"
    mkdir -p "$dir"

    local start end deadline i
    deadline=$(( EPOCHSECONDS + DURATION ))
    start="$EPOCHREALTIME"

    local slice=() j
    WORKER_PIDS=()
    for (( i = 0; i < conns; i++ )); do
        # A strided slice per worker: disjoint URL sets, so nothing in this level is fetched twice.
        # With more workers than the CSV has URLs that is impossible, and report() says so.
        slice=()
        for (( j = i; j < ${#URLS[@]}; j += conns )); do
            slice+=("${URLS[$j]}")
        done
        [ "${#slice[@]}" -gt 0 ] || slice=("${URLS[$(( i % ${#URLS[@]} ))]}")
        worker "${dir}/w${i}.out" "$deadline" "${slice[@]}" &
        WORKER_PIDS+=("$!")
    done
    wait
    WORKER_PIDS=()
    end="$EPOCHREALTIME"

    # Sum what the workers recorded, and be careful about what counts as a failure:
    #
    #   2xx  a transfer, whole or truncated by the deadline. Its bytes count either way, which is
    #        what a throughput measurement wants.
    #   000  no response at all. Overwhelmingly this is the last transfer of a level being started
    #        with a second left on the clock, so --max-time kills it during connect. Counting those
    #        as errors would put a spurious "check your URLs" warning on every clean run.
    #   else  403, 404, 5xx: a real answer that is not the file. Worth shouting about, because a
    #        sweep full of 404s produces a throughput number measured on error pages.
    local stats
    stats="$(awk '
        NF >= 2 {
            if ($2 ~ /^2/)        { bytes += $1; files += 1 }
            else if ($2 == "000") { aborted += 1 }
            else                  { errors += 1 }
        }
        END { printf "%.0f %d %d %d", bytes + 0, files + 0, errors + 0, aborted + 0 }
    ' "${dir}"/*.out)"

    local bytes files errors aborted wall
    read -r bytes files errors aborted <<< "$stats"
    wall="$(awk -v a="$start" -v b="$end" 'BEGIN { printf "%.3f", b - a }')"

    printf '%s\t%s\t%s\t%s\t%s\n' "$conns" "$bytes" "$wall" "$files" "$errors" >> "$RESULTS"
    log "$(awk -v c="$conns" -v b="$bytes" -v w="$wall" -v f="$files" -v e="$errors" \
        'BEGIN { printf "  %3d conns: %8.1f MB in %5.1fs = %7.1f MB/s aggregate, %d transfers, %d errors",
                 c, b / 1e6, w, (w > 0 ? b / w / 1e6 : 0), f, e }')"

    # curl's own stderr, once, when something went wrong: a stale URL or a TLS problem is worth seeing
    # immediately rather than at the end of a sweep whose numbers are meaningless because of it.
    if [ "$errors" -gt 0 ] || { [ "$files" -eq 0 ] && [ "$aborted" -gt 0 ]; }; then
        local first_error
        first_error="$(grep -h -m 1 . "${dir}"/*.err 2> /dev/null | head -n 1 || true)"
        [ -z "$first_error" ] || log "             first error: ${first_error}"
    fi

    TOTAL_BYTES="$(awk -v t="$TOTAL_BYTES" -v b="$bytes" 'BEGIN { printf "%.0f", t + b }')"
}

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
report() {
    awk -F'\t' \
        -v volume_tb="$VOLUME_TB" -v volume_source="$VOLUME_SOURCE" \
        -v maxforks="$MAXFORKS" -v urlcount="${#URLS[@]}" '
    function human(b) {
        if (b >= 1e12) { return sprintf("%.2f TB", b / 1e12) }
        if (b >= 1e9)  { return sprintf("%.2f GB", b / 1e9) }
        return sprintf("%.0f MB", b / 1e6)
    }
    {
        n++
        conns[n] = $1 + 0; bytes[n] = $2 + 0; wall[n] = $3 + 0; files[n] = $4 + 0; errors[n] = $5 + 0
        agg[n] = (wall[n] > 0) ? bytes[n] / wall[n] / 1e6 : 0
        per[n] = agg[n] / conns[n]
        moved += bytes[n]
        errs += errors[n]
        if (agg[n] > best) { best = agg[n]; best_at = conns[n] }
        if (conns[n] == 1) { base = agg[n] }
    }
    END {
        if (n == 0) { print "no levels completed"; exit 1 }

        printf "\n%6s  %9s  %10s  %7s  %14s  %14s\n", \
               "conns", "transfers", "bytes", "wall", "aggregate", "per conn"
        printf "%6s  %9s  %10s  %7s  %14s  %14s\n", \
               "-----", "---------", "----------", "-------", "--------------", "--------------"
        for (i = 1; i <= n; i++) {
            printf "%6d  %9d  %10s  %6.1fs  %9.1f MB/s  %9.1f MB/s%s\n", \
                   conns[i], files[i], human(bytes[i]), wall[i], agg[i], per[i], \
                   (errors[i] ? sprintf("  (%d errors)", errors[i]) : "")
        }
        printf "\n%s transferred in total.\n", human(moved)
        if (errs > 0) {
            printf "WARNING: %d transfers returned something other than the file (403/404/5xx).\n", errs
            print  "         Check the samplesheet URLs are current -- a throughput number measured on"
            print  "         error pages is worse than no number."
        }

        if (best <= 0) {
            print "\nNothing was transferred: every request failed. The numbers above mean nothing."
            exit 1
        }

        printf "\nBest aggregate: %.1f MB/s at %d connections.\n", best, best_at

        # The knee: the fewest connections still within 10 per cent of the best aggregate. Anything
        # past it is load on a public server that buys this run nothing.
        knee = best_at
        for (i = 1; i <= n; i++) {
            if (agg[i] >= 0.9 * best) { knee = conns[i]; break }
        }
        jobs = int((knee + maxforks - 1) / maxforks)
        if (jobs < 1) { jobs = 1 }

        if (base > 0 && best <= 1.25 * base) {
            print  ""
            print  "The cap is on the AGGREGATE, not per connection: opening more streams divided the"
            printf "same ~%.0f MB/s among them instead of adding to it. This is what the development\n", best
            print  "machine saw. Raising params.download_jobs or maxForks cannot help; only a bulk"
            print  "transfer, a mirror, or a different source can. Keep download_jobs low (4 or less)"
            print  "so the run is not needlessly rude about it."
        } else if (base > 0) {
            printf "\nParallelism helps: %.1f MB/s on one connection, %.1f MB/s at %d (%.1fx).\n", \
                   base, best, best_at, best / base
            printf "The knee is ~%d concurrent connections, and a run opens\n", knee
            printf "params.download_jobs x PULLAUTA_GRID maxForks of them, so to land near %d:\n\n", knee
            printf "    --download_jobs %d       (at maxForks %d: %d x %d = %d connections)\n", \
                   jobs, maxforks, jobs, maxforks, jobs * maxforks
            printf "\nGoing past the knee adds load without adding throughput. Note that disk, not the\n"
            printf "network, is what caps maxForks (~117 GB per concurrent grid); raise download_jobs\n"
            printf "rather than maxForks to add connections.\n"
        }

        # The question the whole benchmark exists to answer.
        hours = volume_tb * 1e12 / (best * 1e6) / 3600
        if (hours >= 48) { span = sprintf("%.1f h (%.1f days)", hours, hours / 24) }
        else             { span = sprintf("%.1f h", hours) }
        printf "\nAt %.1f MB/s, %.1f TB (%s) takes %s of wall clock,\n", \
               best, volume_tb, volume_source, span
        print  "assuming the rate holds -- this is a steady-state measurement over seconds, not hours."
        if (hours > 32) {
            printf "\nThat is longer than the render (21-32 h on 128 vCPU), so the run is DOWNLOAD-BOUND:\n"
            print  "the compute sizing in conf/c8id.config is not the thing to tune. Restructure the"
            print  "transfer -- ask the provider about bulk access or a mirror, or stage the data into"
            print  "S3 once and run from there -- before booking the instance for days."
        } else {
            print  "\nThat fits inside the 21-32 h render window, so the run is COMPUTE-BOUND and the"
            print  "estimates in README.md hold. Download and render overlap: PULLAUTA_GRID fetches and"
            print  "renders in one task, so the two phases are not added together."
        }
        if (urlcount < 100) {
            printf "\nCaveat: only %d distinct URLs were available, so levels above that re-fetched files\n", urlcount
            print  "and may have been served from a cache. Re-run with --csv <the real samplesheet> for a"
            print  "number worth planning around."
        }
    }' "$RESULTS"
}

# ---------------------------------------------------------------------------
main() {
    parse_args "$@"
    read_csv

    local levels=() conns
    read -r -a levels <<< "$LEVELS"
    [ "${#levels[@]}" -gt 0 ] || die '--levels is empty'
    # Validated here rather than in the loop: finding out that the last level was a typo after
    # transferring twenty gigabytes would be a poor joke.
    for conns in "${levels[@]}"; do
        [ "$conns" -ge 1 ] 2> /dev/null || die "--levels must be positive integers, got '${conns}'"
    done

    local order='as listed in the CSV (one grid, contiguous)'
    [ "$SHUFFLE" -eq 0 ] || order='shuffled (a cache-cold sample)'

    log "csv          ${CSV}: ${#URLS[@]} URLs, $(awk -v b="$CSV_BYTES" 'BEGIN { printf "%.2f GB", b / 1e9 }')"
    log "order        ${order}"
    log "levels       ${LEVELS} concurrent connections"
    log "duration     ${DURATION}s per level (${#levels[@]} levels, so ~$(( DURATION * ${#levels[@]} ))s plus setup)"
    log "budget       ${BUDGET_GB} GB, after which the sweep stops early"
    log "extrapolate  ${VOLUME_TB} TB (${VOLUME_SOURCE})"
    log "destination  /dev/null (this measures the network, not the disk)"

    if [ "$DRY_RUN" -eq 1 ]; then
        log ''
        log 'dry run: nothing was transferred.'
        return 0
    fi

    TMPDIR_BENCH="$(mktemp -d)"
    RESULTS="${TMPDIR_BENCH}/results.tsv"
    TOTAL_BYTES=0
    trap cleanup EXIT INT TERM

    probe_server
    log ''

    # The budget only ever binds on a *fast* server -- a slow one cannot move 20 GB in seven 12 s
    # levels -- so being cut off here is itself weak evidence that the run is not download-bound. Say
    # exactly what was skipped anyway, because the high levels are the interesting ones.
    local i
    for (( i = 0; i < ${#levels[@]}; i++ )); do
        conns="${levels[$i]}"
        if awk -v t="$TOTAL_BYTES" -v b="$BUDGET_GB" 'BEGIN { exit !(t >= b * 1e9) }'; then
            warn "the ${BUDGET_GB} GB budget is spent; not run: ${levels[*]:$i} connections"
            warn "  Raise --budget-gb, shorten --duration, or measure just the endpoints:"
            warn "  --levels '1 ${levels[-1]}' is enough to tell a per-connection cap from an aggregate one."
            break
        fi
        run_level "$conns"
    done

    report

    if [ -n "$TSV" ]; then
        { printf 'connections\tbytes\twall_seconds\ttransfers\terrors\n'; cat "$RESULTS"; } > "$TSV"
        log ''
        log "numbers written to ${TSV}"
    fi
}

main "$@"
