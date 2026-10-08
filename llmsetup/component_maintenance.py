"""Conservative, individually selectable host maintenance modules for Debian 13.

All components are opt-in. No filesystem formatting, unexpected public listeners,
off-site account enrollment, or automatic restart of unhealthy services.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .core import CONF_DIR, ROOT_DIR, STATE_DIR, SetupError, ensure_dir, stable_secret
from .component_base import managed, unit, model_root

BACKUP_SOURCES = ('/etc/llm-postinstall', '/var/lib/llm-postinstall', '/etc/cockpit')
KNOWN_UNITS = ('llm-ollama.service', 'llm-webui.service', 'llm-llama.service',
               'llm-codeserver.service', 'llm-filebrowser.service',
               'llm-jupyterlab.service', 'llm-novnc-vnc.service',
               'llm-novnc.service', 'cockpit.socket')


def hardware_health(r, cfg, ui):
    """Install Debian hardware tools and save a read-only, on-demand baseline."""
    r.apt('smartmontools', 'nvme-cli', 'lm-sensors')
    report = [managed('NVMe, SMART and temperature report (non-destructive)'),
              'Collected: ' + datetime.now(timezone.utc).isoformat()]
    for cmd in (['nvme', 'list'], ['smartctl', '--scan-open'], ['sensors']):
        result = r.run(cmd, capture=True, check=False, timeout=25)
        report.append('\\n$ ' + ' '.join(cmd) + '\\n' + result.stdout[:15000])
    out = Path('/var/log/llm-postinstall/hardware-health.txt')
    r.write(out, '\\n'.join(report) + '\\n', mode=0o600)
    print('Hardware report: ' + str(out))
    print('For actual SSD self-tests inspect nvme smart-log /dev/nvme0 and /dev/nvme1 manually.')


def cockpit_storage(r, cfg, ui):
    """Add Debian-supported Cockpit storage and package update views."""
    if not Path('/etc/systemd/system/cockpit.socket.d/llm-postinstall.conf').is_file():
        raise SetupError('Install and secure Cockpit before cockpit_storage')
    r.apt('cockpit-storaged', 'cockpit-packagekit')
    print('Storage and package updates pages added to existing Cockpit; no disk changed.')


def developer_tools(r, cfg, ui):
    """Debian-curated CLI tools. uv binary remains managed by existing webui module."""
    r.apt('ripgrep', 'fd-find', 'fzf', 'lazygit', 'zoxide', 'git', 'curl')
    print('CLI tools ready. Debian names fd-find binary fdfind. No shell config changed.')
    print('uv is installed via existing native WebUI prerequisites; no curl|sh executed here.')


def zram(r, cfg, ui):
    """Install Debian's own zram defaults; no manual swapoff or disk swap changes."""
    r.apt('zram-tools')
    if not Path('/etc/default/zramswap').is_file():
        raise SetupError('zram-tools did not install /etc/default/zramswap')
    r.run(['systemctl', 'enable', '--now', 'zramswap.service'])
    print('Debian zramswap enabled; original /etc/default/zramswap preserved unchanged.')


def validate_backup_repo(raw, sources=BACKUP_SOURCES):
    """Only a pre-existing external/NAS-mounted local directory; never a source subtree."""
    if not isinstance(raw, str) or not raw.startswith('/'):
        raise SetupError('backup_repository must be an absolute local directory (mounted NAS recommended)')
    p = Path(raw)
    if '..' in p.parts or p.is_symlink() or not p.is_dir():
        raise SetupError('backup_repository must exist and must not be a symlink')
    canonical = p.resolve(strict=True)
    if not str(canonical).startswith(('/mnt/', '/media/', '/srv/backups/')):
        raise SetupError('Backups must use /mnt, /media, or /srv/backups, not the system/model root')
    if not canonical.is_mount() and not any(parent.is_mount() and parent != Path('/')
                                        for parent in (canonical, *canonical.parents)):
        raise SetupError('Backup target is not on a separately mounted filesystem')
    for source in sources:
        s = Path(source).resolve(strict=False)
        if canonical == s or canonical in s.parents or s in canonical.parents:
            raise SetupError('Backup target overlaps a source directory')
    return canonical


