#!/usr/bin/env bash
# ifinmail docker_clean.sh — keep Docker from filling the disk.
#
#   docker_clean.sh            trim what builds and updates leave behind (daily cron, after updates)
#   docker_clean.sh --deep     also empty the whole build cache (the next build is slower)
#   docker_clean.sh --dry-run  only show what would be removed
#
# Every update rebuilds the images, and each build leaves layers in the build cache and the
# previous image behind without a name. Over a few dozen updates that is many gigabytes. This
# removes:
#
#   * images without a name (the ones each rebuild replaced);
#   * ifinmail/* images with a tag other than "latest" that no container uses (test builds);
#   * stopped containers of this stack that have been stopped for more than a day;
#   * build cache unused for DOCKER_CLEAN_CACHE_DAYS days (default 7), and anything above
#     DOCKER_CLEAN_CACHE_MAX (default 3GB), oldest first. When the disk is more than
#     DOCKER_CLEAN_DISK_PERCENT full (default 85) the whole build cache goes.
#
# Never removed: volumes (mail, database, keys, certificates), images a container uses, the
# "latest" images, and anything Docker holds for other projects on this server. A rollback
# rebuilds from git, so it needs none of what is removed.
set -uo pipefail

PROJECT="${COMPOSE_PROJECT_NAME:-docker}"
CACHE_DAYS="${DOCKER_CLEAN_CACHE_DAYS:-7}"
CACHE_MAX="${DOCKER_CLEAN_CACHE_MAX:-3GB}"
DISK_PERCENT="${DOCKER_CLEAN_DISK_PERCENT:-85}"
DEEP=0 DRY=0
for arg in "$@"; do
    case "$arg" in
        --deep) DEEP=1 ;;
        --dry-run) DRY=1 ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

command -v docker >/dev/null 2>&1 || { echo "docker is not installed"; exit 0; }
docker info >/dev/null 2>&1 || { echo "docker is not running"; exit 0; }

say() { echo "[$(date -u +%FT%TZ)] $*"; }
run() { if [ "$DRY" = 1 ]; then echo "  would run: $*"; else "$@"; fi; }

disk_used() { df -P /var/lib/docker 2>/dev/null | awk 'NR==2 {gsub("%", "", $5); print $5}'; }

before="$(disk_used)"
say "Docker clean-up starting (disk ${before:-?}% used)"

# Images each rebuild replaced: no name left.
run docker image prune -f >/dev/null

# Test builds of the stack's own images: any tag but "latest" that no container runs.
used="$(docker ps -a --format '{{.Image}}' | sort -u)"
used_ids="$(docker ps -aq | xargs -r docker inspect --format '{{.Image}}' 2>/dev/null | sort -u)"
while read -r ref id; do
    [ -n "$ref" ] || continue
    case "$ref" in *:latest) continue ;; esac
    if grep -qxF "$ref" <<<"$used" || grep -q "$id" <<<"$used_ids"; then
        continue
    fi
    say "Removing unused image $ref"
    run docker image rm "$ref" >/dev/null
done < <(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep '^ifinmail/' || true)

# Containers of this stack stopped for more than a day (compose recreates them when needed).
run docker container prune -f --filter "label=com.docker.compose.project=$PROJECT" \
    --filter until=24h >/dev/null

# Build cache: old layers, then a size cap; all of it when asked or when the disk is nearly full.
if [ "$DEEP" = 1 ] || [ "${before:-0}" -ge "$DISK_PERCENT" ]; then
    say "Emptying the build cache"
    run docker builder prune -af >/dev/null
else
    run docker builder prune -af --filter "until=$((CACHE_DAYS * 24))h" >/dev/null
    if docker builder prune --help 2>/dev/null | grep -q -- '--max-used-space'; then
        run docker builder prune -af --max-used-space "$CACHE_MAX" >/dev/null
    else
        run docker builder prune -af --keep-storage "$CACHE_MAX" >/dev/null
    fi
fi

say "Docker clean-up done (disk ${before:-?}% -> $(disk_used)% used)"
docker system df 2>/dev/null | sed 's/^/  /'
