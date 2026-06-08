#!/usr/bin/env python3
"""
ensure_ollama.py — called by docubrowser.py before any embedding operation.

Checks (in order):
  1. ollama binary is installed  → prompts to install if missing
     - Linux : curl -fsSL https://ollama.com/install.sh | sh
     - macOS : brew install ollama  (fallback: direct download URL)
  2. ollama service is reachable → starts `ollama serve` in background if not
  3. nomic-embed-text:latest is present → prompts to pull (~274 MB) if missing

If the user declines any prompt, prints manual instructions and exits non-zero.
"""

import json
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

MODEL      = 'nomic-embed-text:latest'
OLLAMA_API = 'http://localhost:11434'


def ok(msg):   print(f'  ✓ {msg}')
def info(msg): print(f'  → {msg}')
def err(msg):  print(f'  ✗ {msg}', file=sys.stderr)


def ask(question, default_yes=True) -> bool:
    hint = '[Y/n]' if default_yes else '[y/N]'
    try:
        answer = input(f'  {question} {hint}: ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return (answer == '') and default_yes or answer in ('y', 'yes')


def platform() -> str:
    if sys.platform == 'linux':
        return 'linux'
    if sys.platform == 'darwin':
        return 'macos'
    return 'unknown'


# ── 1. Binary present? ───────────────────────────────────────────────────────

def ollama_installed() -> bool:
    return shutil.which('ollama') is not None


def install_ollama():
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
        ret = subprocess.run('curl -fsSL https://ollama.com/install.sh | sh', shell=True)
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
            ret = subprocess.run(['brew', 'install', 'ollama'])
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

    else:
        print()
        err(f'Unsupported platform ({sys.platform}). Install Ollama manually:')
        print('    https://ollama.com/download', file=sys.stderr)
        sys.exit(1)


# ── 2. Service reachable? ────────────────────────────────────────────────────

def ollama_reachable() -> bool:
    try:
        urlopen(f'{OLLAMA_API}/api/tags', timeout=3)
        return True
    except URLError:
        return False


def start_ollama():
    info('Ollama service not running — starting in background...')
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


# ── 3. Model present? ────────────────────────────────────────────────────────

def model_present() -> bool:
    try:
        resp = urlopen(f'{OLLAMA_API}/api/tags', timeout=5)
        data = json.loads(resp.read())
        return any(MODEL in m.get('name', '') for m in data.get('models', []))
    except Exception:
        return False


def pull_model():
    print()
    print(f'  The {MODEL} embedding model is not installed (~274 MB download).')
    print( '  It is required for semantic search.')
    if not ask(f'Pull {MODEL} now?'):
        print()
        err(f'{MODEL} not pulled. To pull manually:')
        print(f'    ollama pull {MODEL}', file=sys.stderr)
        sys.exit(1)
    print()
    ret = subprocess.run(['ollama', 'pull', MODEL])
    if ret.returncode != 0:
        err(f'Failed to pull {MODEL}. Try manually: ollama pull {MODEL}')
        sys.exit(1)
    ok(f'{MODEL} ready.')


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print('Checking Ollama prerequisites...')

    if not ollama_installed():
        install_ollama()
    else:
        ok('ollama binary found.')

    if not ollama_reachable():
        start_ollama()
    else:
        ok('Ollama service reachable.')

    if not model_present():
        pull_model()
    else:
        ok(f'{MODEL} model present.')

    print('Ollama ready.\n')


if __name__ == '__main__':
    main()
