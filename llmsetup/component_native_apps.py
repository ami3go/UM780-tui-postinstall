"""Optional native third-party applications, verified binaries and safe UPS preparation.

No curl | sh, Docker, unapproved LAN listeners, or automatic UPS arm.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tarfile

from .core import CONF_DIR, ROOT_DIR, SetupError, ensure_dir, stable_secret
from .component_base import managed, unit
from .component_llms import _install_uv
from .component_optional_tools import _release_binary, _atomic_binary_from_stream


def _verified_tar_command(r, repository, filename, binary_name, *, tag):
    """Verify upstream SHA256 before extracting exactly one regular executable."""
    base = ROOT_DIR / 'bin'
    ensure_dir(base)
    cache = ROOT_DIR / 'downloaded-releases'
    ensure_dir(cache)
    archive = _release_binary(r, repository, filename, cache / (tag + '-' + filename),
                              tag=tag, max_bytes=180 * 1024 * 1024)
    dest = base / binary_name
    if dest.is_symlink() or (dest.exists() and not dest.is_file()):
        raise SetupError('Refusing unmanaged executable path: ' + str(dest))
    with tarfile.open(archive, mode='r:gz') as tar:
        matches = [m for m in tar.getmembers() if m.name in (binary_name, './' + binary_name)]
        if len(matches) != 1 or not matches[0].isfile() or not 10000 < matches[0].size < 250*1024*1024:
            raise SetupError('Unexpected executable layout or size in verified release tarball')
        if not dest.exists():
            entry = tar.extractfile(matches[0])
            if entry is None:
                raise SetupError('Cannot read upstream executable')
            with entry:
                _atomic_binary_from_stream(entry, dest, max_bytes=250*1024*1024)
    if not os.access(dest, os.X_OK):
        raise SetupError('Installed executable is not runnable')
    return dest


def _symlink_cli(dest, name):
    link = Path('/usr/local/bin') / name
    if link.is_symlink():
        if link.resolve() != dest.resolve():
            raise SetupError('Conflicting existing command: ' + str(link))
    elif link.exists():
        raise SetupError('Existing command is unmanaged: ' + str(link))
    else:
        link.symlink_to(dest)
    return link


def opencode(r, cfg, ui):
    """OpenCode CLI only; credentials belong to normal Linux users."""
    r.apt('ca-certificates', 'tar', 'git')
    command = _verified_tar_command(r, 'anomalyco/opencode', 'opencode-linux-x64.tar.gz',
                                    'opencode', tag='v1.18.32')
    _symlink_cli(command, 'opencode')
    print('OpenCode installed. Run opencode and opencode auth as your normal user; no daemon.')


def llama_swap(r, cfg, ui):
    """Install verified llama-swap binary; do not generate model commands or start proxy."""
    r.apt('ca-certificates', 'tar')
    command = _verified_tar_command(r, 'mostlygeek/llama-swap',
                                    'llama-swap_262_linux_amd64.tar.gz',
                                    'llama-swap', tag='v262')
    _symlink_cli(command, 'llama-swap')
    print('llama-swap installed, not running. Configure verified GGUF paths and non-root llama-server commands.')
    print('Example (manual): llama-swap --config /path/to/config.yaml --listen 127.0.0.1:9292')


KUMA_TAG = '2.5.0'
KUMA_REPO = 'https://github.com/louislam/uptime-kuma.git'


def validate_kuma_node(raw):
    parts = str(raw).strip().lstrip('v').split('.')
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise SetupError('Cannot determine installed Node.js version')
    if (int(parts[0]), int(parts[1])) < (20, 4):
        raise SetupError('Uptime Kuma 2.x requires Node.js >= 20.4')


def uptime_kuma(r, cfg, ui):
    """Uptime Kuma native, non-root, private HTTP; first-run login manual."""
    r.apt('nodejs', 'npm', 'git', 'python3', 'build-essential')
    validate_kuma_node(r.run(['node', '--version'], capture=True).stdout)
    source = ROOT_DIR / 'uptime-kuma'
    if source.is_symlink():
        raise SetupError('Uptime Kuma source path is a symlink')
    if not source.exists():
        r.run(['git', 'clone', '--depth', '1', '--branch', KUMA_TAG, KUMA_REPO, str(source)])
    if not (source / '.git').is_dir():
        raise SetupError('Uptime Kuma source not a Git repository')
    head = r.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture=True).stdout.strip()
    tag_sha = r.run(['git', '-C', str(source), 'rev-list', '-n', '1', KUMA_TAG], capture=True).stdout.strip()
    if head != tag_sha or not re.fullmatch('[a-f0-9]{40}', head):
        raise SetupError('Uptime Kuma checkout does not match pinned release tag')
    remote = r.run(['git', '-C', str(source), 'remote', 'get-url', 'origin'], capture=True).stdout.strip()
    if remote != KUMA_REPO:
        raise SetupError('Unexpected Uptime Kuma checkout origin')
    # v2.5.1 has a known broken native install dependency manifest; pin v2.5.0.
    package = json.loads((source / 'package.json').read_text())
    if package.get('version') != KUMA_TAG or not package.get('dependencies'):
        raise SetupError('Uptime Kuma source has unexpected or empty runtime dependencies')
    if not (source / 'node_modules/dayjs').is_dir():
        r.run(['npm', 'ci', '--ignore-scripts=false', '--no-audit', '--no-fund'], cwd=str(source), timeout=1500)
        r.run(['npm', 'run', 'download-dist'], cwd=str(source), timeout=600)
    if not (source / 'server/server.js').is_file() or not (source / 'dist/index.html').is_file():
        raise SetupError('Uptime Kuma installation incomplete')
    r.account('uptimekuma')
    data = Path('/var/lib/uptimekuma/data')
    ensure_dir(data, user='uptimekuma', mode=0o700)
    unit(r, 'llm-uptime-kuma.service', f"""[Unit]
