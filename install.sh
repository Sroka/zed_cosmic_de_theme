#!/usr/bin/env bash
# Install cosmic-zed-theme and keep Zed in sync with the COSMIC desktop theme.
set -euo pipefail
cd "$(dirname "$0")"

bin="$HOME/.local/bin"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$bin" "$units" \
  "$HOME/.config/cosmic/com.system76.CosmicTheme.Mode/v1" \
  "$HOME/.config/cosmic/com.system76.CosmicTheme.Dark/v1" \
  "$HOME/.config/cosmic/com.system76.CosmicTheme.Light/v1"

install -m 755 cosmic_zed_theme.py "$bin/cosmic-zed-theme"
install -m 644 systemd/cosmic-zed-theme.service systemd/cosmic-zed-theme.path "$units/"

"$bin/cosmic-zed-theme"

if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user daemon-reload
  systemctl --user enable --now cosmic-zed-theme.path
  echo "Watching COSMIC theme changes (systemctl --user status cosmic-zed-theme.path)."
else
  echo "systemd --user not available; run 'cosmic-zed-theme --watch' from your session autostart instead."
fi

cat <<'MSG'

Done. In Zed, open the theme selector (ctrl-k ctrl-t) and pick "COSMIC",
or add this to your Zed settings.json:

  "theme": { "mode": "system", "light": "COSMIC Light", "dark": "COSMIC Dark" }
MSG
