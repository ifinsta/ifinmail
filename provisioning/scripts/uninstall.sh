#!/usr/bin/env bash
# ifinmail uninstall.sh — undo what the installer did on this server.
#
#   uninstall.sh                 ask, then remove everything (mail and data included)
#   uninstall.sh --yes           same, without asking (automation)
#   uninstall.sh --keep-data     keep the Docker volumes (mail, database, DNSSEC keys, certificates)
#   uninstall.sh --keep-backups  keep /backups/ifinmail_backup_* archives
#   uninstall.sh --remove-docker also remove Docker and the tools the installer added
#   uninstall.sh --check         only list what is left of an install (exit 1 if anything)
#
# Removed: containers, volumes, network and images of the stack; the backup cron job; the sysctl
# file (and the original vm.overcommit_memory value is put back); files and packages the
# installer created or added (recorded in /var/lib/ifinmail/manifest); the backup GPG key; ifinmail
# logs; backups; the install directory. Docker itself stays unless --remove-docker: other things
# on the server may use it.
set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
REPO_DIR="$(cd "$(dirname "$SCRIPT_PATH")/../.." && pwd)"
ENV_FILE="$REPO_DIR/provisioning/.env"
PROJECT="${COMPOSE_PROJECT_NAME:-docker}"
STATE_DIR=/var/lib/ifinmail
MANIFEST="$STATE_DIR/manifest"
STACK_IMAGES_RE='^(ifinmail/|postgres:16-alpine|redis:7-alpine|nginx:1\.27-alpine|docker:27-cli|alpine:3\.20)'
PORTS='25 53 80 110 143 443 465 587 993 995'

YES=0 KEEP_DATA=0 KEEP_BACKUPS=0 REMOVE_DOCKER=0 CHECK_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) YES=1 ;;
        --keep-data) KEEP_DATA=1 ;;
        --keep-backups) KEEP_BACKUPS=1 ;;
        --remove-docker) REMOVE_DOCKER=1 ;;
        --check) CHECK_ONLY=1 ;;
        -h|--help) sed -n '2,17p' "$SCRIPT_PATH"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

say() { echo "==> $*"; }
have_docker() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }
env_value() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

leftovers() {
    local found=0
    if have_docker; then
        local c v i
        c="$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" | wc -l)"
        v="$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT" | wc -l)"
        i="$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -cE "$STACK_IMAGES_RE" || true)"
        [ "$c" -gt 0 ] && { echo "  containers: $c"; found=1; }
        [ "$v" -gt 0 ] && { echo "  volumes: $v"; found=1; }
        [ "$i" -gt 0 ] && { echo "  images: $i"; found=1; }
        docker network inspect ifinmail-net >/dev/null 2>&1 && { echo "  network: ifinmail-net"; found=1; }
    fi
    for path in /etc/cron.d/ifinmail-backup /etc/sysctl.d/99-ifinmail.conf "$STATE_DIR" \
                /var/log/ifinmail-backup.log /var/log/ifinmail-restore-test.log; do
        [ -e "$path" ] && { echo "  $path"; found=1; }
    done
    if [ -d /backups ] && ls /backups/ifinmail_backup_* >/dev/null 2>&1; then
        echo "  backups in /backups"; found=1
    fi
    [ -d "$REPO_DIR" ] && [ "$CHECK_ONLY" = 1 ] && { echo "  install directory $REPO_DIR"; found=1; }
    if command -v gpg >/dev/null 2>&1 && gpg --list-keys 2>/dev/null | grep -q 'ifinmail-backup@'; then
        echo "  backup GPG key"; found=1
    fi
    for port in $PORTS; do
        if ss -ltnu 2>/dev/null | awk '{print $5}' | grep -qE "[:.]$port\$"; then
            echo "  port $port still has a listener (may be unrelated to ifinmail)"
        fi
    done
    return $found
}

if [ "$CHECK_ONLY" = 1 ]; then
    echo "Remaining ifinmail pieces:"
    if leftovers; then echo "  none"; exit 0; fi
    exit 1
fi

