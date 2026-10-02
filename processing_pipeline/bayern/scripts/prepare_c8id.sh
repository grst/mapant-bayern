#!/usr/bin/env bash
# Prepare a fresh Amazon Linux 2023 c8id instance to run this pipeline: Java, Nextflow, Docker, the
# instance-store NVMe devices striped into one scratch filesystem, and the operator tools a run of
# this length wants on hand (rclone, uv, glances, gh).
#
# Run it on the instance, as root, after `ssh ec2-user@...`:
#
#   sudo scripts/prepare_c8id.sh                    # everything; safe to re-run at any time
#   sudo scripts/prepare_c8id.sh --scratch-only     # only assemble/mount the scratch volume
#   sudo scripts/prepare_c8id.sh --force            # re-create the array, DESTROYING what is on it
#   sudo scripts/prepare_c8id.sh --no-docker-nvme   # keep docker's images on the root volume
#   sudo scripts/prepare_c8id.sh --mount-point /scratch
#
# Then log out and back in (the docker group only applies to a new login) and:
#
#   nextflow run . -profile docker,c8id --tiles_csv ... --osm_pbf ...
#
# ---------------------------------------------------------------------------
# Why an instance needs preparing at all
# ---------------------------------------------------------------------------
# conf/c8id.config sizes the pipeline for one c8id.32xlarge and then names two things that have to be
# "set up outside the pipeline": workDir on the striped instance NVMe, and a durable place to
# publish. This script is the first of those, plus the three packages the run needs. Everything it
# does is a property of *this machine*, which is exactly what nextflow.config deliberately contains
# none of -- that is what lets the same pipeline run on a laptop, here, and on an HPC scheduler.
#
# Four decisions in here are not obvious, so they are argued rather than just implemented:
#
# 1. RAID-0 across the instance-store devices, not one filesystem per device.
#
#    Peak disk is `maxForks x peak disk per task` and it all lives under one workDir: 7 concurrent
#    grids x ~117 GB ~= 820 GB at `grid_size` 16. Two separate 1.9 TB filesystems cannot host that
#    unless the operator partitions the task set by hand, and Nextflow has no notion of spreading
#    one workDir over two mounts. Striping also doubles the bandwidth the download and
#    karttapullautin's temporaries see, and RAID-0's usual objection -- one device dies, everything
#    is lost -- is free here, because instance storage is already lost when the instance stops.
#
# 2. The scratch volume is NOT put in /etc/fstab.
#
#    Instance storage is wiped on stop/start, so the array simply is not there on the next boot: an
#    fstab entry would then fail, and without `nofail` it blocks boot on a machine reachable only
#    over ssh. `--boot-unit` (on by default) installs a systemd oneshot that re-runs this script's
#    scratch step instead, which re-creates the array when it is gone and re-assembles it when it
#    survived (a plain reboot keeps instance-store contents; a stop/start does not).
#
# 3. Docker's data-root goes on the scratch volume.
#
#    The stock AL2023 root volume is 8 GiB and the pipeline's four images are several GB together.
#    Filling the root volume is a bad failure -- it takes sshd and the Nextflow head process with
#    it -- and re-pulling images after a stop/start costs a couple of minutes against a run measured
#    in days. `--no-docker-nvme` opts out if the root volume was made large enough.
#
# 4. NXF_WORK, NXF_TEMP and TMPDIR are exported globally, not left to `-w`.
#
#    Forgetting `-w /mnt/nvme/work` does not fail: it quietly starts filling the 8 GiB root volume
#    and dies hours later with the run's work already spent. The environment file makes the correct
#    thing the default and `-w` an override.
#
# The one thing this script deliberately does NOT do is decide where the pyramid is published.
# `--outdir` is a per-run choice between EBS, S3 and keeping it on the scratch volume with
# `publish_mode 'link'`; see conf/c8id.config.
set -euo pipefail

readonly MANAGED_MARKER='# managed by scripts/prepare_c8id.sh -- edits will be overwritten'
readonly MD_NAME='mapant-scratch'
readonly FS_LABEL='mapant-scr'          # XFS labels are capped at 12 characters
readonly INSTALLED_COPY='/usr/local/sbin/mapant-prepare-c8id'
readonly BOOT_UNIT='/etc/systemd/system/mapant-scratch.service'
readonly ENV_FILE='/etc/profile.d/mapant.sh'
readonly LIMITS_FILE='/etc/security/limits.d/99-mapant.conf'

