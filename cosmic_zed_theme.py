#!/usr/bin/env python3
"""Generate a Zed editor theme from the COSMIC desktop's active theme.

Reads the COSMIC theme exactly the way COSMIC does: every key is looked up
first in the user's config (~/.config/cosmic/...) and falls back to the system
defaults (/usr/share/cosmic/...). The result is written as a Zed theme family
("COSMIC") into every Zed themes directory found (native and flatpak). Zed
reloads theme files when they change, so re-running this script (or keeping
it running with --watch / the systemd path unit) makes Zed follow COSMIC.

COSMIC's "Frosted glass" setting (level + windows switch) is mapped to Zed's blurred
window background with translucent surfaces.

Only the Python 3 standard library is required.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

VERSION = "1.1.0"
SCHEMA = "https://zed.dev/schema/themes/v0.2.0.json"
THEME_FILE = "cosmic.json"
DARK_ID = "com.system76.CosmicTheme.Dark"
LIGHT_ID = "com.system76.CosmicTheme.Light"
MODE_ID = "com.system76.CosmicTheme.Mode"


# --------------------------------------------------------------------------
# Minimal RON (Rusty Object Notation) parser — enough for cosmic-config files
# --------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+|//[^\n]*|/\*.*?\*/)
  | (?P<str>"(?:\\.|[^"\\])*")
  | (?P<num>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>[()\[\]{}:,])
    """,
    re.VERBOSE | re.DOTALL,
)


class RonError(ValueError):
    pass


def _tokenize(text: str):
    pos = 0
    out = []
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise RonError(f"unexpected character {text[pos]!r} at {pos}")
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group()))
    return out


class _Parser:
    def __init__(self, text: str):
        self.toks = _tokenize(text)
        self.i = 0

    def peek(self, off: int = 0):
        j = self.i + off
        return self.toks[j] if j < len(self.toks) else (None, None)

    def take(self, value: str | None = None):
        tok = self.peek()
        if value is not None and tok[1] != value:
            raise RonError(f"expected {value!r}, got {tok[1]!r}")
        self.i += 1
        return tok

    def value(self):
        kind, val = self.peek()
        if kind == "str":
            self.take()
            return json.loads(val)
        if kind == "num":
            self.take()
            return float(val) if any(c in val for c in ".eE") else int(val)
        if kind == "ident":
            self.take()
            if val == "true":
                return True
            if val == "false":
                return False
            if val == "None":
                return None
            if val == "Some":
                self.take("(")
                inner = self.value()
                self.take(")")
                return inner
            # Named struct `Name(...)` or bare enum variant `Name`
            if self.peek()[1] == "(":
                return self.struct()
            return val
        if val == "(":
            return self.struct()
        if val == "[":
            return self.seq("[", "]")
        if val == "{":
            return self.map()
        raise RonError(f"unexpected token {val!r}")

    def struct(self):
        self.take("(")
        if self.peek()[0] == "ident" and self.peek(1)[1] == ":":
            out = {}
            while self.peek()[1] != ")":
                key = self.take()[1]
                self.take(":")
                out[key] = self.value()
                if self.peek()[1] == ",":
                    self.take()
            self.take(")")
            return out
        self.i -= 1
        return tuple(self.seq("(", ")"))

    def seq(self, open_: str, close: str):
        self.take(open_)
        out = []
        while self.peek()[1] != close:
            out.append(self.value())
            if self.peek()[1] == ",":
                self.take()
        self.take(close)
        return out

    def map(self):
        self.take("{")
        out = {}
        while self.peek()[1] != "}":
            k = self.value()
            self.take(":")
            out[k] = self.value()
            if self.peek()[1] == ",":
                self.take()
        self.take("}")
        return out


def parse_ron(text: str):
    p = _Parser(text)
    v = p.value()
    if p.i != len(p.toks):
        raise RonError("trailing data")
    return v


# --------------------------------------------------------------------------
# cosmic-config lookup (user config overrides system defaults, per key)
# --------------------------------------------------------------------------

