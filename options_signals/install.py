#!/usr/bin/env python3
"""
Options Trading Signals — Installer

Run once to set up the environment and create a desktop launcher:
    python install.py

Options:
    --port PORT          Streamlit port (default 8501)
    --venv PATH          Where to create the virtual environment
                         (default: .venv/ inside this directory)
    --skip-deps          Skip virtual-env creation and pip install
    --skip-launcher      Skip desktop-launcher creation (just install deps)
    --reinstall          Force recreate the virtual environment from scratch

Supported platforms: Linux, macOS, Windows
"""
from __future__ import annotations

import argparse
import base64
import os
import platform
import shutil
import stat
import struct
import subprocess
import sys
import textwrap
import zlib
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
APP_DIR    = Path(__file__).resolve().parent   # options_signals/
APP_NAME   = "Options Trading Signals"
APP_MAIN   = APP_DIR / "app.py"
ICON_SVG   = APP_DIR / "icon.svg"
REQ_FILE   = APP_DIR / "requirements.txt"
ENV_EXAMPLE= APP_DIR / ".env.example"
ENV_FILE   = APP_DIR / ".env"
LOG_DIR    = APP_DIR / "logs"


def _sep() -> None:
    print("-" * 56)


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m  {msg}")


def _warn(msg: str) -> None:
    print(f"  \033[33m⚠\033[0m  {msg}")


def _err(msg: str) -> None:
    print(f"  \033[31m✗\033[0m  {msg}")


def _step(msg: str) -> None:
    print(f"\n\033[1m{msg}\033[0m")


# ── Step 1 — Preflight checks ─────────────────────────────────────────────────
def check_prerequisites() -> None:
    _step("1/5  Checking prerequisites")

    ver = sys.version_info
    if ver < (3, 9):
        _err(f"Python 3.9+ required, found {ver.major}.{ver.minor}")
        sys.exit(1)
    _ok(f"Python {ver.major}.{ver.minor}.{ver.micro}")

    if not APP_MAIN.exists():
        _err(f"app.py not found at {APP_MAIN}")
        sys.exit(1)
    _ok(f"App directory: {APP_DIR}")

    if not REQ_FILE.exists():
        _err("requirements.txt not found")
        sys.exit(1)
    _ok("requirements.txt found")

    # Check if pip is available
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            check=True, capture_output=True
        )
        _ok("pip is available")
    except subprocess.CalledProcessError:
        _err("pip not found — install pip first: https://pip.pypa.io")
        sys.exit(1)


# ── Step 2 — Virtual environment ──────────────────────────────────────────────
def setup_venv(venv_path: Path, reinstall: bool) -> Path:
    _step("2/5  Setting up virtual environment")

    if reinstall and venv_path.exists():
        _warn(f"Removing existing venv at {venv_path}")
        shutil.rmtree(venv_path)

    if not venv_path.exists():
        print(f"  Creating venv at {venv_path} …", end="", flush=True)
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            check=True, capture_output=True
        )
        print(" done")
    else:
        _ok(f"Using existing venv: {venv_path}")

    # Resolve python / pip inside venv
    if platform.system() == "Windows":
        venv_python = venv_path / "Scripts" / "python.exe"
        venv_pip    = venv_path / "Scripts" / "pip.exe"
        venv_stream = venv_path / "Scripts" / "streamlit.exe"
    else:
        venv_python = venv_path / "bin" / "python"
        venv_pip    = venv_path / "bin" / "pip"
        venv_stream = venv_path / "bin" / "streamlit"

    if not venv_python.exists():
        _err(f"venv python not found at {venv_python}")
        sys.exit(1)

    _ok(f"venv python: {venv_python}")
    return venv_path


