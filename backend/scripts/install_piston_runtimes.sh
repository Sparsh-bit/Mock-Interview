#!/usr/bin/env bash
# Installs the coding-round language runtimes into the self-hosted Piston
# container (see docker-compose.yml). Idempotent: re-installing an existing
# package is a no-op. Run once after `docker compose up -d piston`.
set -euo pipefail
PISTON_URL="${PISTON_URL:-http://localhost:2000}"

install() {
  local lang="$1" version="$2"
  echo "Installing ${lang} ${version}…"
  curl -s -X POST "${PISTON_URL}/api/v2/packages" \
    -H 'Content-Type: application/json' \
    -d "{\"language\":\"${lang}\",\"version\":\"${version}\"}"
  echo ""
}

install java 15.0.2      # Java
install python 3.10.0    # Python
install gcc 10.2.0       # C / C++
install sqlite3 3.36.0   # SQL

echo "Done. Installed runtimes:"
curl -s "${PISTON_URL}/api/v2/runtimes"
