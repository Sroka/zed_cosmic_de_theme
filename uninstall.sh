#!/usr/bin/env bash
set -euo pipefail
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
systemctl --user disable --now cosmic-zed-theme.path 2>/dev/null || true
rm -f "$units/cosmic-zed-theme.path" "$units/cosmic-zed-theme.service" "$HOME/.local/bin/cosmic-zed-theme"
systemctl --user daemon-reload 2>/dev/null || true
for d in "${XDG_CONFIG_HOME:-$HOME/.config}/zed/themes" "$HOME/.var/app/dev.zed.Zed/config/zed/themes"; do
  rm -f "$d/cosmic.json"
done
echo "Removed cosmic-zed-theme."