def backup_restore(r, cfg, ui):
    """Restic CLI always; schedule only after explicit repository and existing repo validation."""
    r.apt('restic')
    repository = cfg.get('backup_repository')
    if not repository:
        print('Restic installed. Configure backup_repository to an external/NAS mount to enable a timer.')
        print('No repository initialized, backup schedule enabled, or secret generated.')
        return
    dest = validate_backup_repo(repository)
    # Administrator must initialize an encrypted repo with this generated credential.
    password_file = CONF_DIR / 'restic-password'
    stable_secret(password_file, length=42)
    env = dict(os.environ, RESTIC_PASSWORD_FILE=str(password_file),
               RESTIC_REPOSITORY=str(dest))
    probe = r.run(['restic', 'snapshots', '--json'], env=env, capture=True, check=False, timeout=60)
    if probe.returncode:
        print('Restic password stored at ' + str(password_file))
        raise SetupError('Restic repository not initialized or inaccessible: initialize it manually with RESTIC_PASSWORD_FILE and RESTIC_REPOSITORY')
    available = [p for p in BACKUP_SOURCES if Path(p).is_dir()]
    if not available:
        raise SetupError('No configured directories exist for backup')
    from .component_base import unit as _unit
    # The unit is oneshot and stays disabled; only the timer is enabled.
    body = managed('''[Unit]
Description=Encrypted backup of UM780 configuration and service state
[Service]
Type=oneshot
Environment=RESTIC_PASSWORD_FILE=''' + str(password_file) + '''
Environment=RESTIC_REPOSITORY=''' + str(dest) + '''
ExecStart=/usr/bin/restic backup --tag um780-postinstall ''' + ' '.join(available) + '''
NoNewPrivileges=yes
PrivateTmp=yes
''')
    r.write('/etc/systemd/system/llm-backup.service', body)
    r.write('/etc/systemd/system/llm-backup.timer',
            managed('''[Unit]
Description=Daily UM780 configuration backup
[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30m
Unit=llm-backup.service
[Install]
WantedBy=timers.target
'''))
    r.run(['systemd-analyze', 'verify', '/etc/systemd/system/llm-backup.service',
           '/etc/systemd/system/llm-backup.timer'])
    r.run(['systemctl', 'daemon-reload'])
    r.run(['systemctl', 'enable', '--now', 'llm-backup.timer'])
    print('Daily encrypted configuration backups enabled. RESTORE TEST REQUIRED before relying on them.')
    print('Check snapshots with: sudo restic -r ' + str(dest) + ' snapshots')


WATCHDOG_CODE = r'''# Managed by debian-llm-postinstall
"""Read-only service monitor. No auto-restart; reports anomalies via journal."""
import subprocess
import sys

UNITS = %r
bad = []
for unit in UNITS:
    enabled = subprocess.run(['systemctl', 'is-enabled', '--quiet', unit],
                             check=False, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL).returncode == 0
    if not enabled:
        continue
    active = subprocess.run(['systemctl', 'is-active', '--quiet', unit],
                            check=False, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode == 0
    if not active:
        bad.append(unit)
if bad:
    print('UM780 WATCHDOG ALERT: enabled services inactive: ' + ', '.join(bad), flush=True)
    sys.exit(1)
print('UM780 WATCHDOG: enabled tracked services active', flush=True)
''' % (KNOWN_UNITS,)


def service_watchdog(r, cfg, ui):
    """Journal warning and systemd timer; no surprise restarts or external webhook."""
    path = Path('/usr/local/libexec/um780-service-check.py')
    r.write(path, WATCHDOG_CODE, mode=0o644)
    r.write('/etc/systemd/system/llm-service-watchdog.service',
            managed('''[Unit]
Description=UM780 non-destructive service status monitor
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/libexec/um780-service-check.py
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
'''))
    r.write('/etc/systemd/system/llm-service-watchdog.timer',
            managed('''[Unit]
Description=Periodic UM780 service status checks
[Timer]
OnBootSec=3m
OnUnitActiveSec=5m
Unit=llm-service-watchdog.service
[Install]
WantedBy=timers.target
'''))
    r.run(['systemd-analyze', 'verify', '/etc/systemd/system/llm-service-watchdog.service',
           '/etc/systemd/system/llm-service-watchdog.timer'])
    r.run(['systemctl', 'daemon-reload'])
    r.run(['systemctl', 'enable', '--now', 'llm-service-watchdog.timer'])
    print('Service watchdog enabled (journal alerts only; NO automatic restart or notifications).')


def llm_benchmark(r, cfg, ui):
    """Actual llama.cpp tokens/second; skip safely if no GGUF or llama-bench binary."""
    bench = ROOT_DIR / 'llama.cpp/build/bin/llama-bench'
    if not bench.is_file() or not os.access(bench, os.X_OK):
        raise SetupError('Build llama.cpp with its llama-bench executable before benchmarking')
    model = str(cfg.get('llama_model_path') or '')
    if not model:
        env = CONF_DIR / 'llama.env'
        if env.is_file() and not env.is_symlink():
            model = next((x.partition('=')[2] for x in env.read_text().splitlines()
                          if x.startswith('LLAMA_MODEL=')), '')
    from .core import safe_model
    if not model or not safe_model(model, str(Path(model_root(cfg)) / 'gguf')):
        raise SetupError('Choose an existing GGUF within the managed gguf directory to benchmark')
    report = [managed('llama-bench inference performance evidence'),
              'UTC: ' + datetime.now(timezone.utc).isoformat(), 'GGUF: ' + model]
    for layers in (0, 99):
        cmd = [str(bench), '-m', model, '-ngl', str(layers), '-p', '128', '-n', '32', '-r', '2']
        outcome = r.run(cmd, capture=True, check=False, timeout=900)
        report.extend(['', 'GPU layers: ' + str(layers), 'returncode: ' + str(outcome.returncode),
                       outcome.stdout[:25000]])
    output = Path('/var/log/llm-postinstall/llm-benchmark.txt')
    r.write(output, '\\n'.join(report) + '\\n', mode=0o600)
    print('Benchmark report saved to ' + str(output) + '; inspect CPU/Vulkan numbers and logs.')
