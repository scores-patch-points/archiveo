#!/usr/bin/env bash
# tunnel.sh: make the VM's private gateway reachable at http://localhost:8850 on this Mac, for archiveo's Settings.
# Leave it running while you use "Back up to Wayback"; Ctrl-C closes it. Needs your SSH key loaded (ssh-add).
exec ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 ${SSH_OPTS:-} -L 127.0.0.1:8850:127.0.0.1:8850 "${HOST:-hyphae}"