Description=Uptime Kuma native monitoring dashboard (first-run account setup)
After=network.target
[Service]
User=uptimekuma
WorkingDirectory={source}
Environment=UPTIME_KUMA_HOST=127.0.0.1
Environment=UPTIME_KUMA_PORT=3001
Environment=DATA_DIR={data}
ExecStart=/usr/bin/node {source}/server/server.js
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths={data}
[Install]
WantedBy=multi-user.target
""")
    print('Uptime Kuma on http://127.0.0.1:3001 (SSH forwarded). Create admin on first login.')
    print('Set monitors/notifications manually; no public listener or notification secret auto-added.')


WEBOLLAMA_TAG = 'v1.1.0'
WEBOLLAMA_SHA = '77069d30a3619aa76a51405801ab4c31222bd962'
WEBOLLAMA_REPO = 'https://github.com/dkruyt/webollama.git'
WEBOLLAMA_PORT = 5000
WEBOLLAMA_BINDS = ('127.0.0.1', '0.0.0.0')


def webollama_bind(cfg):
    bind = cfg.get('webollama_bind', '127.0.0.1')
    if bind not in WEBOLLAMA_BINDS:
        raise SetupError('webollama_bind must be 127.0.0.1 or 0.0.0.0')
    return bind


def webollama(r, cfg, ui):
    """Pinned WebOllama under gunicorn; upstream app.run() enables the Flask debugger."""
    bind = webollama_bind(cfg)
    r.apt('git', 'ca-certificates')
    uv = _install_uv(r)
    prefix = ROOT_DIR / 'webollama'
    source = prefix / 'src'
    if prefix.is_symlink() or source.is_symlink():
        raise SetupError('WebOllama path is a symlink')
    ensure_dir(prefix, mode=0o755)
    prefix.chmod(0o755)
    if not source.exists():
        r.run(['git', 'clone', '--depth', '1', '--branch', WEBOLLAMA_TAG, WEBOLLAMA_REPO, str(source)])
    if not (source / '.git').is_dir():
        raise SetupError('WebOllama source not a Git repository')
    head = r.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture=True).stdout.strip()
    if head != WEBOLLAMA_SHA:
        raise SetupError('WebOllama checkout does not match pinned release commit')
    remote = r.run(['git', '-C', str(source), 'remote', 'get-url', 'origin'], capture=True).stdout.strip()
    if remote != WEBOLLAMA_REPO:
        raise SetupError('Unexpected WebOllama checkout origin')
    venv = prefix / 'venv'
    gunicorn = venv / 'bin/gunicorn'
    if not gunicorn.is_file():
        env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(ROOT_DIR / 'uv-python'),
                   UV_PYTHON_PREFERENCE='managed')
        r.run([str(uv), 'python', 'install', '3.11'], env=env)
        r.run([str(uv), 'venv', '--python', '3.11', str(venv)], env=env)
        r.run([str(uv), 'pip', 'install', '--python', str(venv / 'bin/python'),
               '-r', str(source / 'requirements.txt'), 'gunicorn==26.2.0'], env=env)
    if not gunicorn.is_file():
        raise SetupError('gunicorn missing from WebOllama environment')
    r.account('webollama')
    secret = stable_secret(CONF_DIR / 'webollama-secret')
    env_changed = r.write(CONF_DIR / 'webollama.env', managed(f'''SECRET_KEY={secret}
OLLAMA_API_BASE=http://127.0.0.1:11434
'''), mode=0o600)
    unit(r, 'llm-webollama.service', f"""[Unit]
