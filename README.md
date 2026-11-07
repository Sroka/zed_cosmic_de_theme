# zed_cosmic_de_theme

A [Zed](https://zed.dev) theme that follows the theme set in the **COSMIC desktop**,
including COSMIC's **Frosted glass** setting.

Zed themes are static JSON files, so this project ships a small generator
(`cosmic-zed-theme`, Python 3 standard library only). It reads COSMIC's
theme config and writes a `COSMIC` theme family into Zed's themes folder.
A systemd user path unit re-runs it whenever you change anything in
COSMIC Settings → Desktop → Appearance. Zed reloads the file and updates
right away.

## What it reads

COSMIC keeps the system defaults in `/usr/share/cosmic` and your changes in
`~/.config/cosmic`, one file per setting. The generator merges the two the
same way COSMIC does, so any theme works: the defaults, a customised one or
an imported `.ron` theme.

| COSMIC | Zed |
| --- | --- |
| `background` container | window, title bar, status bar, panels, tab bar |
| `primary` container | editor, active tab, terminal, toolbar |
| `secondary` container | popovers, menus, modals |
| `accent` | cursor, focus borders, active line number, selections, links |
| `success` / `warning` / `destructive` | diagnostics and git status colours |
| `palette` accents and neutrals | syntax highlighting and terminal ANSI colours |
| `is_frosted` (**Frosted glass**) | `background.appearance: "blurred"` with translucent surfaces |
| Mode `is_dark` (incl. auto-switch) | which palette the `COSMIC` theme uses |

## Themes it generates

- **COSMIC**: whatever COSMIC is showing right now. It switches between dark
  and light when COSMIC does, including COSMIC's automatic day/night switch.
- **COSMIC Dark** and **COSMIC Light**: fixed variants, for use with Zed's
  `"mode": "system"`.

## Install

```bash
git clone git@github.com:Sroka/zed_cosmic_de_theme.git
cd zed_cosmic_de_theme
./install.sh
```

Then in Zed press `ctrl-k ctrl-t` and choose **COSMIC**, or set it in `settings.json`:

```jsonc
"theme": { "mode": "system", "light": "COSMIC Light", "dark": "COSMIC Dark" }
```

The native Zed (`~/.config/zed`) and the Flathub Zed
(`~/.var/app/dev.zed.Zed/config/zed`) are both found automatically.

Uninstall with `./uninstall.sh`.

## Frosted glass

By default the Zed theme follows COSMIC's **Frosted glass** toggle. When it is
on, Zed's window background is blurred and editor, panels and bars become
translucent. You can override this in `~/.config/zed-cosmic-theme/config.json`
(see `config.example.json`):

```json
{
  "frosted": "auto",
  "opacity": 0.8
}
```

- `frosted`: `"auto"` follows COSMIC, `"on"` always uses frosted glass, `"off"` never does.
- `opacity`: how opaque surfaces are when frosted glass is on (0–1). Lower values show more of the blurred desktop.

Changes to this file are applied immediately too. The blur itself comes from
the compositor. If it doesn't support blur, the window is translucent but not blurred.

## Manual use

```bash
cosmic-zed-theme                 # generate once
cosmic-zed-theme --watch         # keep running without systemd
cosmic-zed-theme --frosted on --opacity 0.7
cosmic-zed-theme --stdout        # print the theme JSON
cosmic-zed-theme -o ~/somewhere  # write to a specific themes folder
```

## License

MIT
