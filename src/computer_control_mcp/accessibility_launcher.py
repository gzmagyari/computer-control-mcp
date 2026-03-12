#!/usr/bin/env python3
"""Accessibility-aware application launcher.

This module provides a reusable ``launch_app`` function and a CLI that launch an
application with best-effort accessibility-related flags and environment
variables.

Primary goals
-------------
- Linux / Ubuntu:
  - Best-effort session-level AT-SPI activation via the user D-Bus session.
  - App-family-specific environment variables and flags.
- Windows:
  - App-family-specific command-line flags where documented or low-risk.
  - Launch the process in a normal way for later inspection via UI Automation /
    MSAA.

This launcher is intentionally conservative by default: it avoids silently
writing persistent desktop settings unless ``--persist-gnome-a11y`` is passed.

Examples
--------
# Simple launch
python accessibility_launcher.py -- code .

# Pass app args safely after --
python accessibility_launcher.py -- google-chrome --incognito https://example.com

# Flatpak app
python accessibility_launcher.py -- flatpak run com.visualstudio.code --new-window .

# JSON-only output for an MCP wrapper
python accessibility_launcher.py --json -- code --new-window .
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, Iterable, List, MutableMapping, Optional, Sequence, Tuple


# ----------------------------- App registry -----------------------------

@dataclass(frozen=True)
class AppProfile:
    family: str
    display_name: str
    notes: Tuple[str, ...] = ()


KNOWN_APPS: Dict[str, AppProfile] = {
    # Chromium browsers
    "google-chrome": AppProfile("chromium", "Google Chrome"),
    "google-chrome-stable": AppProfile("chromium", "Google Chrome"),
    "google-chrome-beta": AppProfile("chromium", "Google Chrome Beta"),
    "google-chrome-unstable": AppProfile("chromium", "Google Chrome Dev"),
    "chrome": AppProfile("chromium", "Chrome"),
    "chrome.exe": AppProfile("chromium", "Chrome"),
    "chromium": AppProfile("chromium", "Chromium"),
    "chromium-browser": AppProfile("chromium", "Chromium Browser"),
    "brave": AppProfile("chromium", "Brave"),
    "brave.exe": AppProfile("chromium", "Brave"),
    "brave-browser": AppProfile("chromium", "Brave Browser"),
    "msedge": AppProfile("chromium", "Microsoft Edge"),
    "msedge.exe": AppProfile("chromium", "Microsoft Edge"),
    "microsoft-edge": AppProfile("chromium", "Microsoft Edge"),
    "microsoft-edge-stable": AppProfile("chromium", "Microsoft Edge"),
    "microsoft-edge-beta": AppProfile("chromium", "Microsoft Edge Beta"),
    "microsoft-edge-dev": AppProfile("chromium", "Microsoft Edge Dev"),
    "vivaldi": AppProfile("chromium", "Vivaldi"),
    "opera": AppProfile("chromium", "Opera"),
    "opera-stable": AppProfile("chromium", "Opera Stable"),
    "yandex-browser": AppProfile("chromium", "Yandex Browser"),
    "thorium-browser": AppProfile("chromium", "Thorium Browser"),

    # VS Code family / Electron-based IDEs that have a documented Linux env var.
    "code": AppProfile("vscode", "Visual Studio Code"),
    "code-insiders": AppProfile("vscode", "Visual Studio Code Insiders"),
    "code-oss": AppProfile("vscode", "Code OSS"),
    "codium": AppProfile("vscode", "VSCodium"),
    "vscodium": AppProfile("vscode", "VSCodium"),
    "cursor": AppProfile("vscode", "Cursor"),
    "cursor.exe": AppProfile("vscode", "Cursor"),
    "windsurf": AppProfile("vscode", "Windsurf"),
    "windsurf.exe": AppProfile("vscode", "Windsurf"),

    # Common Electron apps. These get the Chromium accessibility flag as a
    # best-effort because Electron supports Chromium flags and ignores
    # unsupported ones.
    "slack": AppProfile("electron", "Slack"),
    "slack.exe": AppProfile("electron", "Slack"),
    "discord": AppProfile("electron", "Discord"),
    "discord.exe": AppProfile("electron", "Discord"),
    "signal-desktop": AppProfile("electron", "Signal Desktop"),
    "signal": AppProfile("electron", "Signal Desktop"),
    "obsidian": AppProfile("electron", "Obsidian"),
    "postman": AppProfile("electron", "Postman"),
    "element-desktop": AppProfile("electron", "Element Desktop"),
    "element": AppProfile("electron", "Element Desktop"),
    "bitwarden": AppProfile("electron", "Bitwarden Desktop"),
    "bitwarden-desktop": AppProfile("electron", "Bitwarden Desktop"),
    "standard-notes": AppProfile("electron", "Standard Notes"),
    "simplenote": AppProfile("electron", "Simplenote"),
    "insomnia": AppProfile("electron", "Insomnia"),
    "teams-for-linux": AppProfile("electron", "Teams for Linux"),
    "teams": AppProfile("electron", "Teams"),
    "microsoft-teams": AppProfile("electron", "Microsoft Teams"),
    "notion-app-enhanced": AppProfile("electron", "Notion (enhanced)"),

    # Qt / KDE / other common Qt desktop apps on Linux.
    "kate": AppProfile("qt", "Kate"),
    "kwrite": AppProfile("qt", "KWrite"),
    "dolphin": AppProfile("qt", "Dolphin"),
    "okular": AppProfile("qt", "Okular"),
    "gwenview": AppProfile("qt", "Gwenview"),
    "konsole": AppProfile("qt", "Konsole"),
    "yakuake": AppProfile("qt", "Yakuake"),
    "kcalc": AppProfile("qt", "KCalc"),
    "kcharselect": AppProfile("qt", "KCharSelect"),
    "kfind": AppProfile("qt", "KFind"),
    "kdevelop": AppProfile("qt", "KDevelop"),
    "qtcreator": AppProfile("qt", "Qt Creator"),
    "assistant": AppProfile("qt", "Qt Assistant"),
    "designer": AppProfile("qt", "Qt Designer"),
    "linguist": AppProfile("qt", "Qt Linguist"),
    "vlc": AppProfile("qt", "VLC"),
    "qbittorrent": AppProfile("qt", "qBittorrent"),
    "keepassxc": AppProfile("qt", "KeePassXC"),
    "telegram-desktop": AppProfile("qt", "Telegram Desktop"),
    "virtualbox": AppProfile("qt", "VirtualBox"),
    "wireshark": AppProfile("qt", "Wireshark"),
    "calibre": AppProfile("qt", "Calibre"),
    "anki": AppProfile("qt", "Anki"),

    # JetBrains IDEs. On Linux these currently remain a weak case for screen
    # reader support; the launcher can still start them and enable the session.
    "idea": AppProfile("jetbrains", "IntelliJ IDEA"),
    "intellij-idea": AppProfile("jetbrains", "IntelliJ IDEA"),
    "intellij-idea-community": AppProfile("jetbrains", "IntelliJ IDEA Community"),
    "intellij-idea-ultimate": AppProfile("jetbrains", "IntelliJ IDEA Ultimate"),
    "pycharm": AppProfile("jetbrains", "PyCharm"),
    "pycharm-professional": AppProfile("jetbrains", "PyCharm Professional"),
    "pycharm-community": AppProfile("jetbrains", "PyCharm Community"),
    "webstorm": AppProfile("jetbrains", "WebStorm"),
    "phpstorm": AppProfile("jetbrains", "PhpStorm"),
    "rider": AppProfile("jetbrains", "Rider"),
    "clion": AppProfile("jetbrains", "CLion"),
    "goland": AppProfile("jetbrains", "GoLand"),
    "datagrip": AppProfile("jetbrains", "DataGrip"),
    "rubymine": AppProfile("jetbrains", "RubyMine"),
    "android-studio": AppProfile("jetbrains", "Android Studio"),

    # GTK-ish / GNOME apps do not need per-app toggles here; session-level AT-SPI
    # is usually the relevant part. They are included to make "list known apps"
    # output nicer.
    "firefox": AppProfile("gtk", "Firefox"),
    "nautilus": AppProfile("gtk", "Files / Nautilus"),
    "gedit": AppProfile("gtk", "Gedit"),
    "gnome-text-editor": AppProfile("gtk", "GNOME Text Editor"),
    "gnome-terminal": AppProfile("gtk", "GNOME Terminal"),
    "evince": AppProfile("gtk", "Evince"),
    "thunderbird": AppProfile("gtk", "Thunderbird"),
}


FAMILY_CHOICES = ("auto", "chromium", "electron", "vscode", "qt", "gtk", "jetbrains", "none")

# Common wrapper commands. We support a few so the script is useful for PATH,
# Flatpak, and Snap launches.
WRAPPER_COMMANDS = {"flatpak", "flatpak.exe", "snap", "snap.exe"}

# Low-risk Chromium switch. Supported browsers use it; Electron apps can accept
# Chromium switches, and Electron docs say unsupported switches simply have no
# effect.
FORCE_RENDERER_ACCESSIBILITY = "--force-renderer-accessibility"


# ---------------------------- Result types -----------------------------

@dataclass
class LaunchResult:
    platform: str
    requested_command: List[str]
    effective_command: List[str]
    family: str
    matched_app: Optional[str]
    pid: Optional[int]
    dry_run: bool
    launched: bool
    env_overrides: Dict[str, str] = field(default_factory=dict)
    env_removed: List[str] = field(default_factory=list)
    session_actions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# --------------------------- Utility helpers ---------------------------


def _platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _basename(value: str) -> str:
    return Path(value).name.lower()


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _append_colon_env(env: MutableMapping[str, str], key: str, parts: Iterable[str]) -> None:
    existing = [p for p in env.get(key, "").split(":") if p]
    merged = _dedupe_preserve_order([*existing, *parts])
    if merged:
        env[key] = ":".join(merged)


def _ensure_flag(args: List[str], flag: str, *, insert_at: Optional[int] = None) -> List[str]:
    if flag in args:
        return args
    if insert_at is None or insert_at >= len(args):
        args.append(flag)
    else:
        args.insert(insert_at, flag)
    return args


@dataclass(frozen=True)
class WrapperInfo:
    base_command: List[str]
    wrapper: Optional[str]
    target_token: str
    target_token_index: int


def _parse_wrapper(command: Sequence[str]) -> WrapperInfo:
    if not command:
        raise ValueError("command may not be empty")

    base = list(command)
    wrapper = _basename(base[0])

    def _find_target(start_index: int) -> Optional[int]:
        for idx in range(start_index, len(base)):
            token = base[idx]
            if not token.startswith("-"):
                return idx
        return None

    if wrapper == "flatpak" and len(base) >= 3 and base[1] == "run":
        idx = _find_target(2)
        if idx is not None:
            return WrapperInfo(base_command=base, wrapper="flatpak", target_token=base[idx], target_token_index=idx)
    if wrapper == "snap" and len(base) >= 3 and base[1] == "run":
        idx = _find_target(2)
        if idx is not None:
            return WrapperInfo(base_command=base, wrapper="snap", target_token=base[idx], target_token_index=idx)

    return WrapperInfo(base_command=base, wrapper=None, target_token=base[0], target_token_index=0)


def _detect_family(target_token: str, explicit_family: str = "auto") -> Tuple[str, Optional[str]]:
    if explicit_family and explicit_family != "auto":
        return explicit_family, None

    lower = _basename(target_token)
    if lower in KNOWN_APPS:
        return KNOWN_APPS[lower].family, lower

    # Heuristics for unknown commands.
    chromium_fragments = ("chrome", "chromium", "edge", "brave", "vivaldi", "opera")
    qt_fragments = ("kde", "qt", "dolphin", "okular", "konsole", "keepassxc", "qbittorrent")
    vscode_fragments = ("code", "cursor", "windsurf", "codium")
    electron_fragments = ("discord", "slack", "signal", "obsidian", "postman", "bitwarden", "teams")
    jetbrains_fragments = ("idea", "pycharm", "webstorm", "phpstorm", "rider", "clion", "goland", "datagrip", "rubymine")

    if any(fragment in lower for fragment in vscode_fragments):
        return "vscode", None
    if any(fragment in lower for fragment in chromium_fragments):
        return "chromium", None
    if any(fragment in lower for fragment in electron_fragments):
        return "electron", None
    if any(fragment in lower for fragment in qt_fragments):
        return "qt", None
    if any(fragment in lower for fragment in jetbrains_fragments):
        return "jetbrains", None
    return "none", None


# ------------------------ Linux session accessibility ------------------------


def _run_best_effort(cmd: Sequence[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            list(cmd),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, f"missing executable: {cmd[0]}"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"{cmd[0]} failed to run: {exc}"

    if proc.returncode == 0:
        detail = proc.stdout.strip() or proc.stderr.strip() or "ok"
        return True, detail
    detail = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
    return False, detail


def _ensure_linux_a11y_session(session_actions: List[str], warnings: List[str], *, persist_gnome_a11y: bool) -> None:
    """Best-effort session setup for Linux/Ubuntu.

    Strategy:
    1. Ensure the accessibility bus can start on demand (GetAddress).
    2. Try to set the org.a11y.Status properties via busctl, dbus-send, or gdbus.
    3. Optionally set persistent GNOME keys if explicitly requested.
    """

    # 1) Wake / start the accessibility bus on demand.
    start_attempts: List[Tuple[List[str], str]] = [
        (["busctl", "--user", "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress"], "busctl GetAddress"),
        (["gdbus", "call", "--session", "--dest", "org.a11y.Bus", "--object-path", "/org/a11y/bus", "--method", "org.a11y.Bus.GetAddress"], "gdbus GetAddress"),
    ]

    bus_started = False
    for cmd, label in start_attempts:
        ok, detail = _run_best_effort(cmd)
        if ok:
            session_actions.append(f"{label}: {detail}")
            bus_started = True
            break
        session_actions.append(f"{label} failed: {detail}")

    if not bus_started:
        launcher_path = shutil.which("at-spi-bus-launcher")
        if launcher_path:
            try:
                subprocess.Popen(
                    [launcher_path, "--launch-immediately"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
                session_actions.append("started at-spi-bus-launcher --launch-immediately")
                # Try again after launching.
                ok, detail = _run_best_effort(["gdbus", "call", "--session", "--dest", "org.a11y.Bus", "--object-path", "/org/a11y/bus", "--method", "org.a11y.Bus.GetAddress"])
                if ok:
                    session_actions.append(f"gdbus GetAddress after launcher: {detail}")
                    bus_started = True
                else:
                    session_actions.append(f"gdbus GetAddress after launcher failed: {detail}")
            except Exception as exc:  # pragma: no cover - defensive
                warnings.append(f"failed to start at-spi-bus-launcher: {exc}")
        else:
            session_actions.append("at-spi-bus-launcher not found")

    # 2) Best-effort property writes for toolkits that key off org.a11y.Status.
    prop_attempts = [
        lambda prop: (["busctl", "--user", "set-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", prop, "b", "true"], f"busctl set {prop}=true"),
        lambda prop: (["dbus-send", "--session", "--print-reply", "--dest=org.a11y.Bus", "/org/a11y/bus", "org.freedesktop.DBus.Properties.Set", "string:org.a11y.Status", f"string:{prop}", "variant:boolean:true"], f"dbus-send set {prop}=true"),
        lambda prop: (["gdbus", "call", "--session", "--dest", "org.a11y.Bus", "--object-path", "/org/a11y/bus", "--method", "org.freedesktop.DBus.Properties.Set", "org.a11y.Status", prop, "<true>"], f"gdbus set {prop}=true"),
    ]

    for prop in ("IsEnabled", "ScreenReaderEnabled"):
        applied = False
        for builder in prop_attempts:
            cmd, label = builder(prop)
            ok, detail = _run_best_effort(cmd)
            if ok:
                session_actions.append(f"{label}: {detail}")
                applied = True
                break
            session_actions.append(f"{label} failed: {detail}")
        if not applied:
            warnings.append(f"could not set org.a11y.Status.{prop}; app-specific env vars may still help")

    # 3) Optional persistent GNOME settings.
    if persist_gnome_a11y:
        gsettings_cmds = [
            (["gsettings", "set", "org.gnome.desktop.interface", "toolkit-accessibility", "true"],
             "gsettings set org.gnome.desktop.interface toolkit-accessibility true"),
            (["gsettings", "set", "org.gnome.desktop.a11y.applications", "screen-reader-enabled", "true"],
             "gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true"),
        ]
        for cmd, label in gsettings_cmds:
            ok, detail = _run_best_effort(cmd)
            if ok:
                session_actions.append(f"{label}: {detail}")
            else:
                warnings.append(f"{label} failed: {detail}")


# ------------------------ Rule application logic -----------------------


def _apply_rules(
    *,
    platform_name: str,
    command: Sequence[str],
    explicit_family: str,
    accessibility: bool,
    persist_gnome_a11y: bool,
    aggressive_legacy_gtk: bool,
    extra_env: Dict[str, str],
    perform_session_actions: bool,
) -> Tuple[List[str], Dict[str, str], List[str], List[str], List[str], str, Optional[str], List[str]]:
    """Apply platform and app-family launch rules.

    Returns:
        final_command, env_overrides, env_removed, session_actions, warnings,
        family, matched_app, notes
    """

    wrapper = _parse_wrapper(command)
    family, matched_app = _detect_family(wrapper.target_token, explicit_family)

    final_command = list(command)
    env_overrides: Dict[str, str] = {}
    env_removed: List[str] = []
    session_actions: List[str] = []
    warnings: List[str] = []
    notes: List[str] = []

    if matched_app and matched_app in KNOWN_APPS:
        notes.extend(KNOWN_APPS[matched_app].notes)

    if not accessibility:
        return final_command, env_overrides, env_removed, session_actions, warnings, family, matched_app, notes

    # Remove common Linux variables that disable accessibility if they leak in.
    if platform_name == "linux":
        for var in ("NO_AT_BRIDGE", "NO_GAIL"):
            if os.environ.get(var):
                env_removed.append(var)
        if perform_session_actions:
            _ensure_linux_a11y_session(session_actions, warnings, persist_gnome_a11y=persist_gnome_a11y)
        else:
            session_actions.append("dry-run: skipped Linux session accessibility activation")

    # App family rules.
    if family in {"chromium", "electron"}:
        insert_at = wrapper.target_token_index + 1
        final_command = _ensure_flag(final_command, FORCE_RENDERER_ACCESSIBILITY, insert_at=insert_at)
        if wrapper.wrapper == "flatpak":
            notes.append("added Chromium accessibility switch for Flatpak target")
        elif wrapper.wrapper == "snap":
            notes.append("added Chromium accessibility switch for Snap target")
        else:
            notes.append("added Chromium accessibility switch")

    if family == "vscode":
        if platform_name == "linux":
            env_overrides["ACCESSIBILITY_ENABLED"] = "1"
            notes.append("set ACCESSIBILITY_ENABLED=1 for VS Code-style app")
            notes.append("VS Code-family apps may still need editor.accessibilitySupport=on inside the app")
        # Some wrappers ignore Chromium flags; stay conservative here.

    if family == "qt":
        if platform_name == "linux":
            env_overrides["QT_LINUX_ACCESSIBILITY_ALWAYS_ON"] = "1"
            notes.append("set QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 for Qt/KDE app")

    if family == "gtk":
        if platform_name == "linux":
            notes.append("relying on session-level AT-SPI for GTK/GNOME-style app")

    if family == "jetbrains":
        if platform_name == "linux":
            warnings.append("JetBrains docs currently document screen reader support on Windows and macOS, not Linux")
        notes.append("launched JetBrains app without app-specific flags")

    # Aggressive legacy GTK/ATK bridge mode. Useful in some mixed environments,
    # but disabled by default because modern desktops typically manage this.
    if aggressive_legacy_gtk and platform_name == "linux":
        env_overrides.setdefault("GNOME_ACCESSIBILITY", "1")
        existing_modules = [p for p in os.environ.get("GTK_MODULES", "").split(":") if p]
        merged_modules = _dedupe_preserve_order([*existing_modules, "gail", "atk-bridge"])
        env_overrides["GTK_MODULES"] = ":".join(merged_modules)
        notes.append("enabled aggressive legacy GTK accessibility environment hints")

    # Apply user-provided env last so the caller can override the launcher if
    # they know better.
    env_overrides.update(extra_env)

    return final_command, env_overrides, env_removed, session_actions, warnings, family, matched_app, notes


def _build_env(env_overrides: Dict[str, str], env_removed: List[str], *, wrapper: Optional[str]) -> Dict[str, str]:
    env = dict(os.environ)
    for key in env_removed:
        env.pop(key, None)
    for key, value in env_overrides.items():
        env[key] = value
    if wrapper == "flatpak":
        # The flatpak command line will carry env values into the sandbox; we do
        # not need to leave them in the parent environment as well.
        for key in env_overrides:
            env.pop(key, None)
    return env


def _inject_flatpak_env(command: Sequence[str], env_overrides: Dict[str, str]) -> List[str]:
    final_command = list(command)
    if len(final_command) < 3 or _basename(final_command[0]) != "flatpak" or final_command[1] != "run":
        return final_command

    existing_env_flags = {arg for arg in final_command[2:] if arg.startswith("--env=")}
    insert_at = 2
    to_insert: List[str] = []
    for key, value in env_overrides.items():
        flag = f"--env={key}={value}"
        if flag not in existing_env_flags:
            to_insert.append(flag)
    if to_insert:
        final_command[insert_at:insert_at] = to_insert
    return final_command


# ---------------------------- Public API -------------------------------


def launch_app(
    command: Sequence[str],
    *,
    accessibility: bool = True,
    family: str = "auto",
    cwd: Optional[str] = None,
    persist_gnome_a11y: bool = False,
    aggressive_legacy_gtk: bool = False,
    dry_run: bool = False,
    extra_env: Optional[Dict[str, str]] = None,
) -> LaunchResult:
    """Launch an application with best-effort accessibility settings.

    Parameters
    ----------
    command:
        Full command line as a sequence, e.g. ``["code", "."]`` or
        ``["flatpak", "run", "com.visualstudio.code", "."]``.
    accessibility:
        Whether to apply accessibility-related rules.
    family:
        One of ``auto``, ``chromium``, ``electron``, ``vscode``, ``qt``,
        ``gtk``, ``jetbrains``, or ``none``.
    cwd:
        Working directory for the launched process.
    persist_gnome_a11y:
        On Linux, also write GNOME accessibility GSettings keys. Off by default.
    aggressive_legacy_gtk:
        On Linux, add older GTK accessibility environment hints. Off by default.
    dry_run:
        Compute and return the command without launching.
    extra_env:
        Additional environment variables to inject.
    """

    if not command:
        raise ValueError("command must not be empty")
    if family not in FAMILY_CHOICES:
        raise ValueError(f"family must be one of {', '.join(FAMILY_CHOICES)}")

    platform_name = _platform()
    env_overrides_user = dict(extra_env or {})

    (
        final_command,
        env_overrides,
        env_removed,
        session_actions,
        warnings,
        resolved_family,
        matched_app,
        notes,
    ) = _apply_rules(
        platform_name=platform_name,
        command=command,
        explicit_family=family,
        accessibility=accessibility,
        persist_gnome_a11y=persist_gnome_a11y,
        aggressive_legacy_gtk=aggressive_legacy_gtk,
        extra_env=env_overrides_user,
        perform_session_actions=not dry_run,
    )

    wrapper = _parse_wrapper(final_command)
    if wrapper.wrapper == "flatpak" and env_overrides:
        final_command = _inject_flatpak_env(final_command, env_overrides)

    env = _build_env(env_overrides, env_removed, wrapper=wrapper.wrapper)

    if dry_run:
        return LaunchResult(
            platform=platform_name,
            requested_command=list(command),
            effective_command=list(final_command),
            family=resolved_family,
            matched_app=matched_app,
            pid=None,
            dry_run=True,
            launched=False,
            env_overrides=dict(env_overrides),
            env_removed=list(env_removed),
            session_actions=list(session_actions),
            notes=list(notes),
            warnings=list(warnings),
        )

    popen_kwargs = {
        "cwd": cwd,
        "env": env,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }

    if platform_name == "windows":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(list(final_command), **popen_kwargs)

    return LaunchResult(
        platform=platform_name,
        requested_command=list(command),
        effective_command=list(final_command),
        family=resolved_family,
        matched_app=matched_app,
        pid=proc.pid,
        dry_run=False,
        launched=True,
        env_overrides=dict(env_overrides),
        env_removed=list(env_removed),
        session_actions=list(session_actions),
        notes=list(notes),
        warnings=list(warnings),
    )


# ------------------------------- CLI ----------------------------------


def _parse_env_assignments(values: Optional[Sequence[str]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise ValueError(f"invalid --set-env value {item!r}; expected KEY=VALUE")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"invalid --set-env value {item!r}; empty key")
        result[key] = value
    return result


def _format_command(command: Sequence[str]) -> str:
    return shlex.join(list(command))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch an app with best-effort accessibility settings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python accessibility_launcher.py -- code .\n"
            "  python accessibility_launcher.py -- google-chrome --incognito https://example.com\n"
            "  python accessibility_launcher.py -- flatpak run com.visualstudio.code --new-window .\n"
            "  python accessibility_launcher.py --dry-run -- code .\n"
        ),
    )
    parser.add_argument("--family", choices=FAMILY_CHOICES, default="auto", help="override app family detection")
    parser.add_argument("--no-accessibility", action="store_true", help="launch without any accessibility tweaks")
    parser.add_argument("--persist-gnome-a11y", action="store_true", help="on Linux, also set GNOME accessibility gsettings keys")
    parser.add_argument("--aggressive-legacy-gtk", action="store_true", help="on Linux, add older GTK accessibility env hints")
    parser.add_argument("--cwd", help="working directory")
    parser.add_argument("--set-env", action="append", default=[], metavar="KEY=VALUE", help="extra env var to inject; can be repeated")
    parser.add_argument("--dry-run", action="store_true", help="print the computed launch plan but do not launch")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON only")
    parser.add_argument("--list-known-apps", action="store_true", help="print the built-in app registry and exit")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command to run, preferably after --")
    return parser


def _list_known_apps() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for key in sorted(KNOWN_APPS):
        profile = KNOWN_APPS[key]
        rows.append({"command": key, "family": profile.family, "display_name": profile.display_name})
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_known_apps:
        if args.json:
            print(json.dumps(_list_known_apps(), indent=2))
        else:
            for row in _list_known_apps():
                print(f"{row['command']:<28} {row['family']:<10} {row['display_name']}")
        return 0

    if not args.command:
        parser.error("missing command to launch; put it after --")

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing command to launch after --")

    try:
        extra_env = _parse_env_assignments(args.set_env)
        result = launch_app(
            command,
            accessibility=not args.no_accessibility,
            family=args.family,
            cwd=args.cwd,
            persist_gnome_a11y=args.persist_gnome_a11y,
            aggressive_legacy_gtk=args.aggressive_legacy_gtk,
            dry_run=args.dry_run,
            extra_env=extra_env,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2

    payload = asdict(result)
    payload["ok"] = True

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Platform:         {result.platform}")
    print(f"Family:           {result.family}")
    if result.matched_app:
        print(f"Matched app:      {result.matched_app}")
    print(f"Requested:        {_format_command(result.requested_command)}")
    print(f"Effective:        {_format_command(result.effective_command)}")
    print(f"Launched:         {result.launched}")
    if result.pid is not None:
        print(f"PID:              {result.pid}")
    if result.env_overrides:
        print("Env overrides:")
        for key, value in sorted(result.env_overrides.items()):
            print(f"  {key}={value}")
    if result.env_removed:
        print("Env removed:")
        for key in result.env_removed:
            print(f"  {key}")
    if result.session_actions:
        print("Session actions:")
        for item in result.session_actions:
            print(f"  - {item}")
    if result.notes:
        print("Notes:")
        for item in result.notes:
            print(f"  - {item}")
    if result.warnings:
        print("Warnings:")
        for item in result.warnings:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