# The model string every EC2 NVMe instance-store device reports. EBS volumes -- including the root
# volume, which is also an /dev/nvme*n1 here -- report 'Amazon Elastic Block Store', so this is what
# keeps the script from ever touching persistent storage.
readonly INSTANCE_STORE_MODEL='Amazon EC2 NVMe Instance Storage'

MOUNT_POINT='/mnt/nvme'
TARGET_USER="${SUDO_USER:-ec2-user}"
FORCE=0
SCRATCH_ONLY=0
DOCKER_ON_NVME=1
BOOT_UNIT_WANTED=1

log() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# The usage block is the header down to the first '# ---' rule, so adding a line up there does not
# silently truncate --help.
usage() {
    sed -n '2,/^# ---/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --mount-point) MOUNT_POINT="${2:?--mount-point needs a path}"; shift 2 ;;
            --user) TARGET_USER="${2:?--user needs a name}"; shift 2 ;;
            --force) FORCE=1; shift ;;
            --scratch-only) SCRATCH_ONLY=1; shift ;;
            --no-docker-nvme) DOCKER_ON_NVME=0; shift ;;
            --no-boot-unit) BOOT_UNIT_WANTED=0; shift ;;
            -h|--help) usage; exit 0 ;;
            *) die "unknown argument: $1 (try --help)" ;;
        esac
    done
    readonly MOUNT_POINT TARGET_USER FORCE SCRATCH_ONLY DOCKER_ON_NVME BOOT_UNIT_WANTED
}

# write_if_changed <path> [mode], content on stdin. Returns 1 when the file was already correct,
# which keeps a re-run quiet and lets callers restart a service only when something actually moved.
write_if_changed() {
    local path="$1" mode="${2:-0644}" tmp
    tmp="$(mktemp)"
    cat > "$tmp"
    if [ -f "$path" ] && cmp -s "$tmp" "$path"; then
        rm -f "$tmp"
        return 1
    fi
    install -m "$mode" "$tmp" "$path"
    rm -f "$tmp"
    return 0
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
# Everything here is a warning rather than an error except being root: a c8i without instance
# storage, a smaller c8id or a different AL release all still work, they just need the operator to
# know which of conf/c8id.config's numbers no longer apply.

# Best-effort IMDSv2 lookup. Returns non-zero off EC2 (or with the hop limit set to 1 and this
# running in a container), which is fine -- nothing below depends on it.
imds() {
    local token
    token="$(curl -fsS -X PUT --max-time 2 \
        -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
        http://169.254.169.254/latest/api/token 2>/dev/null)" || return 1
    curl -fsS --max-time 2 -H "X-aws-ec2-metadata-token: ${token}" \
        "http://169.254.169.254/latest/meta-data/$1" 2>/dev/null || return 1
}

preflight() {
    [ "$(id -u)" -eq 0 ] || die "run as root: sudo ${0}"
    id "$TARGET_USER" > /dev/null 2>&1 \
        || die "no such user: ${TARGET_USER} (pass --user; \$SUDO_USER was '${SUDO_USER:-}')"

    local id_like='' version_id=''
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        id_like="${ID:-}"
        version_id="${VERSION_ID:-}"
    fi
    if [ "$id_like" != amzn ] || [ "$version_id" != 2023 ]; then
        warn "expected Amazon Linux 2023, found '${id_like} ${version_id}' -- package names below may differ"
    fi

    [ "$(uname -m)" = x86_64 ] \
        || warn "$(uname -m) is not x86_64: the karttapullautin image ships x86-64 builds only"

    local instance_type
    if instance_type="$(imds instance-type)"; then
        log "instance type: ${instance_type}"
        case "$instance_type" in
            c8id.*) ;;
            *d.*|*d-*) warn "not a c8id; conf/c8id.config's sizing assumes Granite Rapids and 3.8 TB of NVMe" ;;
            *) warn "'${instance_type}' has no instance store -- there is nothing for this script to stripe" ;;
        esac
    fi

    local cpus; cpus="$(nproc)"
    [ "$cpus" -ge 128 ] || warn "${cpus} vCPU: conf/c8id.config is sized for the 32xlarge (128 vCPU, executor.cpus = 124, maxForks 7). Lower maxForks and executor.cpus to match, or disk and CPU will both be oversubscribed."
}

# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------
install_packages() {
    step 'Installing packages'

    # Deliberately no `dnf update`: it can pull a new kernel, which needs a reboot to take effect and
    # turns "prepare the instance" into two steps. Everything below comes from the AL2023 repos the
    # AMI already trusts.
    #
    #   docker            -- the run's container engine (`-profile docker`)
    #   mdadm, nvme-cli   -- stripe and identify the instance store
    #   xfsprogs          -- XFS over the array: it is AL2023's own default, and it is the filesystem
    #                        that copes with ~72k tile files plus 30 GB laz staging per task
    #   git               -- to clone this pipeline
    #   tmux              -- the run is measured in days; nobody wants it tied to an ssh session
    #   jq                -- edits /etc/docker/daemon.json in place instead of overwriting it
    #   unzip             -- rclone upstream ships a zip
    local packages=(docker mdadm nvme-cli xfsprogs git tmux jq unzip)
    dnf install -y "${packages[@]}"

    # Nextflow needs Java 17+; 21 is what upstream tests against. Corretto is in the AL2023 repos, so
    # there is no third-party repository to add.
    dnf install -y java-21-amazon-corretto-headless \
        || dnf install -y java-17-amazon-corretto-headless \
        || die 'no Amazon Corretto 21 or 17 available; install a JDK 17+ manually'

    log "java: $(java -version 2>&1 | head -n 1)"
}

# ---------------------------------------------------------------------------
# Scratch volume
# ---------------------------------------------------------------------------

# Print the instance-store block devices, one per line. `nvme id-ctrl` would work too, but
# /sys/block/<dev>/device/model is the same string without parsing a second tool's output, and it is
# readable when nvme-cli is not installed yet.
scratch_devices() {
    local dev name model
    for dev in /dev/nvme*n1; do
        [ -b "$dev" ] || continue
        name="${dev##*/}"
        model="$(cat "/sys/block/${name}/device/model" 2>/dev/null || true)"
        # The attribute is space-padded to a fixed width, so match on a prefix rather than equality.
        case "$model" in
            "${INSTANCE_STORE_MODEL}"*) printf '%s\n' "$dev" ;;
        esac
    done
}

# The md device currently built on top of <device>, if any, via /sys/block/<dev>/holders.
md_holder_of() {
    local name="${1##*/}" holder
    holder="$(find "/sys/block/${name}/holders" -mindepth 1 -maxdepth 1 -name 'md*' -printf '%f\n' \
        2>/dev/null | head -n 1)"
    [ -n "$holder" ] || return 1
    printf '/dev/%s\n' "$holder"
}

# Take a set of devices apart so they can be re-created: only ever reached with --force.
tear_down() {
    local devices=("$@") dev md
    if findmnt -rn "$MOUNT_POINT" > /dev/null 2>&1; then
        log "unmounting ${MOUNT_POINT}"
        umount "$MOUNT_POINT"
    fi
    for dev in "${devices[@]}"; do
        if md="$(md_holder_of "$dev")"; then
            log "stopping ${md}"
            mdadm --stop "$md" > /dev/null 2>&1 || true
        fi
    done
    for dev in "${devices[@]}"; do
        mdadm --zero-superblock "$dev" > /dev/null 2>&1 || true
        wipefs -a "$dev" > /dev/null
    done
}

# Print the block device that should carry the filesystem: the single instance-store device, or the
# RAID-0 across all of them. Re-assembles an array that survived a reboot rather than re-creating it.
scratch_target() {
    local devices=("$@") md
    if [ "${#devices[@]}" -eq 1 ]; then
        printf '%s\n' "${devices[0]}"
        return
    fi

    if md="$(md_holder_of "${devices[0]}")"; then
        log "reusing assembled array ${md}" >&2
        printf '%s\n' "$md"
        return
    fi

    # An md superblock that is present but not assembled means the array survived a reboot.
    if mdadm --examine "${devices[0]}" > /dev/null 2>&1; then
        log "assembling existing array from ${devices[*]}" >&2
        mdadm --assemble --scan --run > /dev/null 2>&1 || true
        if md="$(md_holder_of "${devices[0]}")"; then
            printf '%s\n' "$md"
            return
        fi
        warn "an md superblock is present but the array would not assemble; re-run with --force to re-create it"
        return 1
    fi

    log "creating RAID-0 over ${#devices[@]} devices: ${devices[*]}" >&2
    # --homehost=any so the array still assembles after the instance comes back with a different
    # hostname; a named array gives a stable /dev/md/<name> instead of a number that shifts.
    mdadm --create "/dev/md/${MD_NAME}" \
        --name="$MD_NAME" --homehost=any \
        --level=0 --chunk=512 --raid-devices="${#devices[@]}" \
        --run "${devices[@]}" >&2
    printf '/dev/md/%s\n' "$MD_NAME"
}

