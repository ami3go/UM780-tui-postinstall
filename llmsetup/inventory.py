"""Read-only installed/configured/running inventory for all installer components.

Inventory is evidence-based rather than a version/upgrade authority. Never use
inventory status alone to skip a safety-sensitive installer or authorize disk
mounting. No files are written, services started, or secrets printed.
"""
from __future__ import annotations

from dataclasses import dataclass
import glob
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

from .core import CONF_DIR, ROOT_DIR
from .install_stages import ORDER

CONFIG_ROOT = Path('/etc/llm-postinstall')
UNIT_ROOT = Path('/etc/systemd/system')

# Action-only modules cannot accurately be called "installed software".
ACTIONS = {'preflight', 'config_snapshot', 'models', 'benchmarks',
           'llm_benchmark', 'secure_ingress', 'ups_wol', 'bookmark_sync'}

# Presence evidence. Multiple checks for a module are ALL required unless
# declared via a glob / alternate selector. Package evidence is local dpkg only.
INSTALL = {
    'preflight': ('file:/var/log/llm-postinstall/preflight.txt',),
    'config_snapshot': ('glob:/var/backups/llm-postinstall/snapshots/um780-config-*.tar.gz',),
    'base': ('bin:git', 'bin:python3', 'package:openssh-server'),
    'storage': ('dir:/var/lib/llm-stack/models|/srv/llm-data/models',),
    'vulkan': ('package:mesa-vulkan-drivers', 'bin:vulkaninfo'),
    'llama': ('file:/opt/llm-stack/llama.cpp/build/bin/llama-server',),
    'ollama': ('file:/opt/llm-stack/ollama/current/bin/ollama',),
    'webui': ('file:/opt/llm-stack/open-webui/venv/bin/open-webui',),
    'models': ('file:/usr/local/bin/ollama',),
    'cockpit': ('package:cockpit',),
    'cockpit_storage': ('package:cockpit-storaged', 'package:cockpit-packagekit'),
    'cockpit_ghsync': ('file:/usr/share/cockpit/ghsync/manifest.json',),
    'cockpit_bookmarks': ('file:/usr/share/cockpit/cockpit-bookmarks/manifest.json',),
    'cockpit_status': ('file:/usr/share/cockpit/um780-status/manifest.json',
                       'file:/usr/share/cockpit/um780-status/status.js'),
    'filebrowser': ('glob:/opt/llm-stack/filebrowser-quantum/*/filebrowser',),
    'codeserver': ('bin:code-server',),
    'tailscale': ('bin:tailscale', 'package:tailscale'),
    'updates': ('package:unattended-upgrades',),
    'benchmarks': ('bin:sysbench', 'bin:vulkaninfo'),
    'fish': ('bin:fish',),
    'btop': ('bin:btop',),
    'mc': ('bin:mc',),
    'ttyd': ('file:/opt/llm-stack/bin/ttyd',),
    'agent_of_empires': ('file:/opt/llm-stack/bin/aoe',),
    'jupyterlab': ('bin:jupyter-lab',),
    'vnc': ('bin:tigervncserver',),
    'novnc': ('package:novnc', 'package:websockify', 'bin:tigervncserver'),
    'bookmark_sync': ('file:/usr/share/cockpit/cockpit-bookmarks/manifest.json',),
    'hardware_health': ('bin:nvme', 'bin:smartctl', 'bin:sensors'),
    'backup_restore': ('bin:restic',),
    'service_watchdog': ('file:/usr/local/libexec/um780-service-check.py',),
    'developer_tools': ('bin:rg', 'bin:fdfind', 'bin:fzf', 'bin:lazygit', 'bin:zoxide'),
    'llm_benchmark': ('file:/opt/llm-stack/llama.cpp/build/bin/llama-bench',),
    'zram': ('package:zram-tools',),
    'opencode': ('file:/opt/llm-stack/bin/opencode',),
    'llama_swap': ('file:/opt/llm-stack/bin/llama-swap',),
    'uptime_kuma': ('file:/opt/llm-stack/uptime-kuma/server/server.js',),
    'secure_ingress': ('bin:tailscale',),
    'ups_wol': ('file:/opt/llm-stack/cockpit-ups-wol/install.sh',),
}