# ── Step 3 — Install dependencies ─────────────────────────────────────────────
def install_deps(venv_path: Path) -> None:
    _step("3/5  Installing dependencies")

    if platform.system() == "Windows":
        venv_python = str(venv_path / "Scripts" / "python.exe")
    else:
        venv_python = str(venv_path / "bin" / "python")

    # Always upgrade pip via 'python -m pip' — works on Windows where
    # calling pip.exe directly causes a file-lock error.
    subprocess.run(
        [venv_python, "-m", "pip", "install", "--upgrade", "pip", "-q"],
        check=True
    )
    _ok("pip upgraded")

    # Install requirements
    print("  Installing packages from requirements.txt …", end="", flush=True)
    subprocess.run(
        [venv_python, "-m", "pip", "install", "-r", str(REQ_FILE), "-q"],
        check=True
    )
    print(" done")
    _ok("All required packages installed")

    # Optional: websocket-client for live streaming
    try:
        subprocess.run(
            [venv_python, "-m", "pip", "install", "websocket-client", "-q"],
            check=True, capture_output=True
        )
        _ok("websocket-client installed (WebSocket live feed enabled)")
    except subprocess.CalledProcessError:
        _warn("websocket-client not installed — live WS streaming unavailable")

    # Create .env from .env.example if not present
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        shutil.copy(ENV_EXAMPLE, ENV_FILE)
        _ok(".env created from .env.example — add your UPSTOX_ACCESS_TOKEN there")
    elif not ENV_FILE.exists():
        ENV_FILE.write_text(
            "# Options Trading Signals — configuration\n"
            "# UPSTOX_ACCESS_TOKEN=your_token_here\n"
            "# UPSTOX_API_KEY=your_api_key\n"
            "# UPSTOX_API_SECRET=your_api_secret\n"
            "# UPSTOX_ENABLE_TRADING=false\n"
        )
        _ok(".env created — add your Upstox credentials to enable live data")

    # Ensure logs directory exists
    LOG_DIR.mkdir(exist_ok=True)


# ── Step 4 — Platform launcher ────────────────────────────────────────────────
def _resolve_streamlit(venv_path: Path) -> str:
    """Return the absolute path to the venv's streamlit executable."""
    if platform.system() == "Windows":
        st = venv_path / "Scripts" / "streamlit.exe"
    else:
        st = venv_path / "bin" / "streamlit"

    if st.exists():
        return str(st)
    # Fallback to python -m streamlit
    if platform.system() == "Windows":
        py = str(venv_path / "Scripts" / "python.exe")
    else:
        py = str(venv_path / "bin" / "python")
    return f"{py} -m streamlit"