setup_scratch() {
    step "Preparing the scratch volume at ${MOUNT_POINT}"

    local devices=()
    mapfile -t devices < <(scratch_devices)
    [ "${#devices[@]}" -gt 0 ] || die "no instance-store NVMe devices found. This instance type has none, or they are already in use by something this script did not create."
    log "instance-store devices: ${devices[*]}"

    if [ "$FORCE" -eq 1 ]; then
        warn "--force: destroying everything on ${devices[*]}"
        tear_down "${devices[@]}"
    elif findmnt -rn "$MOUNT_POINT" > /dev/null 2>&1; then
        log "already mounted:"
        findmnt -no SOURCE,TARGET,FSTYPE,SIZE "$MOUNT_POINT"
        ensure_scratch_dirs
        return
    fi

    local target fstype
    target="$(scratch_target "${devices[@]}")" || die 'could not obtain a scratch device'

    fstype="$(blkid -o value -s TYPE "$target" 2>/dev/null || true)"
    if [ "$fstype" = xfs ]; then
        log "reusing the existing XFS on ${target}"
    elif [ -n "$fstype" ]; then
        die "${target} already holds a '${fstype}' filesystem. Re-run with --force to destroy it."
    else
        log "mkfs.xfs on ${target}"
        # mkfs.xfs reads the stripe geometry off the md device by itself, so no su/sw here.
        mkfs.xfs -f -L "$FS_LABEL" "$target" > /dev/null
    fi

    # Mounted by device rather than by LABEL/UUID: the label is this script's own and there is
    # exactly one such volume, but a stale duplicate label from an earlier AMI would make a
    # LABEL= mount ambiguous, and getting that wrong means writing the run somewhere else entirely.
    mkdir -p "$MOUNT_POINT"
    # noatime: every laz file, temporary and finished tile would otherwise cost a metadata write.
    mount -o noatime "$target" "$MOUNT_POINT"
    findmnt -no SOURCE,TARGET,FSTYPE,SIZE "$MOUNT_POINT"

    # /etc/mdadm.conf is only an aid to assembly (`mdadm --assemble --scan` above works from the
    # superblocks alone), but it makes what the array *should* be explicit for anyone debugging.
    if [ "${#devices[@]}" -gt 1 ]; then
        mdadm --detail --scan > /etc/mdadm.conf
    fi

    ensure_scratch_dirs
}

ensure_scratch_dirs() {
    # work    -- NXF_WORK: laz downloads, karttapullautin temporaries, every task's scratch
    # results -- a plausible --outdir when publishing with publish_mode 'link'
    # tmp     -- NXF_TEMP/TMPDIR, kept off the small root volume
    local dir group
    group="$(id -gn "$TARGET_USER")"
    for dir in work results tmp; do
        install -d -o "$TARGET_USER" -g "$group" -m 0755 "${MOUNT_POINT}/${dir}"
    done
    # Docker's data-root stays root-owned and unreadable to others, as on /var/lib/docker.
    [ "$DOCKER_ON_NVME" -eq 0 ] || install -d -o root -g root -m 0710 "${MOUNT_POINT}/docker"
}

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
setup_docker() {
    step 'Configuring docker'

    local changed=0
    if [ "$DOCKER_ON_NVME" -eq 1 ]; then
        local daemon_json='/etc/docker/daemon.json' tmp
        mkdir -p /etc/docker
        tmp="$(mktemp)"
        # jq rather than a heredoc so an existing daemon.json (a proxy, a registry mirror) survives.
        if [ -s "$daemon_json" ]; then
            jq --arg root "${MOUNT_POINT}/docker" '.["data-root"] = $root' "$daemon_json" > "$tmp"
        else
            jq -n --arg root "${MOUNT_POINT}/docker" '{"data-root": $root}' > "$tmp"
        fi
        if write_if_changed "$daemon_json" 0644 < "$tmp"; then
            changed=1
            log "data-root -> ${MOUNT_POINT}/docker"
        fi
        rm -f "$tmp"
    fi

    systemctl enable docker > /dev/null
    if [ "$changed" -eq 1 ] && systemctl is-active --quiet docker; then
        log 'restarting docker to pick up the new data-root'
        systemctl restart docker
    else
        systemctl start docker
    fi

    # Nextflow shells out to `docker`, so the user running it needs the group. This takes effect on
    # the next login only -- the summary says so, because "permission denied on
    # /var/run/docker.sock" ten seconds into a run is an annoying way to find out.
    if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx docker; then
        log "${TARGET_USER} is already in the docker group"
    else
        usermod -aG docker "$TARGET_USER"
        log "added ${TARGET_USER} to the docker group (needs a new login)"
    fi

    log "docker $(docker version --format '{{.Server.Version}}' 2> /dev/null || echo '?'), images in $(docker info --format '{{.DockerRootDir}}' 2> /dev/null || echo '?')"
}

