#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""
ensure_ollama.py — called by docubrowser.py before any embedding operation.

Checks (in order):
  1. ollama binary is installed  → prompts to install if missing
     - Linux : curl -fsSL https://ollama.com/install.sh | sh
     - macOS : brew install ollama  (fallback: direct download URL)
  2. ollama service is reachable → starts `ollama serve` in background if not
  3. each model in REQUIRED_MODELS is present → prompts to pull if missing

If the user declines any prompt, prints manual instructions and exits non-zero.
"""

import json
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

# (model name, approx download size, what it's used for)
REQUIRED_MODELS = [
    ('nomic-embed-text:latest', '~274 MB', 'semantic search embeddings (ingestion)'),
    ('dolphin3:latest', '~4.9 GB', 'document synopsis generation (operational AI)'),
]

OLLAMA_API = 'http://localhost:11434'


def ok(msg):
    """Print a green-check-style success line."""
    print(f'  ✓ {msg}')


def info(msg):
    """Print an informational status line."""
    print(f'  → {msg}')


def err(msg):
    """Print an error line to stderr."""
    print(f'  ✗ {msg}', file=sys.stderr)


def ask(question, default_yes=True) -> bool:
    """Prompt the user for a yes/no answer; ^C or EOF returns False."""
    hint = '[Y/n]' if default_yes else '[y/N]'
    try:
        answer = input(f'  {question} {hint}: ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return (answer == '') and default_yes or answer in ('y', 'yes')


def platform() -> str:
    """Return the current OS as one of ``linux``/``macos``/``windows``/``unknown``."""
    if sys.platform == 'linux':
        return 'linux'
    if sys.platform == 'darwin':
        return 'macos'
    if sys.platform == 'win32':
        return 'windows'
    return 'unknown'


# ── 1. Binary present? ───────────────────────────────────────────────────────

def ollama_installed() -> bool:
    """Return True if the ``ollama`` binary is on PATH."""
    return shutil.which('ollama') is not None


# pylint: disable-next=too-many-statements
def install_ollama():
    """Interactively install ollama for the detected platform, or exit non-zero."""
    plat = platform()
    print()
    print('  Ollama is not installed. It is required for semantic search.')

    if plat == 'linux':
        if not ask('Install Ollama now? (curl -fsSL https://ollama.com/install.sh | sh)'):
            print()
            err('Ollama not installed. To install manually:')
            print('    curl -fsSL https://ollama.com/install.sh | sh', file=sys.stderr)
            sys.exit(1)
        print()
        ret = subprocess.run(
            'curl -fsSL https://ollama.com/install.sh | sh', shell=True, check=False,
        )
        if ret.returncode != 0 or not ollama_installed():
            err('Installation failed. Try manually:')
            print('    curl -fsSL https://ollama.com/install.sh | sh', file=sys.stderr)
            sys.exit(1)
        ok('Ollama installed.')

    elif plat == 'macos':
        if shutil.which('brew'):
            if not ask('Install Ollama via Homebrew? (brew install ollama)'):
                print()
                err('Ollama not installed. To install manually:')
                print('    brew install ollama', file=sys.stderr)
                print('    or download from: https://ollama.com/download', file=sys.stderr)
                sys.exit(1)
            print()
            ret = subprocess.run(['brew', 'install', 'ollama'], check=False)
            if ret.returncode != 0 or not ollama_installed():
                err('Homebrew install failed. Try downloading directly:')
                print('    https://ollama.com/download', file=sys.stderr)
                sys.exit(1)
            ok('Ollama installed via Homebrew.')
        else:
            print()
            err('Homebrew not found. Install Ollama manually on macOS:')
            print('    Option 1 — install Homebrew first: https://brew.sh', file=sys.stderr)
            print('               then: brew install ollama', file=sys.stderr)
            print('    Option 2 — download directly: https://ollama.com/download', file=sys.stderr)
            sys.exit(1)

    elif plat == 'windows':
        print()
        err('Ollama is not installed. Install it from:')
        print('    https://ollama.com/download/windows', file=sys.stderr)
        print()
        print('  After installing, restart this command.', file=sys.stderr)
        sys.exit(1)

    else:
        print()
        err(f'Unsupported platform ({sys.platform}). Install Ollama manually:')
        print('    https://ollama.com/download', file=sys.stderr)
        sys.exit(1)


# ── 2. Service reachable? ────────────────────────────────────────────────────

def ollama_reachable() -> bool:
    """Return True if ``ollama serve`` is answering on the local API port."""
    try:
        with urlopen(f'{OLLAMA_API}/api/tags', timeout=3):
            return True
    except URLError:
        return False


def start_ollama():
    """Spawn ``ollama serve`` as a detached background process and wait for it."""
    info('Ollama service not running — starting in background...')
    # Detached background process — intentional: it must outlive this script.
    # pylint: disable-next=consider-using-with
    subprocess.Popen(
        ['ollama', 'serve'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for i in range(15):
        time.sleep(1)
        if ollama_reachable():
            ok('Ollama service started.')
            return
        if i % 5 == 4:
            info(f'Waiting for Ollama service... ({i+1}s)')
    err('Ollama service did not become reachable within 15 seconds.')
    err('Try running manually: ollama serve')
    sys.exit(1)


# ── 3. Models present? ───────────────────────────────────────────────────────

def installed_models() -> set:
    """Return the set of model names Ollama currently reports as installed."""
    try:
        with urlopen(f'{OLLAMA_API}/api/tags', timeout=5) as resp:
            data = json.loads(resp.read())
        return {m.get('name', '') for m in data.get('models', [])}
    except (URLError, OSError, json.JSONDecodeError):
        return set()


def model_present(model: str, names: set) -> bool:
    """Return True if *model* (possibly with a :tag suffix) matches any name in *names*."""
    return any(model in name for name in names)


def pull_model(model: str, size: str, purpose: str):
    """Interactively pull an Ollama model, or exit non-zero if declined."""
    print()
    print(f'  The {model} model is not installed ({size} download).')
    print(f'  It is required for: {purpose}.')
    if not ask(f'Pull {model} now?'):
        print()
        err(f'{model} not pulled. To pull manually:')
        print(f'    ollama pull {model}', file=sys.stderr)
        sys.exit(1)
    print()
    ret = subprocess.run(['ollama', 'pull', model], check=False)
    if ret.returncode != 0:
        err(f'Failed to pull {model}. Try manually: ollama pull {model}')
        sys.exit(1)
    ok(f'{model} ready.')


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    """Verify Ollama binary, service, and required models — install / start / pull as needed."""
    print('Checking Ollama prerequisites...')

    if not ollama_installed():
        install_ollama()
    else:
        ok('ollama binary found.')

    if not ollama_reachable():
        start_ollama()
    else:
        ok('Ollama service reachable.')

    names = installed_models()
    for model, size, purpose in REQUIRED_MODELS:
        if model_present(model, names):
            ok(f'{model} model present.')
        else:
            pull_model(model, size, purpose)
            # Refresh so a later required model isn't re-checked against stale data
            names = installed_models()

    print('Ollama ready.\n')


if __name__ == '__main__':
    main()