def _make_exe(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def create_linux_launcher(venv_path: Path, port: int) -> None:
    streamlit_cmd = _resolve_streamlit(venv_path)

    # ── wrapper shell script (hidden from user, called by .desktop)
    wrapper = APP_DIR / "launch_app.sh"
    wrapper.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Auto-generated by install.py — do not edit manually
        set -euo pipefail
        cd "{APP_DIR}"
        LOG="{LOG_DIR}/app.log"
        echo "$(date -Iseconds)  Starting {APP_NAME} on port {port}" >> "$LOG"
        exec {streamlit_cmd} app.py \\
            --server.port {port} \\
            --server.headless false \\
            >> "$LOG" 2>&1
    """))
    _make_exe(wrapper)

    # ── .desktop file (registered in OS app menu)
    apps_dir = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    desktop_file = apps_dir / "options-trading-signals.desktop"

    icon_path = str(ICON_SVG) if ICON_SVG.exists() else "utilities-terminal"

    desktop_content = textwrap.dedent(f"""\
        [Desktop Entry]
        Version=1.1
        Type=Application
        Name={APP_NAME}
        GenericName=Options Trading Dashboard
        Comment=Real-time options signals for Indian derivatives
        Exec={wrapper}
        Icon={icon_path}
        Terminal=false
        Categories=Finance;Office;
        Keywords=options;trading;nifty;derivatives;signals;
        StartupNotify=true
    """)
    desktop_file.write_text(desktop_content)
    _make_exe(desktop_file)

    # ── Desktop shortcut
    desktop_dir = Path.home() / "Desktop"
    if desktop_dir.exists():
        shortcut = desktop_dir / "Options Trading Signals.desktop"
        shortcut.write_text(desktop_content)
        _make_exe(shortcut)
        _ok(f"Desktop shortcut: {shortcut}")
    else:
        _warn("~/Desktop not found — skipping desktop shortcut")

    _ok(f"App menu entry: {desktop_file}")
    _ok(f"Wrapper script: {wrapper}")

    # Refresh desktop database
    try:
        subprocess.run(
            ["update-desktop-database", str(apps_dir)],
            check=True, capture_output=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass  # Not critical

    print()
    print("  \033[33mNOTE:\033[0m If the Desktop icon doesn't open on double-click,")
    print("  right-click it → \033[1mAllow Launching\033[0m (Ubuntu/GNOME).")


def create_mac_launcher(venv_path: Path, port: int) -> None:
    streamlit_cmd = _resolve_streamlit(venv_path)

    # ── .command file for Finder double-click
    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)
    cmd_file = desktop / "Options Trading Signals.command"
    cmd_file.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # {APP_NAME} — double-click to start (auto-generated by install.py)
        cd "{APP_DIR}"
        mkdir -p "{LOG_DIR}"
        echo "$(date)  Starting {APP_NAME}" >> "{LOG_DIR}/app.log"
        {streamlit_cmd} app.py \\
            --server.port {port} \\
            --server.headless false \\
            2>> "{LOG_DIR}/app.log"
    """))
    _make_exe(cmd_file)
    _ok(f"Launcher created: {cmd_file}")

    # ── Minimal .app bundle so Dock icon works
    app_bundle = desktop / f"{APP_NAME}.app"
    macos_dir  = app_bundle / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)

    exec_file = macos_dir / "launch"
    exec_file.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        cd "{APP_DIR}"
        mkdir -p "{LOG_DIR}"
        {streamlit_cmd} app.py --server.port {port} --server.headless false \
            >> "{LOG_DIR}/app.log" 2>&1 &
        sleep 3
        open http://localhost:{port}
    """))
    _make_exe(exec_file)

    plist = app_bundle / "Contents" / "Info.plist"
    plist.write_text(textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
            "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>CFBundleName</key>        <string>{APP_NAME}</string>
            <key>CFBundleExecutable</key>  <string>launch</string>
            <key>CFBundleIdentifier</key>  <string>com.optionssignals.app</string>
            <key>CFBundleVersion</key>     <string>1.0</string>
            <key>CFBundlePackageType</key> <string>APPL</string>
        </dict>
        </plist>
    """))
    _ok(f"App bundle: {app_bundle}")

    print()
    print("  \033[33mNOTE:\033[0m On first launch, macOS may ask to confirm opening the app.")
    print("  Go to System Preferences → Security & Privacy → 'Open Anyway'.")
    print("  After that, double-clicking works every time.")


def _windows_desktop() -> Path:
    """
    Return the real Desktop path on Windows.
    OneDrive commonly moves it to ~/OneDrive/Desktop — read the registry
    to find the authoritative location, then fall back to common guesses.
    """
    # Registry is the most reliable source
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        desktop_path, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        p = Path(desktop_path)
        if p.exists():
            return p
    except Exception:
        pass

    # Common fallbacks (covers OneDrive-synced Desktop)
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "OneDrive" / "Desktop",
        Path(os.environ.get("USERPROFILE", str(home))) / "Desktop",
        Path(os.environ.get("USERPROFILE", str(home))) / "OneDrive" / "Desktop",
    ]
    for c in candidates:
        if c.exists():
            return c

    # Nothing found — just use home dir and warn
    _warn(f"Desktop folder not found — placing shortcut in {home}")
    return home


