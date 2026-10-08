"""Audited command execution, service management, file writes and downloads."""
from __future__ import annotations
import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import subprocess
import tempfile
import urllib.request

OWNER_MARK = '# Managed by debian-llm-postinstall'
ROOT_DIR = Path('/opt/llm-stack')
CONF_DIR = Path('/etc/llm-postinstall')
STATE_DIR = Path('/var/lib/llm-postinstall')

class SetupError(RuntimeError):
    pass


def is_root() -> bool:
    return os.geteuid() == 0


def detect_target() -> list[str]:
    problems = []
    try:
        data = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        if data.get('ID', '').strip('"') != 'debian' or data.get('VERSION_ID', '').strip('"') != '13':
            problems.append('Requires Debian 13 (trixie)')
    except OSError:
        problems.append('Cannot identify operating system')
    if os.uname().machine != 'x86_64':
        problems.append('Installer currently supports x86_64 only')
    if Path('/.dockerenv').exists() or Path('/run/.containerenv').exists():
        problems.append('Bare-metal installer: container detected')
    if not Path('/run/systemd/system').exists():
        problems.append('systemd is not running as PID 1')
    if shutil.which('systemd-detect-virt'):
        for kind in ('--container', '--vm'):
            check = subprocess.run(['systemd-detect-virt', kind], capture_output=True, text=True)
            if check.returncode == 0 and check.stdout.strip() not in ('', 'none'):
                problems.append(f'Bare-metal target required; virtualization detected: {check.stdout.strip()}')
    return problems


class Runner:
    def __init__(self, log_path=None):
        if log_path is None:
            base = Path('/var/log/llm-postinstall') if is_root() else Path.home() / '.cache/llm-postinstall'
            base.mkdir(mode=0o700, parents=True, exist_ok=True)
            log_path = base / ('install-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.log')
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger('llmsetup.' + str(id(self)))
        self.logger.setLevel(logging.INFO)
        h = logging.FileHandler(self.log_path, encoding='utf-8')
        h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        self.logger.addHandler(h)
        os.chmod(self.log_path, 0o600)
        self.logger.propagate = False

    def run(self, cmd, *, cwd=None, env=None, secret=False, check=True, capture=False, timeout=None):
        if not isinstance(cmd, (list, tuple)) or not cmd:
            raise ValueError('argv list required, shell is forbidden')
        display = '[redacted: contains secret]' if secret else ' '.join(str(x) for x in cmd)
        self.logger.info('RUN %s', display)
        try:
            p = subprocess.run(cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.logger.error('COMMAND ERROR %s', type(exc).__name__)
            raise SetupError('Command failed: ' + ('[sensitive]' if secret else display)) from exc
        if not secret:
            self.logger.info('OUTPUT: %s', p.stdout[-30000:])
        if p.returncode and check:
            raise SetupError(f'Command exited {p.returncode}: {display}; see {self.log_path}')
        if not capture:
            print(('OK' if p.returncode == 0 else 'FAIL'), display)
        return p

    def write(self, path, content, *, mode=0o644, owned=True):
        path = Path(path)
        if owned and not content.startswith(OWNER_MARK):
            raise SetupError('Managed files must contain ownership header: ' + str(path))
        if path.is_symlink():
            raise SetupError('Refusing symlink target: ' + str(path))
        if path.exists():
            current = path.read_text()
            if current == content:
                if path.stat().st_mode & 0o777 != mode:
                    os.chmod(path, mode)
                return False
            if owned and not current.startswith(OWNER_MARK):
                raise SetupError('Refusing to overwrite unmanaged file: ' + str(path))
            backup_dir = Path('/var/backups/llm-postinstall')
            backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup = backup_dir / (path.name + '.' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
            shutil.copy2(path, backup)
            self.logger.info('BACKUP %s => %s', path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(temp, mode)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.logger.info('WRITE %s', path)
        return True

    def apt(self, *pkgs):
        self.run(['apt-get', 'install', '-y', '--no-install-recommends', *pkgs])

    def service(self, name, enable=True, restart=True):
        self.run(['systemctl', 'daemon-reload'])
        if enable:
            self.run(['systemctl', 'enable', name])
            self.run(['systemctl', 'restart' if restart else 'start', name])
        else:
            self.run(['systemctl', 'disable', '--now', name], check=False)

    def account(self, name, *, groups=()):
        try:
            pwd.getpwnam(name)
        except KeyError:
            self.run(['useradd', '--system', '--create-home', '--home-dir', '/var/lib/' + name,
                      '--shell', '/usr/sbin/nologin', name])
        for group in groups:
            # Debian normally provides these device groups; create only if absent.
            try: grp.getgrnam(group)
            except KeyError: self.run(['groupadd', '--system', group])
            self.run(['usermod', '-aG', group, name])

    def get_json(self, url):
        req = urllib.request.Request(url, headers={'User-Agent': 'debian-llm-postinstall/0.1', 'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    def download(self, url, digest, path, *, max_bytes=3 * 1024**3):
        from .assets import download
        return download(self, url, digest, path, max_bytes=max_bytes)



def ensure_dir(path, user=None, group=None, mode=0o755):
    path = Path(path)
    if path.is_symlink():
        raise SetupError('Directory symlink is not allowed: ' + str(path))
    if path.exists() and not path.is_dir():
        raise SetupError('Not a directory: ' + str(path))
    if not path.exists():
        path.mkdir(parents=True, mode=mode)
        os.chmod(path, mode)
        if user or group:
            os.chown(path, pwd.getpwnam(user).pw_uid if user else -1, grp.getgrnam(group).gr_gid if group else -1)
    return path


def stable_secret(path, length=36):
    import secrets
    path = Path(path)
    if path.exists():
        if path.is_symlink(): raise SetupError('Refusing symlinked secret path')
        if not path.is_file(): raise SetupError('Secret path is not a regular file')
        os.chmod(path, 0o600)
        return path.read_text().strip()
    ensure_dir(path.parent, mode=0o700)
    token = secrets.token_urlsafe(length)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f: f.write(token + '\n')
    return token


def safe_model(path, root):
    p = Path(path)
    r = Path(root)
    return (p.is_absolute() and p.suffix.lower() == '.gguf' and p.is_file()
            and not p.is_symlink() and not r.is_symlink() and r.resolve() in p.resolve().parents)

from .assets import sha256, github_asset, install_release_asset
