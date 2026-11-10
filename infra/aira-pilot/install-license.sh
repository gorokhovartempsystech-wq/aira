#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

[[ "$(id -u)" == 0 ]]
. /etc/os-release
[[ "$ID:$VERSION_ID" == ubuntu:24.04 ]]
cd -- "$(dirname -- "$0")"
sha256sum --check backend.tar.gz.sha256

apt-get update
apt-get install -y --no-install-recommends ca-certificates curl postgresql-common python3.12-venv
install -d -m 0755 /usr/share/postgresql-common/pgdg
curl --fail --silent --show-error --location \
  -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc
cat > /etc/apt/sources.list.d/aira-pgdg.sources <<'EOF'
Types: deb
URIs: https://apt.postgresql.org/pub/repos/apt
Suites: noble-pgdg
Components: main
Signed-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
EOF
apt-get update
apt-get install -y --no-install-recommends postgresql-18
systemctl enable --now postgresql
pg=(runuser -u postgres -- psql -X -h /var/run/postgresql -v ON_ERROR_STOP=1)
[[ "$("${pg[@]}" -Atc 'SHOW server_version_num')" =~ ^18[0-9]{4}$ ]]
[[ "$("${pg[@]}" -Atc 'SHOW listen_addresses')" =~ ^(localhost|127\.0\.0\.1)?$ ]]
if ! getent passwd aira-license >/dev/null; then
  adduser --system --group --home /var/lib/aira-license aira-license
fi
[[ "$(getent passwd aira-license | cut -d: -f6)" == /var/lib/aira-license ]]
install -d -m 0700 -o aira-license -g aira-license /var/lib/aira-license
"${pg[@]}" <<'SQL'
SELECT 'CREATE ROLE "aira-license" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aira-license')
\gexec
SELECT 'CREATE DATABASE aira_licenses OWNER "aira-license"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'aira_licenses')
\gexec
SQL
[[ "$(runuser -u aira-license -- psql -X -h /var/run/postgresql -d aira_licenses -Atc 'SELECT current_user')" == aira-license ]]

install -d -m 0755 /opt/aira-license/backend
tar -xzf backend.tar.gz --no-same-owner -C /opt/aira-license/backend
python3.12 -m venv /opt/aira-license/venv
/opt/aira-license/venv/bin/pip --disable-pip-version-check install --requirement /opt/aira-license/backend/requirements.lock
/opt/aira-license/venv/bin/pip --disable-pip-version-check install --no-deps /opt/aira-license/backend
runuser -u aira-license -- /opt/aira-license/venv/bin/python - <<'PY'
import os
import secrets
from pathlib import Path

os.umask(0o077)
path = Path.home() / "secrets.env"
if path.is_symlink():
    raise SystemExit("Refusing a symlink for the license settings.")
try:
    handle = path.open("x", encoding="ascii")
except FileExistsError:
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise SystemExit("Unexpected permissions on the license settings.")
else:
    with handle:
        handle.write(
            "AIRA_LICENSE_DATABASE_URL=postgresql+psycopg://aira-license@/aira_licenses"
            "?host=/var/run/postgresql\n"
        )
        handle.write("AIRA_LICENSE_PEPPER=" + secrets.token_hex(32) + "\n")
PY
runuser -u aira-license -- /opt/aira-license/venv/bin/python -m ara.licensing.server init

cat > /etc/systemd/system/aira-license.service <<'UNIT'
[Unit]
Description=AIRA License Server
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User=aira-license
Group=aira-license
WorkingDirectory=/opt/aira-license/backend
ExecStart=/opt/aira-license/venv/bin/python -m ara.licensing.server serve --port 8766
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now aira-license
status="$(curl --silent --retry 5 --retry-connrefused --retry-delay 1 --output /dev/null \
  --write-out '%{http_code}' --header 'Content-Type: application/json' \
  --header 'X-Forwarded-Proto: https' --data '{}' http://127.0.0.1:8766/license/v1/check)"
[[ "$status" == 422 ]]
systemctl is-active aira-license