def create_windows_launcher(venv_path: Path, port: int) -> None:
    streamlit_exe = str(venv_path / "Scripts" / "streamlit.exe")
    python_exe    = str(venv_path / "Scripts" / "python.exe")

    desktop = _windows_desktop()
    _ok(f"Desktop folder: {desktop}")

    # ── 1. launch.bat inside the app folder (terminal version for debugging)
    bat_app = APP_DIR / "launch.bat"
    bat_app.write_text(textwrap.dedent(f"""\
        @echo off
        title {APP_NAME}
        cd /d "{APP_DIR}"
        if not exist "logs" mkdir logs
        echo Starting {APP_NAME} on port {port}...
        "{streamlit_exe}" run app.py ^
            --server.port {port} ^
            --server.headless false
        pause
    """), encoding="utf-8")

    # ── 2. Invisible VBScript launcher on Desktop
    #    VBScript runs the bat file with WindowStyle=0 (hidden), so no black
    #    terminal window appears when you double-click.
    vbs_file = desktop / "Options Trading Signals.vbs"
    vbs_file.write_text(textwrap.dedent(f"""\
        ' Options Trading Signals — silent launcher
        ' Double-click this file to start the app (no terminal window).
        Set sh = CreateObject("WScript.Shell")
        sh.Run "cmd /c """"{bat_app}""""", 0, False
    """), encoding="utf-8")
    _ok(f"Desktop launcher (VBS): {vbs_file}")

    # ── 3. .lnk shortcut pointing at the VBS so it shows a nice name/icon
    lnk_file = desktop / "Options Trading Signals.lnk"
    ps_script = (
        f'$ws = New-Object -ComObject WScript.Shell;'
        f'$lnk = $ws.CreateShortcut("{lnk_file}");'
        f'$lnk.TargetPath = "wscript.exe";'
        f'$lnk.Arguments = """{vbs_file}""";'
        f'$lnk.WorkingDirectory = "{APP_DIR}";'
        f'$lnk.Description = "{APP_NAME}";'
        f'$lnk.WindowStyle = 1;'
        f'$lnk.Save()'
    )
    try:
        subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps_script],
            check=True, capture_output=True, timeout=15,
        )
        _ok(f"Desktop shortcut (.lnk): {lnk_file}")
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        _warn(f"Could not create .lnk — use the .vbs file directly ({e})")

    print()
    print(f"  \033[32mLauncher files are on your Desktop:\033[0m")
    print(f"  • Options Trading Signals.lnk  ← double-click this")
    print(f"  • Options Trading Signals.vbs  ← backup (same thing)")
    print()
    print("  If Windows asks 'How do you want to open this?', choose")
    print("  \033[1mMicrosoft Windows Based Script Host\033[0m and tick 'Always'.")
    print()
    print("  \033[33mIf nothing appears on Desktop:\033[0m open File Explorer and")
    print(f"  navigate to:  {desktop}")


def create_launcher(venv_path: Path, port: int) -> None:
    _step("4/5  Creating desktop launcher")
    system = platform.system()
    if system == "Linux":
        create_linux_launcher(venv_path, port)
    elif system == "Darwin":
        create_mac_launcher(venv_path, port)
    elif system == "Windows":
        create_windows_launcher(venv_path, port)
    else:
        _warn(f"Unknown platform '{system}' — skipping desktop launcher")
        print(f"  Manual launch: cd \"{APP_DIR}\" && streamlit run app.py")