RUNTIME_UNITS = {
    'base': 'ssh.service',
    'ollama': 'llm-ollama.service', 'llama': 'llm-llama.service',
    'webui': 'llm-webui.service', 'cockpit': 'cockpit.socket',
    'codeserver': 'llm-codeserver.service',
    'filebrowser': 'llm-filebrowser.service', 'tailscale': 'tailscaled.service',
    'updates': 'apt-daily-upgrade.timer', 'jupyterlab': 'llm-jupyterlab.service',
    'novnc': 'llm-novnc.service', 'service_watchdog': 'llm-service-watchdog.timer',
    'backup_restore': 'llm-backup.timer', 'zram': 'zramswap.service',
    'uptime_kuma': 'llm-uptime-kuma.service',
}

# Exact generated configuration units. A unit file is NOT proof of runtime or
# authentication. Service-template modules can be configured while disabled.
UNIT_CONFIG = {
    'ollama': ('llm-ollama.service',),
    'llama': ('llm-llama.service',),
    'webui': ('llm-webui.service',),
    'filebrowser': ('llm-filebrowser.service',),
    'codeserver': ('llm-codeserver.service',),
    'jupyterlab': ('llm-jupyterlab.service',),
    'ttyd': ('llm-ttyd.service',),
    'vnc': ('llm-vnc@.service',),
    'novnc': ('llm-novnc.service', 'llm-novnc-vnc.service'),
    'service_watchdog': ('llm-service-watchdog.service', 'llm-service-watchdog.timer'),
    'backup_restore': ('llm-backup.service', 'llm-backup.timer'),
    'uptime_kuma': ('llm-uptime-kuma.service',),
}

# No reliable, safe method to determine whether a particular *normal user* has
# authenticated or initialized these tools. Expose uncertainty explicitly.
PERSONAL_SETUP = {'opencode', 'agent_of_empires', 'vnc', 'ups_wol'}


@dataclass(frozen=True)
class ComponentState:
    component: str
    installed: bool | None
    configured: bool | None
    running: bool | None
    details: str

    @property
    def status(self):
        if self.component in ACTIONS and self.component not in ('models', 'ups_wol'):
            return ('ACTION DONE' if self.configured is True
                    else 'ACTION PENDING' if self.configured is False else 'ACTION UNKNOWN')
        if self.installed is None:
            return 'UNVERIFIED'
        if not self.installed:
            return 'NOT INSTALLED'
        if self.configured is None:
            return 'INSTALLED / SETUP UNVERIFIED'
        return 'INSTALLED + CONFIGURED' if self.configured else 'INSTALLED ONLY'

    @property
    def short(self):
        return {
            'ACTION DONE': 'DONE', 'ACTION PENDING': 'PENDING',
            'ACTION UNKNOWN': 'UNKNOWN', 'UNVERIFIED': 'UNKNOWN',
            'NOT INSTALLED': 'MISSING', 'INSTALLED ONLY': 'INSTALLED',
            'INSTALLED / SETUP UNVERIFIED': 'UNVERIFIED',
            'INSTALLED + CONFIGURED': 'CONFIGURED',
        }[self.status]

    def as_dict(self):
        return {'component': self.component, 'status': self.status,
                'installed': self.installed, 'configured': self.configured,
                'running': self.running, 'details': self.details}