# ---------------------------------------------------------------------------
# Nextflow and the run environment
# ---------------------------------------------------------------------------
install_nextflow() {
    step 'Installing Nextflow'

    if command -v nextflow > /dev/null 2>&1; then
        log "already installed: $(command -v nextflow)"
    else
        local tmp
        tmp="$(mktemp -d)"
        # The installer drops `nextflow` into the working directory; NXF_VER, if the caller exported
        # one, pins which distribution the launcher then self-installs.
        ( cd "$tmp" && curl -fsSL https://get.nextflow.io | bash > /dev/null )
        install -m 0755 "${tmp}/nextflow" /usr/local/bin/nextflow
        rm -rf "$tmp"
    fi

    # First run as the target user, not root: it self-installs the distribution under the *user's*
    # ~/.nextflow, and doing it now means the first real run does not stop to download a JAR.
    runuser -u "$TARGET_USER" -- nextflow -version 2>&1 | sed -n '2,4p' || true
}

# ---------------------------------------------------------------------------
# Operator tools: rclone, uv, glances, gh
# ---------------------------------------------------------------------------
# None of these are pipeline dependencies -- a run needs java, nextflow and docker and nothing else --
# so a failure in here warns and carries on rather than aborting an otherwise prepared instance. They
# are what an operator of *this* run wants to hand:
#
#   rclone   the pyramid is millions of small files and ${MOUNT_POINT} dies with the instance. rclone's
#            --transfers/--checkers concurrency is what turns that sync from days into hours; it also
#            does S3, EBS-to-elsewhere and resumable retries without a second tool.
#   uv       runs tests/ and bin/*.py outside a container (`uv venv && uv pip install -r
#            tests/requirements.txt`, the CLAUDE.md recipe without waiting for pip), and installs
#            glances without touching the system python.
#   glances  one screen for the four things that go wrong on this box, which no single stock tool
#            shows together: CPU saturation, NVMe fill, disk I/O and network throughput -- the last
#            being the suspected bottleneck for the whole run.
#   gh       filing failures.tsv rows against karttapullautin upstream, and opening a PR against this
#            repo, without an operator having to set up a personal token or clone credentials by hand.
#
# rclone, uv and glances each come from their own upstream; gh is the one of the four that has an
# AL2023-compatible package repo, added the way GitHub's own install instructions do it.
install_host_tools() {
    step 'Installing rclone, uv, glances and gh'
    install_rclone || warn 'rclone not installed -- the final sync off the instance will need another tool'
    install_uv || warn 'uv not installed -- and glances below depends on it'
    install_glances || warn 'glances not installed'
    install_gh || warn 'gh not installed'
}

install_rclone() {
    if command -v rclone > /dev/null 2>&1; then
        log "rclone already installed: $(rclone version | head -n 1)"
        return 0
    fi

    local version="${RCLONE_VERSION:-}"
    if [ -z "$version" ]; then
        # downloads.rclone.org/version.txt is a single line, 'rclone v1.71.1'. Reading the version
        # from upstream rather than pinning it here keeps a stale pin out of a script nobody will
        # revisit, while still downloading one *specific* release -- which is what makes the checksum
        # below worth anything. Pin RCLONE_VERSION if a run has to be reconstructible later.
        version="$(curl -fsS --max-time 30 https://downloads.rclone.org/version.txt \
            | awk '{ print $2 }')" || true
    fi
    if [ -z "$version" ]; then
        warn 'could not resolve the current rclone version; re-run with RCLONE_VERSION=v1.71.1 (say)'
        return 1
    fi

    local tmp base zip
    tmp="$(mktemp -d)"
    base="https://downloads.rclone.org/${version}"
    zip="rclone-${version}-linux-amd64.zip"
    (
        set -e
        curl -fsSL --max-time 300 -o "${tmp}/${zip}" "${base}/${zip}"
        curl -fsSL --max-time 30 -o "${tmp}/SHA256SUMS" "${base}/SHA256SUMS"
        cd "$tmp"
        # Only our own line, so an unrelated missing artifact in SHA256SUMS is not a failure.
        grep -F "$zip" SHA256SUMS | sha256sum --check --status -
        # -j: the archive has a versioned top-level directory that is of no use in /usr/local/bin.
        unzip -q -j -o "$zip" '*/rclone'
    ) || { rm -rf "$tmp"; warn "rclone ${version} could not be downloaded or failed its checksum"; return 1; }

    install -m 0755 "${tmp}/rclone" /usr/local/bin/rclone
    rm -rf "$tmp"
    log "rclone $(rclone version | head -n 1) (checksum verified)"
}

install_uv() {
    if command -v uv > /dev/null 2>&1; then
        log "uv already installed: $(uv --version)"
        return 0
    fi
    # UV_INSTALL_DIR: system-wide rather than ~/.local/bin, so root, ec2-user and the boot unit all
    # see the same uv. UV_NO_MODIFY_PATH: no edits to anyone's shell rc -- /usr/local/bin is already
    # on the default PATH, and ${ENV_FILE} is where this script puts environment it owns.
    local url='https://astral.sh/uv/install.sh'
    [ -z "${UV_VERSION:-}" ] || url="https://astral.sh/uv/${UV_VERSION}/install.sh"
    curl -fsSL --max-time 120 "$url" \
        | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh > /dev/null || return 1
    log "uv $(uv --version)"
}

install_glances() {
    if command -v glances > /dev/null 2>&1; then
        log "glances already installed: $(glances --version 2>&1 | head -n 1)"
        return 0
    fi
    command -v uv > /dev/null 2>&1 || return 1

    # A uv-managed 3.13 rather than AL2023's system python (3.9): glances owns its interpreter, so a
    # dnf update cannot break it and nothing lands in the system site-packages -- which matters
    # because the same python is what dnf itself runs on.
    UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin \
        uv tool install --quiet --python 3.13 glances || return 1
    log "glances $(glances --version 2>&1 | head -n 1)"
}

install_gh() {
    if command -v gh > /dev/null 2>&1; then
        log "gh already installed: $(gh --version | head -n 1)"
        return 0
    fi
    dnf install -y 'dnf-command(config-manager)' > /dev/null || return 1
    dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo > /dev/null || return 1
    dnf install -y gh > /dev/null || return 1
    log "gh $(gh --version | head -n 1)"
}

# ---------------------------------------------------------------------------
write_environment() {
    step "Writing ${ENV_FILE} and ${LIMITS_FILE}"

    if write_if_changed "$ENV_FILE" 0644 <<EOF
${MANAGED_MARKER}
# NXF_WORK is the whole point of this instance's local NVMe: it holds every grid's laz files and
# karttapullautin's temporaries (~117 GB per concurrent grid at grid_size 16). Left on the root
# volume the run dies of ENOSPC hours in. \`-w\` on the command line still overrides it.
export NXF_WORK='${MOUNT_POINT}/work'
export NXF_TEMP='${MOUNT_POINT}/tmp'
export TMPDIR='${MOUNT_POINT}/tmp'

# The head JVM tracks every task of a run that has tens of thousands of them, and validates a 72k-row
# samplesheet up front. The default heap is sized for a laptop.
export NXF_OPTS='-Xms2g -Xmx16g'
EOF
    then log 'environment file updated'; fi

    # A full Bavaria run has ~4,500 grid tasks and ~1,600 tiling tasks, each with staged inputs and
    # published outputs; the head process holds a lot of descriptors open at once.
    if write_if_changed "$LIMITS_FILE" 0644 <<EOF
${MANAGED_MARKER}
*  soft  nofile  65536
*  hard  nofile  262144
EOF
    then log 'nofile limits updated (applies at next login)'; fi
}

# ---------------------------------------------------------------------------
# Boot unit
# ---------------------------------------------------------------------------
# The unit runs an installed *copy* of this script, so it does not depend on a git checkout under
# some user's home staying where it was. Re-running the script refreshes the copy.
install_boot_unit() {
    step "Installing ${BOOT_UNIT}"

    install -m 0755 "${BASH_SOURCE[0]}" "$INSTALLED_COPY"

    local args="--scratch-only --mount-point ${MOUNT_POINT} --user ${TARGET_USER}"
    [ "$DOCKER_ON_NVME" -eq 1 ] || args="${args} --no-docker-nvme"

    if write_if_changed "$BOOT_UNIT" 0644 <<EOF
${MANAGED_MARKER}
[Unit]
Description=Assemble and mount the mapant NVMe scratch volume
Documentation=https://github.com/grst/mapant
# Ordered before docker because docker's data-root lives on this volume: started the other way
# round, docker would create /mnt/nvme/docker on the root volume and then be shadowed by the mount.
After=local-fs.target
Before=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=${INSTALLED_COPY} ${args}
StandardOutput=journal

[Install]
WantedBy=multi-user.target
EOF
    then systemctl daemon-reload; fi

    systemctl enable mapant-scratch.service > /dev/null
    log 'enabled: the array is re-created (stop/start) or re-assembled (reboot) at boot'
}

# ---------------------------------------------------------------------------
summary() {
    step 'Ready'
    df -h "$MOUNT_POINT" | sed -n '1,2p'
    cat <<EOF

Log out and back in (docker group, nofile limits, ${ENV_FILE}), then:

  1. Benchmark the download from THIS node before planning anything. README.md's estimate of
     "about a day and a half" holds only above ~200 MB/s; a development machine saw 30 MB/s, which
     would make the same run take over a week and the compute sizing irrelevant.

       scripts/benchmark_download.sh --dry-run     # what it will transfer, and from where
       scripts/benchmark_download.sh

     It sweeps connection counts up to the ~56 the c8id profile actually opens
     (download_jobs x PULLAUTA_GRID maxForks), which is the number that decides this, and prints the
     extrapolated wall clock for the full input.

  2. Check the ISA dispatch picks the AVX-512 build on Granite Rapids -- the first line of a
     PULLAUTA_GRID log should read "pullauta: ISA variant v4".

  3. A miniature end-to-end run first (~15 min, downloads ~7.4 GB), then recompute the per-tile
     cost from its trace before committing to the full one:

       tmux new -s mapant
       git clone https://github.com/grst/mapant && cd mapant
       nextflow run . -profile docker,c8id,test_immenstadt --outdir ${MOUNT_POINT}/results

  4. The real run. workDir is already ${MOUNT_POINT}/work via NXF_WORK:

       nextflow run . -profile docker,c8id \\
           --tiles_csv tiles.csv --osm_pbf region.osm.pbf \\
           --outdir ${MOUNT_POINT}/results

     ${MOUNT_POINT} is instance storage and is GONE when the instance stops. Either publish to EBS
     or S3 with --publish_mode copy, or keep the pyramid here with 'link' during the run (much
     cheaper for millions of small tiles) and sync it off once at the end:

       rclone copy --transfers 64 --checkers 64 --s3-no-check-bucket --fast-list \\
           ${MOUNT_POINT}/results s3:my-bucket/mapant

  5. While it runs: \`glances\` for CPU, NVMe fill, disk I/O and network on one screen (the network
     row is the one to watch), \`df -h ${MOUNT_POINT}\` against the ~1.2 TB peak, and
     \`${MOUNT_POINT}/results/pipeline_info/trace.txt\` for per-task cost. For the tests and bin/*.py
     outside a container: \`uv venv && uv pip install -r tests/requirements.txt\`.
EOF
}

main() {
    parse_args "$@"

    if [ "$SCRATCH_ONLY" -eq 1 ]; then
        [ "$(id -u)" -eq 0 ] || die 'run as root'
        setup_scratch
        return
    fi

    preflight
    install_packages
    setup_scratch
    setup_docker
    install_nextflow
    install_host_tools
    write_environment
    [ "$BOOT_UNIT_WANTED" -eq 0 ] || install_boot_unit
    summary
}

main "$@"