[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo $0 $*" >&2; exit 1; }

# The install directory is removed at the end; run from a copy so bash keeps reading the script.
if [ -z "${IFINMAIL_UNINSTALL_COPY:-}" ]; then
    copy="$(mktemp /tmp/ifinmail-uninstall.XXXXXX)"
    cp "$SCRIPT_PATH" "$copy"
    IFINMAIL_UNINSTALL_COPY=1 IFINMAIL_REPO_DIR="$REPO_DIR" exec bash "$copy" "$@"
fi
REPO_DIR="${IFINMAIL_REPO_DIR:-$REPO_DIR}"
ENV_FILE="$REPO_DIR/provisioning/.env"

DOMAIN="$(env_value DOMAIN)"
if [ "$YES" != 1 ]; then
    echo "This removes ifinmail${DOMAIN:+ for $DOMAIN} from this server:"
    [ "$KEEP_DATA" = 1 ] && echo "  - containers and images (mail and data volumes are KEPT)" \
        || echo "  - containers, images and ALL MAIL AND DATA (mailboxes, database, DNSSEC keys, certificates)"
    [ "$KEEP_BACKUPS" = 1 ] || echo "  - backups in /backups"
    echo "  - cron job, system settings, backup key, logs and $REPO_DIR"
    [ "$REMOVE_DOCKER" = 1 ] && echo "  - Docker and the tools the installer added"
    read -rp "Type the word 'uninstall' to continue: " answer < /dev/tty
    [ "$answer" = uninstall ] || { echo "Nothing was changed."; exit 1; }
fi

if have_docker; then
    say "Stopping and removing the stack"
    ids="$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")"
    [ -n "$ids" ] && docker rm -f $ids >/dev/null
    docker network rm ifinmail-net >/dev/null 2>&1 || true
    if [ "$KEEP_DATA" != 1 ]; then
        vols="$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")"
        [ -n "$vols" ] && docker volume rm $vols >/dev/null
    fi
    imgs="$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "$STACK_IMAGES_RE" || true)"
    [ -n "$imgs" ] && docker rmi -f $imgs >/dev/null 2>&1
    docker image prune -f >/dev/null 2>&1 || true   # dangling layers left by the stack's builds
fi

say "Removing the backup schedule and system settings"
rm -f /etc/cron.d/ifinmail-backup /etc/sysctl.d/99-ifinmail.conf
original="$(sed -n 's/^sysctl vm.overcommit_memory=//p' "$MANIFEST" 2>/dev/null | head -1)"
sysctl -w "vm.overcommit_memory=${original:-0}" >/dev/null 2>&1 || true

if [ -f "$MANIFEST" ]; then
    while IFS= read -r line; do
        case "$line" in
            "created /etc/apt/apt.conf.d/"*) rm -f "${line#created }" ;;
            "installed unattended-upgrades") DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq unattended-upgrades >/dev/null 2>&1 || true ;;
        esac
    done < "$MANIFEST"
fi

say "Removing the backup key, logs and backups"
recipient="$(env_value BACKUP_GPG_RECIPIENT)"
if command -v gpg >/dev/null 2>&1; then
    for fpr in $(gpg --with-colons --fingerprint "${recipient:-ifinmail-backup@}" 2>/dev/null | awk -F: '/^fpr/ {print $10}' | sort -u); do
        gpg --batch --yes --delete-secret-and-public-key "$fpr" >/dev/null 2>&1 || true
    done
fi
rm -f /var/log/ifinmail-backup.log /var/log/ifinmail-restore-test.log
if [ "$KEEP_BACKUPS" != 1 ] && [ -d /backups ]; then
    rm -rf /backups/ifinmail_backup_* /backups/[0-9]*_[0-9]*
    rmdir /backups 2>/dev/null || true   # only when nothing else lives there
fi

if [ "$REMOVE_DOCKER" = 1 ] && [ -f "$MANIFEST" ]; then
    say "Removing Docker and the tools the installer added"
    pkgs=""
    grep -qx 'installed docker' "$MANIFEST" && pkgs="docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"
    for pkg in $(sed -n 's/^installed \(make\|dnsutils\|git\|gpg\|openssl\|curl\)$/\1/p' "$MANIFEST"); do
        pkgs="$pkgs $pkg"
    done
    if [ -n "$pkgs" ]; then
        DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq $pkgs >/dev/null 2>&1 || true
        DEBIAN_FRONTEND=noninteractive apt-get autoremove -y -qq >/dev/null 2>&1 || true
    fi
    grep -qx 'installed docker' "$MANIFEST" && rm -rf /var/lib/docker /var/lib/containerd \
        /etc/apt/sources.list.d/docker.list /etc/apt/keyrings/docker.asc
fi

say "Removing $REPO_DIR"
rm -rf "$STATE_DIR"
case "$REPO_DIR" in
    /|/root|/home|/home/*/..|"") echo "Refusing to remove $REPO_DIR" >&2 ;;
    *) rm -rf "$REPO_DIR" ;;
esac
rm -f "$0"

echo
echo "ifinmail is uninstalled. Anything still present:"
if leftovers; then echo "  nothing"; fi
echo
echo "Outside this server, undo by hand if you no longer want them: the nameserver/glue and DS"
echo "records at your registrar, and the reverse DNS (PTR) at your VPS provider."