class LocalProbe:
    """Subprocesses are read-only, local, argv-only, bounded and quiet."""
    def __init__(self):
        self._packages = {}

    def command(self, argv, timeout=3):
        try:
            p = subprocess.run(argv, capture_output=True, text=True,
                               timeout=timeout, check=False)
            return p.returncode == 0, p.stdout[:131072]
        except (OSError, subprocess.TimeoutExpired):
            return False, ''

    def binary(self, name):
        return shutil.which(name) is not None

    def file(self, path):
        return Path(path).is_file()

    def directory(self, path):
        return Path(path).is_dir()

    def match(self, pattern):
        p = Path(pattern)
        return any(Path(x).is_file() for x in glob.glob(pattern))

    def package(self, name):
        if name not in self._packages:
            ok, out = self.command(['dpkg-query', '-W',
                                    '-f=${db:Status-Status}', name])
            self._packages[name] = bool(ok and out.strip() == 'installed')
        return self._packages[name]

    def text(self, path):
        p = Path(path)
        try:
            if p.is_symlink() or not p.is_file() or p.stat().st_size > 131072:
                return None
            return p.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            return None

    def unit(self, name):
        return self.file(UNIT_ROOT / name)

    def enabled(self, name):
        return self.command(['systemctl', 'is-enabled', '--quiet', name])[0]

    def active(self, name):
        return self.command(['systemctl', 'is-active', '--quiet', name])[0]

    def model_names(self):
        """Read-only local Ollama tags endpoint; never contact an external host."""
        request = urllib.request.Request('http://127.0.0.1:11434/api/tags')
        try:
            with urllib.request.urlopen(request, timeout=1.2) as response:
                if response.status != 200 or response.headers.get('Content-Length', '0').isdigit() and int(response.headers.get('Content-Length', '0')) > 262144:
                    return None
                raw = response.read(262145)
            if len(raw) > 262144:
                return None
            data = json.loads(raw)
            models = data.get('models')
            if not isinstance(models, list):
                return None
            return {m.get('name') for m in models if isinstance(m, dict)
                    and isinstance(m.get('name'), str)}
        except (OSError, ValueError, TypeError):
            return None


def has_evidence(probe, token):
    kind, sep, value = token.partition(':')
    if not sep or not value:
        raise ValueError('Invalid inventory evidence token')
    if kind == 'bin':
        return probe.binary(value)
    if kind == 'file':
        return probe.file(value)
    if kind == 'dir':
        return any(probe.directory(x) for x in value.split('|'))
    if kind == 'glob':
        return probe.match(value)
    if kind == 'package':
        return probe.package(value)
    raise ValueError('Unsupported inventory evidence: ' + kind)


def _file_contains(probe, path, *words):
    txt = probe.text(path)
    return txt is not None and all(w in txt for w in words)


def _managed_unit(probe, name):
    return probe.unit(name) and _file_contains(
        probe, UNIT_ROOT / name, '# Managed by debian-llm-postinstall')


def _private_cockpit(probe):
    return _file_contains(probe,
                          '/etc/systemd/system/cockpit.socket.d/llm-postinstall.conf',
                          'ListenStream=127.0.0.1:9090')


def _valid_storage(probe):
    try:
        raw = probe.text('/etc/llm-postinstall/storage.json')
        if raw is None:
            return False
        root = json.loads(raw).get('model_storage')
        if root not in ('/var/lib/llm-stack/models', '/srv/llm-data/models'):
            return False
        if not probe.directory(root):
            return False
        return root != '/srv/llm-data/models' or Path('/srv/llm-data').is_mount()
    except (ValueError, TypeError, AttributeError):
        return False


