"""
Redirects to install.py — the new full installer.
Run install.py instead:  python install.py
"""
import runpy, os, sys
sys.argv[0] = os.path.join(os.path.dirname(__file__), "install.py")
runpy.run_path(sys.argv[0], run_name="__main__")
