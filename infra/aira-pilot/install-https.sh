#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
[[ "$(id -u)" == 0 ]]
config="$(realpath -- "${1:?pass the staged Caddyfile}")"
install -d -m 0755 /srv/aira-public/downloads /srv/aira-public/updates
systemctl is-active --quiet aira-license
apt-get install -y --no-install-recommends debian-keyring debian-archive-keyring apt-transport-https gpg
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key |
  gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -fsSL -o /etc/apt/sources.list.d/caddy-stable.list \
  https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt
chmod 0644 /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
apt-get update
candidate="$(apt-cache policy caddy | awk '/Candidate:/ {print $2}')"
dpkg --compare-versions "$candidate" ge 2.11.4
apt-get install -y --no-install-recommends "caddy=$candidate"
install -m 0644 "$config" /etc/caddy/aira-candidate.caddyfile
runuser -u caddy -- caddy validate --config /etc/caddy/aira-candidate.caddyfile --adapter caddyfile
cp -n /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-aira
mv /etc/caddy/aira-candidate.caddyfile /etc/caddy/Caddyfile
if command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active$'; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi
systemctl enable --now caddy
systemctl reload caddy
systemctl is-active caddy aira-license
caddy version