def configured(name, probe, cfg, installed):
    """Configuration evidence; None means cannot assess safely without user context."""
    if name == 'preflight':
        return probe.file('/var/log/llm-postinstall/preflight.txt')
    if name == 'config_snapshot':
        return probe.match('/var/backups/llm-postinstall/snapshots/um780-config-*.tar.gz')
    if name == 'storage':
        return _valid_storage(probe)
    if name == 'base':
        return probe.enabled('ssh.service') and probe.directory('/etc/llm-postinstall')
    if name == 'vulkan':
        return probe.command(['vulkaninfo', '--summary'], timeout=5)[0] if installed else False
    if name == 'llama':
        return (_managed_unit(probe, 'llm-llama.service') and
                _file_contains(probe, CONFIG_ROOT / 'llama.env', 'LLAMA_MODEL=') and
                any(line.startswith('LLAMA_MODEL=') and line.partition('=')[2].strip()
                    for line in (probe.text(CONFIG_ROOT / 'llama.env') or '').splitlines()))
    if name == 'ollama':
        return (_managed_unit(probe, 'llm-ollama.service') and
                _file_contains(probe, CONFIG_ROOT / 'ollama.env', 'OLLAMA_HOST=127.0.0.1:11434'))
    if name == 'models':
        names = probe.model_names() if installed else None
        if names is None:
            return None
        return cfg.get('model', 'qwen2.5-coder:7b') in names
    if name == 'webui':
        return (_managed_unit(probe, 'llm-webui.service') and
                _file_contains(probe, CONFIG_ROOT / 'webui.env',
                               'OLLAMA_BASE_URL=http://127.0.0.1:11434', 'WEBUI_AUTH=True'))
    if name == 'cockpit':
        return _private_cockpit(probe) and probe.enabled('cockpit.socket')
    if name == 'cockpit_storage':
        return _private_cockpit(probe)
    if name == 'cockpit_status':
        return _private_cockpit(probe)
    if name == 'cockpit_bookmarks':
        raw = probe.text('/etc/cockpit/cockpit-bookmarks.json')
        if raw is None:
            return False
        try:
            return isinstance(json.loads(raw).get('services'), list)
        except (ValueError, AttributeError):
            return False
    if name == 'cockpit_ghsync':
        return probe.file('/etc/llm-postinstall/cockpit-ghsync.json')
    if name == 'filebrowser':
        return (_managed_unit(probe, 'llm-filebrowser.service') and
                _file_contains(probe, '/var/lib/filebrowser/config.yaml',
                               '127.0.0.1', '/var/lib/filebrowser/database.db'))
    if name == 'codeserver':
        return (_managed_unit(probe, 'llm-codeserver.service') and
                _file_contains(probe, '/etc/llm-postinstall/codeserver.env', 'PASSWORD=') and
                _file_contains(probe, UNIT_ROOT / 'llm-codeserver.service', '127.0.0.1:8443'))
    if name == 'tailscale':
        ok, raw = probe.command(['tailscale', 'status', '--json'])
        if not ok:
            return None
        try:
            return json.loads(raw).get('BackendState') == 'Running'
        except (ValueError, AttributeError):
            return None
    if name == 'updates':
        return (_file_contains(probe, '/etc/apt/apt.conf.d/52-llm-postinstall',
                               'Automatic-Reboot "false"') and
                probe.enabled('apt-daily-upgrade.timer'))
    if name == 'benchmarks':
        return probe.file('/var/log/llm-postinstall/benchmark-report.txt')
    if name in ('fish', 'btop', 'mc', 'developer_tools'):
        return installed  # no separate system-level setup is required
    if name == 'ttyd':
        return _managed_unit(probe, 'llm-ttyd.service')
    if name == 'agent_of_empires':
        return None  # user-owned tmux/agent configuration
    if name == 'jupyterlab':
        return (_managed_unit(probe, 'llm-jupyterlab.service') and
                _file_contains(probe, UNIT_ROOT / 'llm-jupyterlab.service',
                               '--ip=127.0.0.1', '--port=8888'))
    if name == 'vnc':
        return None  # user's actual VNC password/instance is not globally inspectable
    if name == 'novnc':
        return (all(_managed_unit(probe, unit) for unit in UNIT_CONFIG['novnc'])
                and probe.file('/etc/llm-postinstall/novnc-vnc-password')
                and probe.file('/var/lib/llmvnc/.config/tigervnc/passwd')
                and _file_contains(probe, UNIT_ROOT / 'llm-novnc.service',
                                   '127.0.0.1:6080', '127.0.0.1:5902'))
    if name == 'bookmark_sync':
        raw = probe.text('/etc/cockpit/cockpit-bookmarks.json')
        if raw is None:
            return False
        try:
            return any(x.get('um780ManagedBy') == 'um780-postinstall'
                       for x in json.loads(raw).get('services', [])
                       if isinstance(x, dict))
        except (ValueError, AttributeError, TypeError):
            return False
    if name == 'hardware_health':
        return probe.file('/var/log/llm-postinstall/hardware-health.txt')
    if name == 'backup_restore':
        return (all(_managed_unit(probe, x) for x in UNIT_CONFIG['backup_restore'])
                and probe.file('/etc/llm-postinstall/restic-password')
                and probe.enabled('llm-backup.timer'))
    if name == 'service_watchdog':
        return (all(_managed_unit(probe, x) for x in UNIT_CONFIG['service_watchdog'])
                and probe.enabled('llm-service-watchdog.timer'))
    if name == 'llm_benchmark':
        return probe.file('/var/log/llm-postinstall/llm-benchmark.txt')
    if name == 'zram':
        return probe.enabled('zramswap.service') and probe.file('/etc/default/zramswap')
    if name in PERSONAL_SETUP:
        return None
    if name == 'llama_swap':
        return False  # binary installed, but router config and launch remain manual
    if name == 'uptime_kuma':
        return (_managed_unit(probe, 'llm-uptime-kuma.service') and
                _file_contains(probe, UNIT_ROOT / 'llm-uptime-kuma.service',
                               'UPTIME_KUMA_HOST=127.0.0.1', 'UPTIME_KUMA_PORT=3001'))
    if name == 'secure_ingress':
        return None  # no persistent setup done by this readiness check
    raise ValueError('No configuration detector for ' + name)


