"""Safe, additive configuration of ami3go/bookmarks for installed UM780 apps.

No services/terminals are started by this module. Only trusted local URLs and
per-user, on-demand ttyd launcher definitions are generated. Existing bookmarks,
their order, preferences, launchers, and history are never overwritten or removed.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from datetime import datetime, timezone

from .core import SetupError

BOOKMARKS_PACKAGE = Path('/usr/share/cockpit/cockpit-bookmarks/manifest.json')
BOOKMARKS_CONFIG = Path('/etc/cockpit/cockpit-bookmarks.json')
LOCK_PATH = Path('/run/lock/um780-bookmarks-sync.lock')
BACKUP_DIR = Path('/var/backups/llm-postinstall')
MAX_BYTES = 1048576   # Cockpit Bookmarks upstream configuration write budget
MAX_READ_BYTES = MAX_BYTES * 4
MANAGED_BY = 'um780-postinstall'
WEB_GROUP = 'UM780 Web Apps'
TERM_GROUP = 'Applications'
TTDY_BINARY = Path('/opt/llm-stack/bin/ttyd')

# A web link is useful only in a browser that has the corresponding SSH -L
# tunnel. 127.0.0.1 refers to the browser/client, NOT the server.
WEB_APPS = (
    ('webui', 'Open WebUI', 3000, 'http://127.0.0.1:3000/', '🤖',
     '/etc/systemd/system/llm-webui.service', 'Ollama chat interface'),
    ('codeserver', 'code-server', 8443, 'http://127.0.0.1:8443/', '💻',
     '/etc/systemd/system/llm-codeserver.service', 'Browser-based IDE'),
    ('filebrowser', 'FileBrowser Quantum', 8082, 'http://127.0.0.1:8082/', '📁',
     '/etc/systemd/system/llm-filebrowser.service', 'Server file manager'),
    ('jupyterlab', 'JupyterLab', 8888, 'http://127.0.0.1:8888/lab', '🧪',
     '/etc/systemd/system/llm-jupyterlab.service', 'Token-authenticated Python notebooks'),
    ('novnc', 'noVNC Desktop', 6080, 'http://127.0.0.1:6080/vnc.html', '🖥️',
     '/etc/systemd/system/llm-novnc.service', 'Activate VNC and noVNC first'),
)

# These become real Cockpit Bookmarks "Applications" entries with the existing
# gotty-launcher compatibility type and ttyd provider; they do not auto-start.
TERM_APPS = (
    ('fish', 'Fish Shell', 'fish', '🐟', 47200),
    ('btop', 'btop', 'btop', '📊', 47201),
    ('mc', 'Midnight Commander', 'mc', '📂', 47202),
    ('aoe', 'Agent of Empires', 'aoe', '🏛️', 47203),
)


def config_template():
    return {'schemaVersion': 2, 'title': 'Cockpit Bookmarks',
            'subtitle': 'Services hosted on this mini PC', 'eyebrow': 'Mini PC',
            'showEyebrow': True, 'showHeader': True, 'showTitle': True,
            'showSearch': True, 'displayMode': 'cards',
            'groupOrder': [], 'services': [], 'history': []}


def _read_config(path=BOOKMARKS_CONFIG):
    path = Path(path)
    if path.is_symlink():
        raise SetupError('Refusing to follow a symlinked Cockpit Bookmarks config')
    if not path.exists():
        return config_template(), None, None
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_READ_BYTES:
        raise SetupError('Cockpit Bookmarks config must be a normal JSON file below 4 MiB')
    raw = path.read_bytes()
    try:
        config = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise SetupError('Invalid Cockpit Bookmarks JSON; leaving it unchanged') from exc
    if not isinstance(config, dict) or not isinstance(config.get('services'), list):
        raise SetupError('Unsupported Cockpit Bookmarks configuration; services array required')
    version = config.get('schemaVersion', 0)
    if type(version) is not int or version > 2 or version < 0:
        raise SetupError('Unknown Cockpit Bookmarks schema; refusing to downgrade/mutate it')
    # Upstream migrates v0/v1 to v2 at UI load. Do not change their existing fields.
    if not all(isinstance(service, dict) for service in config['services']):
        raise SetupError('Malformed service entry; config unchanged')
    return config, raw, info


def _web_entries(exists):
    for key, name, port, url, icon, unit, description in WEB_APPS:
        if exists(unit):
            yield {'id': 'um780-' + key, 'um780ManagedBy': MANAGED_BY,
                   'name': name, 'description': description +
                   '; requires SSH -L ' + str(port) + ':127.0.0.1:' + str(port) +
                   ' on the browser client',
                   'url': url, 'icon': icon, 'group': WEB_GROUP,
                   'tags': ['um780', 'web', 'ssh-tunnel'], 'statusCheck': False}


def _used_ports(services):
    used = set()
    for item in services:
        if not isinstance(item, dict):
            continue
        for field in ('gottyLauncher', 'applicationLauncher'):
            launcher = item.get(field)
            if isinstance(launcher, dict):
                try:
                    port = int(launcher.get('port', 0))
                    if 0 < port <= 65535: used.add(port)
                except (TypeError, ValueError):
                    pass
    return used


def _terminal_entries(exists, command_exists, services):
    if not exists(str(TTDY_BINARY)):
        return
    reserved = _used_ports(services)
    for key, name, command, icon, preferred in TERM_APPS:
        if not command_exists(command):
            continue
        port = preferred
        while port in reserved and port <= 47299:
            port += 1
        if port > 47299:
            raise SetupError('No free Bookmarks terminal launcher port in 47200..47299')
        reserved.add(port)
        id_ = 'um780-' + key
        yield {'id': id_, 'um780ManagedBy': MANAGED_BY,
               'name': name, 'description': 'On-demand local ttyd launcher for ' + command +
               '; requires SSH tunnel for TCP ' + str(port),
               'type': 'gotty-launcher', 'integration': 'ttyd',
               'url': 'http://127.0.0.1:' + str(port) + '/cb-gotty-' + id_ + '/',
               'group': TERM_GROUP, 'icon': icon,
               'tags': ['um780', 'terminal', 'ttyd', command],
               'gottyLauncher': {'provider': 'ttyd',
                                 'binary': str(TTDY_BINARY), 'command': command,
                                 'args': [], 'port': port, 'address': '127.0.0.1',
                                 'autoStopMinutes': 30}}


def desired_entries(exists=None, command_exists=None, services=()):
    """Pure discovery with injectable probes for deterministic tests."""
    exists = exists or (lambda path: Path(path).is_file())
    command_exists = command_exists or (lambda cmd: shutil.which(cmd) is not None)
    return list(_web_entries(exists)) + list(_terminal_entries(exists, command_exists, services))


def merge_bookmarks(config, new_entries):
    """Return a new config and additions. No updates to pre-existing bookmarks."""
    items = list(config['services'])
    ids = {str(s.get('id', '')) for s in items}
    names = {str(s.get('name', '')).strip().casefold() for s in items}
    urls = {str(s.get('url', '')).strip().rstrip('/').casefold() for s in items}
    added = []
    for entry in new_entries:
        if (entry['id'] in ids or entry['name'].strip().casefold() in names or
                entry['url'].strip().rstrip('/').casefold() in urls):
            continue
        items.append(entry)
        added.append(entry['name'])
        ids.add(entry['id'])
        names.add(entry['name'].strip().casefold())
        urls.add(entry['url'].strip().rstrip('/').casefold())
    if not added:
        return config, []
    result = {**config, 'services': items}
    existing = result.get('groupOrder')
    groups = list(existing) if isinstance(existing, list) else []
    for entry in items[len(config['services']):]:
        if entry['group'] not in groups:
            groups.append(entry['group'])
    result['groupOrder'] = groups
    # Keep user-managed history untouched: the external writer makes separate timestamped backups.
    return result, added


def _atomic_save(path, config, old_raw, original_stat, backup_dir=BACKUP_DIR):
    path, backup_dir = Path(path), Path(backup_dir)
    data = (json.dumps(config, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    if len(data) > MAX_BYTES:
        raise SetupError('Adding Bookmarks would exceed its 1 MiB config budget; nothing written')
    if path.is_symlink():
        raise SetupError('Cockpit Bookmarks config became a symlink')
    # Optimistic read-back check for external editors, not a substitute for the Cockpit file tag.
    current_raw = path.read_bytes() if path.exists() else None
    if current_raw != old_raw:
        raise SetupError('Bookmarks config changed during sync; rerun rather than overwrite')
    path.parent.mkdir(parents=True, exist_ok=True)
    if old_raw is not None:
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = backup_dir / ('cockpit-bookmarks-' + timestamp + '.json')
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as out: out.write(old_raw)
    fd, temp = tempfile.mkstemp(prefix='.um780-bookmarks-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
            if original_stat is not None:
                os.fchmod(out.fileno(), stat.S_IMODE(original_stat.st_mode))
                if os.geteuid() == 0:
                    os.fchown(out.fileno(), original_stat.st_uid, original_stat.st_gid)
            else:
                os.fchmod(out.fileno(), 0o644)
        if path.is_symlink() or (path.read_bytes() if path.exists() else None) != old_raw:
            raise SetupError('Concurrent Bookmarks config change detected; refusing overwrite')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    return len(data)


def sync_bookmarks(r=None, cfg=None, ui=None, *, config_path=None, package_path=None,
                   exists=None, command_exists=None, backup_dir=None):
    """Merge installed apps into Cockpit Bookmarks without starting applications.

    Returns names added; package must already be installed. No installation
    activity happens for '--plan' or '--health'; call only from apply.
    """
    config_path = Path(config_path or BOOKMARKS_CONFIG)
    package_path = Path(package_path or BOOKMARKS_PACKAGE)
    if not package_path.is_file() or package_path.is_symlink():
        raise SetupError('Cockpit Bookmarks is not installed; install cockpit_bookmarks first')
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(LOCK_PATH, flags, 0o600)
    with os.fdopen(fd, 'r+', encoding='utf-8') as lock:
        info = os.fstat(lock.fileno())
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_nlink != 1 or (os.geteuid() == 0 and info.st_uid != 0)):
            raise SetupError('Insecure Cockpit Bookmarks sync lock file')
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current, old, info = _read_config(config_path)
        entries = desired_entries(exists=exists, command_exists=command_exists, services=current['services'])
        merged, added = merge_bookmarks(current, entries)
        if added:
            length = _atomic_save(config_path, merged, old, info, backup_dir=backup_dir or BACKUP_DIR)
            if r is not None: r.logger.info('COCKPIT BOOKMARKS: added %s; config bytes %d', ', '.join(added), length)
            print('Bookmarks added: ' + ', '.join(added))
        else:
            print('Cockpit Bookmarks already up to date; no existing bookmarks changed')
        return added


def bookmark_sync(r, cfg, ui):
    """Explicit rescan module (auto-sync also runs after successful installs)."""
    return sync_bookmarks(r, cfg, ui)


def auto_sync_bookmarks(r, cfg, chosen):
    """Post-install hook. Skip when plugin is absent, disabled, or explicitly run."""
    if cfg.get('auto_bookmarks', True) is False or 'bookmark_sync' in chosen:
        return []
    if not BOOKMARKS_PACKAGE.is_file():
        return []
    return sync_bookmarks(r, cfg, None)