def _config_roots() -> list[Path]:
    home = Path.home()
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    roots = [xdg_config / "cosmic"]
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for d in data_dirs.split(":"):
        if d:
            roots.append(Path(d) / "cosmic")
    # Make sure the canonical system location is always considered.
    for d in ("/usr/share/cosmic",):
        if Path(d) not in roots:
            roots.append(Path(d))
    return roots


def config_version(config_id: str) -> str:
    """Newest config schema version present for this id (COSMIC reads only
    its own version, e.g. v2 since libcosmic switched to hex colours)."""
    best = 0
    for root in _config_roots():
        try:
            for d in (root / config_id).iterdir():
                m = re.fullmatch(r"v(\d+)", d.name)
                if m and d.is_dir() and any(d.iterdir()):
                    best = max(best, int(m.group(1)))
        except OSError:
            pass
    return f"v{best or 1}"


def watched_dirs() -> list[Path]:
    dirs = []
    for root in _config_roots():
        for cid in (DARK_ID, LIGHT_ID, MODE_ID):
            dirs.append(root / cid)
            dirs.append(root / cid / config_version(cid))
    return dirs


def read_key(config_id: str, key: str, default=None):
    version = config_version(config_id)
    for root in _config_roots():
        f = root / config_id / version / key
        try:
            text = f.read_text()
        except OSError:
            continue
        try:
            return normalize(parse_ron(text))
        except RonError as e:
            print(f"warning: cannot parse {f}: {e}", file=sys.stderr)
    return default


THEME_KEYS = (
    "name", "is_dark", "is_high_contrast", "palette",
    "background", "primary", "secondary", "accent", "success", "warning",
    "destructive", "button", "accent_button", "text_button",
    # Frosted glass: v1 used a single flag, v2 a level + per-surface switches.
    "is_frosted", "frosted", "frosted_windows", "alpha_map",
)


def load_cosmic_theme(config_id: str) -> dict | None:
    theme = {k: read_key(config_id, k) for k in THEME_KEYS}
    required = ("palette", "background", "primary", "secondary", "accent")
    if any(theme[k] is None for k in required):
        return None
    theme["_version"] = config_version(config_id)
    return theme


# --------------------------------------------------------------------------
# Colours
# --------------------------------------------------------------------------

_HEX = re.compile(r"#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})")


def normalize(v):
    """Turn every COSMIC colour into an (r, g, b, a) tuple of floats.

    v1 configs store colours as structs (red: 0.5, green: ...), v2 configs
    as "#RRGGBBAA" strings.
    """
    if isinstance(v, str) and _HEX.fullmatch(v):
        h = v[1:] + ("ff" if len(v) == 7 else "")
        return tuple(int(h[i:i + 2], 16) / 255 for i in range(0, 8, 2))
    if isinstance(v, dict):
        if {"red", "green", "blue"} <= v.keys():
            return (v["red"], v["green"], v["blue"], v.get("alpha", 1.0))
        return {k: normalize(x) for k, x in v.items()}
    return v


def rgba(c, alpha: float | None = None) -> tuple[float, float, float, float]:
    if isinstance(c, dict):
        c = normalize(c)
    r, g, b, a = c
    return (r, g, b, a if alpha is None else alpha)


def hexc(c, alpha: float | None = None) -> str:
    r, g, b, a = rgba(c)
    if alpha is not None:
        a = alpha
    ch = [max(0, min(255, round(max(0.0, min(1.0, v)) * 255))) for v in (r, g, b, a)]
    return "#{:02x}{:02x}{:02x}{:02x}".format(*ch)


def mix(a, b, t: float):
    """Linear blend from colour a to colour b (t = 0 → a, t = 1 → b)."""
    return tuple(x + (y - x) * t for x, y in zip(rgba(a), rgba(b)))


# --------------------------------------------------------------------------
# COSMIC → Zed mapping
# --------------------------------------------------------------------------