def inspect(name, cfg=None, probe=None):
    """Return evidence-based status without modifying the host."""
    if name not in INSTALL:
        raise ValueError('Unknown module: ' + name)
    cfg = cfg or {}
    probe = probe or LocalProbe()
    try:
        installed = all(has_evidence(probe, key) for key in INSTALL[name])
        if name == 'models':
            # A model is data, not the Ollama binary; if API cannot answer,
            # presence is unknown rather than falsely marking model installed.
            names = probe.model_names() if installed else None
            installed = None if names is None else cfg.get('model', 'qwen2.5-coder:7b') in names
        configuration = configured(name, probe, cfg, installed)
        unit = RUNTIME_UNITS.get(name)
        active = probe.active(unit) if installed and unit else None
        description = {
            'models': 'Model tag checked via local Ollama API; unavailable API means unverified',
            'llama': 'Configured requires a selected GGUF path; GPU offload not verified',
            'cockpit_ghsync': 'Plugin deployment only; per-user GitHub login not verified',
            'cockpit_bookmarks': 'Configuration structure only; individual launchers not tested',
            'filebrowser': 'Model read-only permissions still require safety review',
            'webui': 'Service configuration only; first-run admin login not verified',
            'novnc': 'Unit/credential presence only; VNC password login not tested',
            'tailscale': 'Enrollment is checked; tailnet ACLs are not audited',
            'backup_restore': 'Timer configuration only; backup success/restore not verified',
            'ups_wol': 'Source checkout only; UPS hardware integration not verified',
            'llama_swap': 'Router executable only; no configured listener',
            'opencode': 'Per-user authentication not inspected',
            'agent_of_empires': 'Per-user agent sessions not inspected',
            'vnc': 'Per-user VNC password and enabled instance not inspected',
            'secure_ingress': 'Readiness only; no published Serve routes checked',
            'bookmark_sync': 'Generated entry presence; no browser-side links tested',
            'preflight': 'Report presence; earlier results may be stale',
            'config_snapshot': 'Archive presence; restore integrity not checked here',
            'llm_benchmark': 'Report presence; GPU performance not evaluated here',
        }.get(name, 'File/package and local configuration evidence only')
        return ComponentState(name, installed, configuration, active, description)
    except (OSError, ValueError, TypeError, PermissionError) as exc:
        return ComponentState(name, None, None, None,
                              'Unable to inspect safely: ' + type(exc).__name__)


def scan(names=ORDER, cfg=None, probe=None):
    """Inspect selected components, sharing cached local package queries."""
    shared = probe or LocalProbe()
    return {name: inspect(name, cfg=cfg, probe=shared) for name in names}


def render(states, *, selected=(), json_mode=False):
    if json_mode:
        print(json.dumps({name: state.as_dict() for name, state in states.items()}, indent=2))
        return
    selection = set(selected)
    print('=== INSTALLED / CONFIGURED SOFTWARE INVENTORY ===')
    print('Read-only evidence; configuration != successful login or healthy service.')
    for name, state in states.items():
        running = 'RUNNING' if state.running is True else (
            'STOPPED' if state.running is False else 'N/A')
        flag = '*' if name in selection else ' '
        print(f'{flag} {name:21} {state.short:12} {running:7} {state.status}')
    print('* = selected for installation by current config/filters.')
    print('UNVERIFIED means manual/per-user setup or offline model state cannot be proven.')
    print('No application, service, credential or network settings were changed.')
