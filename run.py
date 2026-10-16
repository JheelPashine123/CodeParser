#!/usr/bin/env python3
"""GraphAgent Standalone 1-Command Cross-Platform Runner.

Runs on any Mac, Linux, or Windows machine without prior installation.
Usage:
    python3 run.py .
    python3 run.py /path/to/repo --verbose
"""

import os
import sys
import subprocess
from pathlib import Path

def main():
    script_dir = Path(__file__).resolve().parent
    cache_dir = Path.home() / ".cache" / "graphagent"
    venv_dir = cache_dir / "venv"

    # Identify venv python executable
    if sys.platform == "win32":
        venv_python = venv_dir / "Scripts" / "python.exe"
        venv_graphagent = venv_dir / "Scripts" / "graphagent.exe"
    else:
        venv_python = venv_dir / "bin" / "python3"
        venv_graphagent = venv_dir / "bin" / "graphagent"

    # Bootstrap isolated environment if needed
    if not venv_graphagent.exists():
        print("⚡ First-time setup: Initializing isolated environment in ~/.cache/graphagent...")
        cache_dir.mkdir(parents=True, exist_ok=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
        subprocess.check_call([str(venv_python), "-m", "pip", "install", "--upgrade", "--quiet", "pip"])
        subprocess.check_call([str(venv_python), "-m", "pip", "install", "--quiet", str(script_dir)])
        print("✅ Environment ready!")

    # Forward arguments to graphagent
    args = sys.argv[1:]
    target_path = args[0] if args else "."
    remaining_flags = args[1:] if len(args) > 1 else []

    cmd = [str(venv_graphagent), "parse", target_path] + remaining_flags
    exit_code = subprocess.call(cmd)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