def build_style(t: dict, opacity: float | None) -> dict:
    """opacity: surface opacity for frosted glass, or None for opaque."""
    frosted = opacity is not None
    p = t["palette"]
    bg, pri, sec = t["background"], t["primary"], t["secondary"]
    acc = t["accent"]
    ok = t.get("success") or {"base": p["bright_green"]}
    warn = t.get("warning") or {"base": p["bright_orange"]}
    err = t.get("destructive") or {"base": p["bright_red"]}
    dark = bool(t.get("is_dark", True))
    pc = pri["component"]

    # Frosted mode: Zed paints the window `background` first and draws the
    # editor, panels, bars and tabs on top of it. Translucent layers stack
    # (two at 81% look 96% opaque), so only the window background carries
    # COSMIC's opacity. Docked surfaces are fully transparent ("base"), and
    # primary-coloured areas get a light tint ("tint") that keeps COSMIC's
    # container contrast without adding much opacity. Popovers and menus
    # stay nearly opaque so text under them doesn't show through.
    surf_a = opacity if frosted else 1.0
    TINT = 0.3

    def window_bg(c):
        return hexc(c, rgba(c)[3] * surf_a)

    def base(c):
        return "#00000000" if frosted else hexc(c)

    def tint(c):
        return hexc(c, TINT) if frosted else hexc(c)

    def popover(c):
        return hexc(c, max(0.95, surf_a)) if frosted else hexc(c)

    text = pri["on"]
    ui_text = bg["on"]
    muted = mix(ui_text, bg["base"], 0.35)
    placeholder = mix(ui_text, bg["base"], 0.5)
    disabled = mix(ui_text, bg["base"], 0.6)
    info = p["accent_blue"]
    hint = p["accent_indigo"]

    def status(c, bg_alpha=0.15):
        base = c["base"] if isinstance(c, dict) and "base" in c else c
        return {
            "": hexc(base),
            ".background": hexc(base, 0.15 if bg_alpha is None else bg_alpha),
            ".border": hexc(base, 0.5),
        }

    style: dict = {
        "background.appearance": "blurred" if frosted else "opaque",
        "accents": [hexc(acc["base"])] + [hexc(p[k]) for k in (
            "accent_blue", "accent_purple", "accent_orange", "accent_green",
            "accent_pink", "accent_yellow", "accent_indigo")],

        "border": hexc(bg["divider"]),
        "border.variant": hexc(pri["divider"]),
        "border.focused": hexc(acc["focus"]),
        "border.selected": hexc(acc["base"]),
        "border.transparent": "#00000000",
        "border.disabled": hexc(pc["disabled_border"]),

        "elevated_surface.background": popover(sec["base"]),
        "surface.background": popover(pri["base"]),
        "background": window_bg(bg["base"]),

        "element.background": hexc(pc["base"]),
        "element.hover": hexc(pc["hover"]),
        "element.active": hexc(pc["pressed"]),
        "element.selected": hexc(pc["selected"]),
        "element.disabled": hexc(pc["disabled"]),
        "drop_target.background": hexc(acc["base"], 0.2),

        "ghost_element.background": "#00000000",
        "ghost_element.hover": hexc(pc["hover"], 0.7),
        "ghost_element.active": hexc(pc["pressed"], 0.8),
        "ghost_element.selected": hexc(pc["selected"]),
        "ghost_element.disabled": "#00000000",

        "text": hexc(ui_text),
        "text.muted": hexc(muted),
        "text.placeholder": hexc(placeholder),
        "text.disabled": hexc(disabled),
        "text.accent": hexc(acc["base"]),
        "link_text.hover": hexc(acc["hover"]),

        "icon": hexc(ui_text),
        "icon.muted": hexc(muted),
        "icon.disabled": hexc(disabled),
        "icon.placeholder": hexc(placeholder),
        "icon.accent": hexc(acc["base"]),

        "status_bar.background": base(bg["base"]),
        "title_bar.background": base(bg["base"]),
        "title_bar.inactive_background": base(bg["base"]),
        "toolbar.background": base(pri["base"]),
        "tab_bar.background": base(bg["base"]),
        "tab.inactive_background": base(bg["base"]),
        "tab.active_background": tint(pri["base"]),
        "search.match_background": hexc(acc["base"], 0.3),
        "panel.background": base(bg["base"]),
        "panel.focused_border": hexc(acc["focus"]),
        "panel.indent_guide": hexc(bg["divider"]),
        "panel.indent_guide_active": hexc(mix(bg["divider"], ui_text, 0.4)),
        "panel.indent_guide_hover": hexc(acc["base"], 0.6),
        "pane.focused_border": hexc(acc["focus"], 0.6),
        "pane_group.border": hexc(bg["divider"]),

        "scrollbar.thumb.background": hexc(ui_text, 0.2),
        "scrollbar.thumb.hover_background": hexc(ui_text, 0.35),
        "scrollbar.thumb.border": "#00000000",
        "scrollbar.track.background": "#00000000",
        "scrollbar.track.border": "#00000000",

        "editor.foreground": hexc(text),
        "editor.background": tint(pri["base"]),
        "editor.gutter.background": tint(pri["base"]),
        "editor.subheader.background": base(bg["base"]),
        "editor.active_line.background": hexc(pc["hover"], 0.35),
        "editor.highlighted_line.background": hexc(pc["hover"], 0.5),
        "editor.line_number": hexc(mix(text, pri["base"], 0.55)),
        "editor.active_line_number": hexc(acc["base"]),
        "editor.invisible": hexc(mix(text, pri["base"], 0.7)),
        "editor.wrap_guide": hexc(pri["divider"]),
        "editor.active_wrap_guide": hexc(mix(pri["divider"], text, 0.3)),
        "editor.indent_guide": hexc(pri["divider"]),
        "editor.indent_guide_active": hexc(mix(pri["divider"], text, 0.35)),
        "editor.document_highlight.read_background": hexc(acc["base"], 0.12),
        "editor.document_highlight.write_background": hexc(acc["base"], 0.22),
        "editor.document_highlight.bracket_background": hexc(acc["base"], 0.18),

        "terminal.background": tint(pri["base"]),
        "terminal.foreground": hexc(text),
        "terminal.bright_foreground": hexc(p["neutral_10"] if dark else p["neutral_0"]),
        "terminal.dim_foreground": hexc(muted),
        "terminal.ansi.background": tint(pri["base"]),
    }

    ansi = {
        "black": p["neutral_1"] if dark else p["neutral_9"],
        "red": p["accent_red"],
        "green": p["accent_green"],
        "yellow": p["accent_yellow"],
        "blue": p["accent_blue"],
        "magenta": p["accent_purple"],
        "cyan": p["ext_blue"],
        "white": p["neutral_8"] if dark else p["neutral_2"],
    }
    bright = {
        "black": p["neutral_4"] if dark else p["neutral_6"],
        "red": p["bright_red"],
        "green": p["bright_green"],
        "yellow": p["ext_yellow"],
        "blue": p["ext_indigo"],
        "magenta": p["ext_purple"],
        "cyan": p["accent_indigo"],
        "white": p["neutral_10"] if dark else p["neutral_0"],
    }
    for name, c in ansi.items():
        style[f"terminal.ansi.{name}"] = hexc(c)
        style[f"terminal.ansi.dim_{name}"] = hexc(mix(c, pri["base"], 0.35))
        style[f"terminal.ansi.bright_{name}"] = hexc(bright[name])

    for key, c in {
        "error": err, "warning": warn, "success": ok,
        "info": {"base": info}, "hint": {"base": hint},
        "created": ok, "modified": {"base": p["accent_yellow"]}, "deleted": err,
        "renamed": {"base": info}, "conflict": warn,
        "hidden": {"base": disabled}, "ignored": {"base": disabled},
        "predictive": {"base": placeholder}, "unreachable": {"base": muted},
    }.items():
        for suffix, v in status(c).items():
            style[key + suffix] = v

    player_keys = ["accent_blue", "accent_purple", "accent_orange", "accent_pink",
                   "accent_yellow", "accent_indigo", "accent_red"]
    players = [{"cursor": hexc(acc["base"]), "background": hexc(acc["base"]),
                "selection": hexc(acc["base"], 0.25)}]
    for k in player_keys:
        players.append({"cursor": hexc(p[k]), "background": hexc(p[k]),
                        "selection": hexc(p[k], 0.25)})
    style["players"] = players

    def s(c, **extra):
        d = {"color": hexc(c)}
        d.update(extra)
        return d

    comment = mix(text, pri["base"], 0.45)
    punct = mix(text, pri["base"], 0.2)
    style["syntax"] = {
        "attribute": s(p["accent_warm_grey"]),
        "boolean": s(p["accent_orange"]),
        "comment": s(comment, font_style="italic"),
        "comment.doc": s(mix(comment, p["accent_green"], 0.3), font_style="italic"),
        "constant": s(p["accent_orange"]),
        "constructor": s(p["accent_yellow"]),
        "embedded": s(text),
        "emphasis": s(acc["base"], font_style="italic"),
        "emphasis.strong": s(acc["base"], font_weight=700),
        "enum": s(p["accent_yellow"]),
        "function": s(p["accent_blue"]),
        "function.method": s(p["accent_blue"]),
        "function.builtin": s(p["ext_blue"]),
        "hint": s(hint, font_style="italic"),
        "keyword": s(p["accent_purple"]),
        "label": s(p["accent_indigo"]),
        "link_text": s(acc["base"], font_style="italic"),
        "link_uri": s(p["accent_blue"]),
        "namespace": s(p["accent_warm_grey"]),
        "number": s(p["accent_orange"]),
        "operator": s(punct),
        "predictive": s(placeholder, font_style="italic"),
        "preproc": s(p["accent_pink"]),
        "primary": s(text),
        "property": s(p["accent_indigo"]),
        "punctuation": s(punct),
        "punctuation.bracket": s(punct),
        "punctuation.delimiter": s(punct),
        "punctuation.list_marker": s(acc["base"]),
        "punctuation.special": s(p["accent_pink"]),
        "selector": s(p["accent_yellow"]),
        "selector.pseudo": s(p["accent_purple"]),
        "string": s(p["accent_green"]),
        "string.escape": s(p["accent_pink"]),
        "string.regex": s(p["accent_pink"]),
        "string.special": s(p["accent_pink"]),
        "string.special.symbol": s(p["accent_orange"]),
        "tag": s(p["accent_red"]),
        "text.literal": s(p["accent_green"]),
        "title": s(acc["base"], font_weight=700),
        "type": s(p["accent_yellow"]),
        "type.builtin": s(p["accent_yellow"]),
        "variable": s(text),
        "variable.special": s(p["accent_red"]),
        "variant": s(p["accent_yellow"]),
    }
    return style


