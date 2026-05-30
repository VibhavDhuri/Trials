#!/usr/bin/env python3
"""
Options Signals — Desktop Launcher Setup.

Run once to create a clickable app icon on your Desktop:
    python setup_launcher.py

What it does:
  Linux  → creates ~/.local/share/applications/OptionsSignals.desktop
             and a clickable launcher on ~/Desktop/
  macOS  → creates ~/Desktop/OptionsSignals.command (double-click to open)
  Windows → creates %USERPROFILE%\\Desktop\\OptionsSignals.bat
"""
from __future__ import annotations

import os
import platform
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

APP_NAME  = "Options Signals"
APP_ICON  = "📈"
APP_DIR   = Path(__file__).resolve().parent   # options_signals/
APP_MAIN  = APP_DIR / "app.py"
PORT      = 8501

PYTHON = sys.executable
try:
    STREAMLIT = subprocess.check_output([PYTHON, "-m", "streamlit", "--version"],
                                        stderr=subprocess.DEVNULL).decode().strip()
    STREAMLIT_CMD = f"{PYTHON} -m streamlit run"
except Exception:
    STREAMLIT_CMD = "streamlit run"


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _create_linux() -> None:
    desktop_dir = Path.home() / ".local" / "share" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    # Shell script that the .desktop file calls
    script = APP_DIR.parent / "launch_options_signals.sh"
    script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Options Signals launcher
        cd "{APP_DIR}"
        {STREAMLIT_CMD} app.py --server.port {PORT} --server.headless false
    """))
    _make_executable(script)

    desktop_file = desktop_dir / "OptionsSignals.desktop"
    desktop_file.write_text(textwrap.dedent(f"""\
        [Desktop Entry]
        Version=1.0
        Type=Application
        Name={APP_NAME}
        Comment=Real-time options trading signals for Indian derivatives
        Exec={script}
        Icon=utilities-terminal
        Terminal=false
        Categories=Finance;
        StartupNotify=true
    """))
    _make_executable(desktop_file)

    # Also put a copy on Desktop if it exists
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        shortcut = desktop / "OptionsSignals.desktop"
        shortcut.write_text(desktop_file.read_text())
        _make_executable(shortcut)
        print(f"  Desktop shortcut: {shortcut}")

    print(f"  Application menu entry: {desktop_file}")
    print(f"  Launch script: {script}")
    print()
    print("If double-click on Desktop doesn't work, right-click → Allow Launching.")


def _create_mac() -> None:
    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)
    cmd_file = desktop / "OptionsSignals.command"
    cmd_file.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Options Signals — double-click to launch
        cd "{APP_DIR}"
        {STREAMLIT_CMD} app.py --server.port {PORT} --server.headless false
    """))
    _make_executable(cmd_file)
    print(f"  Created: {cmd_file}")
    print()
    print("Double-click OptionsSignals.command in Finder to start the app.")
    print("macOS may ask for confirmation the first time — click 'Open'.")
    print()
    print("To add to your Dock:")
    print("  1. Open the .command file once so Terminal opens")
    print("  2. Right-click the Terminal icon in the Dock → Options → Keep in Dock")


def _create_windows() -> None:
    desktop = Path.home() / "Desktop"
    bat_file = desktop / "OptionsSignals.bat"
    bat_file.write_text(textwrap.dedent(f"""\
        @echo off
        cd /d "{APP_DIR}"
        {STREAMLIT_CMD} app.py --server.port {PORT} --server.headless false
        pause
    """))
    print(f"  Created: {bat_file}")
    print()
    print("Double-click OptionsSignals.bat on your Desktop to launch the app.")
    print()
    print("To make it look like a proper app:")
    print("  1. Right-click the .bat file → Create shortcut")
    print("  2. Right-click the shortcut → Properties → Change Icon")
    print("     Pick an icon from %SystemRoot%\\System32\\shell32.dll")


def main() -> None:
    print(f"\n{APP_ICON}  Options Signals — Launcher Setup")
    print("=" * 50)

    system = platform.system()
    print(f"Detected OS: {system}")
    print(f"App directory: {APP_DIR}")
    print(f"Streamlit command: {STREAMLIT_CMD}")
    print()

    if not APP_MAIN.exists():
        print(f"ERROR: app.py not found at {APP_MAIN}")
        sys.exit(1)

    if system == "Linux":
        _create_linux()
    elif system == "Darwin":
        _create_mac()
    elif system == "Windows":
        _create_windows()
    else:
        print(f"Unsupported OS '{system}'. Create a shortcut manually:")
        print(f"  Command: {STREAMLIT_CMD} app.py")
        print(f"  Working directory: {APP_DIR}")
        sys.exit(1)

    print()
    print("Done! The app will open in your default browser when launched.")
    print(f"Manual start: cd \"{APP_DIR}\" && {STREAMLIT_CMD} app.py")


if __name__ == "__main__":
    main()
