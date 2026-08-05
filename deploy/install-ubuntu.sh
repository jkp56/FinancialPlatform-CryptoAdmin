#!/usr/bin/env bash
set -euo pipefail

app_root=/opt/apps/crypto-admin
source_root="${app_root}/app"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Voer dit script uit met: sudo bash deploy/install-ubuntu.sh" >&2
  exit 1
fi

if [[ ! -f "${source_root}/deploy/compose.yaml" ]]; then
  echo "Plaats of clone de repository eerst in ${source_root}." >&2
  exit 1
fi

install -d -m 0755 "${app_root}"
install -d -m 0750 "${app_root}/data"
chown 10001:10001 "${app_root}/data"

docker compose -f "${source_root}/deploy/compose.yaml" up -d --build
docker compose -f "${source_root}/deploy/compose.yaml" ps