# --------------------------------------------------------------------------
# Settings, output and the main loop
# --------------------------------------------------------------------------

def settings_path() -> Path:
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return xdg / "zed-cosmic-theme" / "config.json"


def load_settings() -> dict:
    defaults = {"frosted": "auto", "opacity": "auto", "output": []}
    try:
        user = json.loads(settings_path().read_text())
        defaults.update({k: v for k, v in user.items() if k in defaults})
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print(f"warning: ignoring {settings_path()}: {e}", file=sys.stderr)
    return defaults


def zed_theme_dirs() -> list[Path]:
    home = Path.home()
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    candidates = [
        xdg / "zed",                                    # native install
        home / ".var/app/dev.zed.Zed/config/zed",       # flatpak
        home / ".var/app/dev.zed.Zed.Preview/config/zed",
    ]
    found = [c / "themes" for c in candidates if c.is_dir()]
    return found or [candidates[0] / "themes"]


DEFAULT_OPACITY = 0.76  # COSMIC's "Medium" frosted level


def _snake(name: str) -> str:
    """COSMIC level names (Medium, Low2, ExtremelyHigh2) → alpha_map keys."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name)
    s = re.sub(r"(?<=[A-Za-z])(?=\d)", "_", s)
    return s.lower()


def cosmic_frosted(theme: dict) -> float | None:
    """Opacity COSMIC uses for frosted windows, or None when it is off."""
    if theme.get("_version", "v1") != "v1" and theme.get("frosted_windows") is not None:
        if not theme.get("frosted_windows"):
            return None
        level = theme.get("frosted")
        alpha_map = theme.get("alpha_map") or {}
        if isinstance(level, str):
            if level.lower() in ("none", "off", "disabled"):
                return None
            if _snake(level) in alpha_map:
                return float(alpha_map[_snake(level)])
        if isinstance(level, (int, float)):
            return float(level)
        return DEFAULT_OPACITY
    return DEFAULT_OPACITY if theme.get("is_frosted") else None


def resolve_frosted(mode: str, opacity, theme: dict) -> float | None:
    """Final surface opacity for Zed, or None for an opaque theme."""
    from_cosmic = cosmic_frosted(theme)
    if mode in ("off", "false", False):
        return None
    if mode not in ("on", "true", True) and from_cosmic is None:
        return None
    if isinstance(opacity, (int, float)):
        return max(0.0, min(1.0, float(opacity)))
    return from_cosmic if from_cosmic is not None else DEFAULT_OPACITY


def generate(frosted_mode: str, opacity) -> dict:
    dark = load_cosmic_theme(DARK_ID)
    light = load_cosmic_theme(LIGHT_ID)
    if not dark and not light:
        raise SystemExit("error: no COSMIC theme found (is COSMIC installed?)")
    is_dark = read_key(MODE_ID, "is_dark", True)

    themes = []

    def add(name, t):
        themes.append({
            "name": name,
            "appearance": "dark" if t.get("is_dark", True) else "light",
            "style": build_style(t, resolve_frosted(frosted_mode, opacity, t)),
        })

    active = (dark if is_dark else light) or dark or light
    add("COSMIC", active)
    if dark:
        add("COSMIC Dark", dark)
    if light:
        add("COSMIC Light", light)

    return {
        "$schema": SCHEMA,
        "name": "COSMIC",
        "author": "Generated from the COSMIC desktop theme by zed_cosmic_de_theme",
        "themes": themes,
    }


def write_theme(doc: dict, outputs: list[Path]) -> list[Path]:
    data = json.dumps(doc, indent=2) + "\n"
    written = []
    for d in outputs:
        d.mkdir(parents=True, exist_ok=True)
        target = d / THEME_FILE
        try:
            if target.read_text() == data:
                continue  # unchanged; don't make Zed reload for nothing
        except OSError:
            pass
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(data)
        os.replace(tmp, target)  # atomic, so Zed never reads a half file
        written.append(target)
    return written


def snapshot() -> dict:
    state = {}
    for d in watched_dirs():
        try:
            for f in d.iterdir():
                state[str(f)] = f.stat().st_mtime_ns
        except OSError:
            pass
    s = settings_path()
    if s.exists():
        state[str(s)] = s.stat().st_mtime_ns
    return state


def run_once(args) -> None:
    cfg = load_settings()
    frosted = args.frosted or cfg["frosted"]
    opacity = args.opacity if args.opacity is not None else cfg["opacity"]
    if not isinstance(opacity, (int, float)):
        try:
            opacity = float(opacity)
        except (TypeError, ValueError):
            opacity = "auto"  # use COSMIC's frosted level
    outs = [Path(o).expanduser() for o in (args.output or cfg["output"])] or zed_theme_dirs()
    if args.stdout:
        print(json.dumps(generate(frosted, opacity), indent=2))
        return
    written = write_theme(generate(frosted, opacity), outs)
    if not args.quiet:
        for w in written:
            print(f"wrote {w}")
        if not written:
            print("theme unchanged")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frosted", choices=["auto", "on", "off"],
                    help="frosted glass: follow COSMIC (auto, default), or force on/off")
    ap.add_argument("--opacity", type=float,
                    help="surface opacity when frosted glass is on (0-1; default: COSMIC's frosted level)")
    ap.add_argument("-o", "--output", action="append",
                    help="Zed themes directory to write to (repeatable; default: auto-detect)")
    ap.add_argument("--stdout", action="store_true", help="print the theme instead of writing it")
    ap.add_argument("--watch", action="store_true",
                    help="keep running and regenerate whenever the COSMIC theme changes")
    ap.add_argument("--interval", type=float, default=1.0, help="poll interval for --watch (seconds)")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args(argv)

    run_once(args)
    if not args.watch:
        return 0
    last = snapshot()
    while True:
        time.sleep(args.interval)
        now = snapshot()
        if now != last:
            time.sleep(0.2)  # let COSMIC finish writing all keys
            last = snapshot()
            try:
                run_once(args)
            except Exception as e:  # keep watching on transient errors
                print(f"error: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
