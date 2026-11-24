#!/usr/bin/env bash
# deploy.sh: copy the archiveo gateway to the VM and (re)start it. Follows holodeck/tools/contracts-api/deploy.sh.
# No nginx change: temporary pages are written into /srv/samples/_archiveo, which the existing route
# https://watch.hyphae.social/samples/ already publishes; the API listens on the VM's loopback only (reach it with tunnel.sh).
# The key is generated here into gateway/.key (gitignored) and copied as a 0600 file; it is never printed.
#   ./gateway/deploy.sh                        deploy / redeploy
#   ./gateway/deploy.sh --check                is it running, and what is in the pages folder?
#   SSH_OPTS="-i ~/.ssh/<key>" ./gateway/deploy.sh      (default: whatever `ssh hyphae` resolves to)
set -euo pipefail
HOST=${HOST:-hyphae}; DEST=${DEST:-/mnt/watch/archiveo-gateway}
FILES_DIR=${FILES_DIR:-/srv/samples/_archiveo}; FILES_URL=${FILES_URL:-https://watch.hyphae.social/samples/_archiveo}
SSH_OPTS=${SSH_OPTS:-}
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC2086
ssh_() { ssh -o BatchMode=yes -o ConnectTimeout=15 $SSH_OPTS "$HOST" "$@"; }
# shellcheck disable=SC2086
scp_() { scp -o BatchMode=yes -q $SSH_OPTS "$@"; }

if [ "${1:-}" = "--check" ]; then
  ssh_ "systemctl is-active archiveo-gateway; curl -sS -m 5 http://127.0.0.1:8850/health; echo; echo \"pages folder (should be empty between backups):\"; ls -la $FILES_DIR | tail -n +4; journalctl -u archiveo-gateway -n 5 --no-pager | cut -c1-170" || true
  exit 0
fi

[ -s "$here/.key" ] || { umask 077; openssl rand -hex 24 > "$here/.key"; echo "generated gateway/.key (not printed)"; }
chmod 600 "$here/.key"
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
printf 'GATEWAY_PORT=8850\nGATEWAY_FILES_DIR=%s\nGATEWAY_FILES_URL=%s\nGATEWAY_KEY_FILE=%s/key\n' "$FILES_DIR" "$FILES_URL" "$DEST" > "$tmp"

ssh_ "mkdir -p $DEST $FILES_DIR"
scp_ "$here/server.py" "$HOST:$DEST/"
scp_ "$here/.key" "$HOST:$DEST/key"
scp_ "$tmp" "$HOST:$DEST/gateway.env"
scp_ "$here/archiveo-gateway.service" "$HOST:$DEST/"
ssh_ "chmod 600 $DEST/key $DEST/gateway.env && sudo install -m 644 $DEST/archiveo-gateway.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now archiveo-gateway && sudo systemctl restart archiveo-gateway && sleep 1 && systemctl is-active archiveo-gateway"
echo "running on the VM at 127.0.0.1:8850 (loopback only). Reach it from your Mac with:  ./gateway/tunnel.sh"