# ── Step 5 — Update launch.sh / launch.bat ────────────────────────────────────
def update_raw_launchers(venv_path: Path, port: int) -> None:
    _step("5/5  Updating raw launch scripts")

    # launch.sh (Linux / macOS)
    if platform.system() != "Windows":
        if platform.system() == "Windows":
            activate = str(venv_path / "Scripts" / "activate")
            streamlit = str(venv_path / "Scripts" / "streamlit")
        else:
            activate  = str(venv_path / "bin" / "activate")
            streamlit = str(venv_path / "bin" / "streamlit")

        launch_sh = APP_DIR / "launch.sh"
        launch_sh.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env bash
            # {APP_NAME} — quick launcher (generated by install.py)
            # Usage: ./launch.sh           → web UI
            #        ./launch.sh terminal  → terminal dashboard
            set -euo pipefail
            DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
            cd "$DIR"

            # Activate the venv created by install.py
            if [ -f "{activate}" ]; then
                # shellcheck disable=SC1090
                source "{activate}"
            fi

            if [ "${{1:-}}" = "terminal" ]; then
                python terminal_app.py "${{@:2}}"
            else
                echo "Starting {APP_NAME} → http://localhost:{port}"
                "{streamlit}" run app.py \\
                    --server.port {port} \\
                    --server.headless false
            fi
        """))
        _make_exe(launch_sh)
        _ok(f"launch.sh updated → {launch_sh}")

    # launch.bat (Windows)
    if platform.system() == "Windows":
        activate_bat = str(venv_path / "Scripts" / "activate.bat")
        launch_bat = APP_DIR / "launch.bat"
        launch_bat.write_text(textwrap.dedent(f"""\
            @echo off
            :: {APP_NAME} — quick launcher
            cd /d "%~dp0"
            if exist "{activate_bat}" call "{activate_bat}"
            if "%1"=="terminal" (
                python terminal_app.py %*
            ) else (
                echo Starting {APP_NAME} on port {port} ...
                streamlit run app.py --server.port {port} --server.headless false
            )
        """))
        _ok(f"launch.bat updated → {launch_bat}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port",           type=int, default=8501, metavar="PORT",
                        help="Port for the Streamlit app (default: 8501)")
    parser.add_argument("--venv",           type=Path, default=APP_DIR / ".venv",
                        metavar="PATH", help="Virtual environment location")
    parser.add_argument("--skip-deps",      action="store_true",
                        help="Skip venv creation and pip install")
    parser.add_argument("--skip-launcher",  action="store_true",
                        help="Skip desktop launcher creation")
    parser.add_argument("--reinstall",      action="store_true",
                        help="Delete and recreate the virtual environment")
    args = parser.parse_args()

    print()
    print("\033[1m📈  Options Trading Signals — Installer\033[0m")
    print(f"    Platform : {platform.system()} {platform.machine()}")
    print(f"    App dir  : {APP_DIR}")
    print(f"    Venv dir : {args.venv}")
    print(f"    Port     : {args.port}")
    _sep()

    check_prerequisites()

    venv_path = args.venv.resolve()

    if not args.skip_deps:
        setup_venv(venv_path, args.reinstall)
        install_deps(venv_path)
    else:
        _warn("Skipping dependency install (--skip-deps)")
        if not venv_path.exists():
            _err(f"No venv found at {venv_path} — run without --skip-deps first")
            sys.exit(1)

    if not args.skip_launcher:
        create_launcher(venv_path, args.port)
        update_raw_launchers(venv_path, args.port)
    else:
        _warn("Skipping launcher creation (--skip-launcher)")

    _sep()
    print()
    print("\033[32m\033[1m✅  Installation complete!\033[0m")
    print()
    print("  \033[1mHow to start the app:\033[0m")
    system = platform.system()
    if system == "Linux":
        print("  • Double-click the desktop icon  (if on GNOME/KDE)")
        print("  • Or from terminal:  ./launch.sh")
    elif system == "Darwin":
        print("  • Double-click  Options Trading Signals.command  on Desktop")
        print("  • Or from terminal:  ./launch.sh")
    elif system == "Windows":
        print("  • Double-click  Options Trading Signals.lnk  on Desktop")
        print("  • Or double-click  Options Trading Signals.bat  on Desktop")
    print()
    print("  \033[1mLive data (optional):\033[0m")
    print(f"  Edit  {ENV_FILE}")
    print("  and set UPSTOX_ACCESS_TOKEN to your Upstox OAuth token.")
    print()
    print("  \033[1mApp logs:\033[0m")
    print(f"  {LOG_DIR}/app.log")
    print()


if __name__ == "__main__":
    main()