Description=WebOllama Ollama model manager (no authentication)
After=network.target llm-ollama.service
Wants=llm-ollama.service
[Service]
User=webollama
WorkingDirectory={source}
EnvironmentFile={CONF_DIR}/webollama.env
ExecStart={gunicorn} --chdir {source} --workers 1 --threads 8 --timeout 0 --no-control-socket --bind {bind}:{WEBOLLAMA_PORT} app:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
[Install]
WantedBy=multi-user.target
""", force_restart=env_changed)
    print(f'WebOllama on http://{bind}:{WEBOLLAMA_PORT}/ with NO login: anyone reaching it can pull/delete models.')
    if bind != '127.0.0.1':
        print('WARNING: listening on all interfaces by explicit webollama_bind; restrict with a firewall.')


UPS_REPO = 'https://github.com/ami3go/cockpit-ups-wol.git'


def ups_wol(r, cfg, ui):
    """Prepare reviewed UPS/WOL project; never arm or silently enroll a NUT UPS."""
    r.apt('git', 'ca-certificates')
    source = ROOT_DIR / 'cockpit-ups-wol'
    if source.is_symlink():
        raise SetupError('UPS/WOL checkout path is a symlink')
    if not source.exists():
        # Version is not pinned: source is for PREVIEW ONLY, not executed as root.
        r.run(['git', 'clone', '--depth', '1', UPS_REPO, str(source)])
    if not (source / 'install.sh').is_file() or not (source / '.git').is_dir():
        raise SetupError('Cockpit UPS/WOL source checkout incomplete')
    origin = r.run(['git', '-C', str(source), 'remote', 'get-url', 'origin'],
                   capture=True).stdout.strip()
    if origin != UPS_REPO:
        raise SetupError('Existing UPS/WOL checkout has unexpected origin')
    print('UPS/WOL source checkout prepared in ' + str(source))
    print('NOT INSTALLED OR ARMED: inspect UPS hardware and run ./install.sh --check before manual --tui.')
    print('Use monitor or dry-run mode until physical power-fail acceptance is complete.')


def secure_ingress(r, cfg, ui):
    """Preflight trusted Tailscale ingress; never publish a service automatically."""
    if not shutil.which('tailscale'):
        raise SetupError('Install optional tailscale module before secure_ingress')
    status = r.run(['tailscale', 'status', '--json'], capture=True, check=False, timeout=20)
    state = None
    if status.returncode == 0:
        try:
            state = json.loads(status.stdout).get('BackendState')
        except ValueError:
            pass
    if state != 'Running':
        raise SetupError('Tailscale is not enrolled; run sudo tailscale up manually')
    print('Tailscale identity is connected. No port or HTTPS ingress has been published.')
    print('Review tailscale serve --help to explicitly map an authenticated HTTPS name to ONE localhost app.')
    print('Cockpit and model APIs remain private; Tailscale identity policies must be reviewed first.')
