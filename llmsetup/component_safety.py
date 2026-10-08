"""Optional safe preflight, private config snapshots, and Cockpit status plugin.

Snapshots cover installer config and owned systemd units only. No package or
database rollback is implied. Restoring always requires explicit typed consent.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import tarfile
import tempfile

from .core import CONF_DIR, ROOT_DIR, SetupError, detect_target, ensure_dir

SNAPSHOT_ROOT = Path('/var/backups/llm-postinstall/snapshots')
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
STATUS_ASSETS = Path(__file__).resolve().parent / 'cockpit_status_assets'
STATUS_DEST = Path('/usr/share/cockpit/um780-status')
VERSION = 1

def _allowed_snapshot_path(path):
    """Strict policy shared by writer and manual restoration."""
    if not isinstance(path, str) or not path.startswith('/'):
        return False
    p = Path(path)
    if '..' in p.parts or len(path) > 230:
        return False
    if p.parent == CONF_DIR:
        return re.fullmatch(r'[A-Za-z0-9_.-]+', p.name) is not None
    if str(p) == '/etc/cockpit/cockpit-bookmarks.json':
        return True
    if p.parent == Path('/etc/systemd/system'):
        return re.fullmatch(r'llm-[A-Za-z0-9_.@-]+\.(service|timer)', p.name) is not None
    return False


def _collect_snapshot_paths():
    paths = []
    for parent in (CONF_DIR, Path('/etc/systemd/system')):
        if parent.is_dir() and not parent.is_symlink():
            for f in sorted(parent.iterdir()):
                if not _allowed_snapshot_path(str(f)):
                    continue  # Debian systemd contains many unrelated unit-alias symlinks.
                if f.is_symlink():
                    raise SetupError('Refusing installer-owned configuration symlink: ' + str(f))
                if f.is_file():
                    paths.append(f)
    bookmarks = Path('/etc/cockpit/cockpit-bookmarks.json')
    if bookmarks.is_symlink():
        raise SetupError('Refusing symlinked Cockpit Bookmarks config')
    if bookmarks.is_file():
        paths.append(bookmarks)
    return paths


def _hash(blob):
    return hashlib.sha256(blob).hexdigest()


def build_snapshot(path, files):
    """Write an exclusive root-only tar file, with SHA and mode manifest."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise SetupError('Refusing existing snapshot: ' + str(path))
    collected = []
    total = 0
    for item in files:
        item = Path(item)
        if not _allowed_snapshot_path(str(item)) or item.is_symlink() or not item.is_file():
            raise SetupError('Unexpected snapshot input file: ' + str(item))
        info = item.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES:
            raise SetupError('Invalid/oversized snapshot input')
        data = item.read_bytes()
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise SetupError('Configuration snapshot exceeds size limit')
        collected.append((item, data, stat.S_IMODE(info.st_mode)))
    if not collected:
        raise SetupError('No existing owned configuration files to snapshot')
    manifest = {'version': VERSION, 'files': {
        str(p): {'sha256': _hash(blob), 'mode': mode}
        for p, blob, mode in collected}}
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as raw:
            with tarfile.open(fileobj=raw, mode='w:gz') as tar:
                for p, data, mode in collected:
                    entry = tarfile.TarInfo(p.as_posix().lstrip('/'))
                    entry.size = len(data); entry.mode = mode
                    tar.addfile(entry, io.BytesIO(data))
                data = (json.dumps(manifest, sort_keys=True) + '\n').encode()
                item = tarfile.TarInfo('manifest.json')
                item.size = len(data); item.mode = 0o600
                tar.addfile(item, io.BytesIO(data))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return manifest


def config_snapshot(r, cfg, ui):
    """Capture root-only, file-level recovery evidence (not full rollback)."""
    time = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = SNAPSHOT_ROOT / ('um780-config-' + time + '.tar.gz')
    manifest = build_snapshot(path, _collect_snapshot_paths())
    print('Private configuration snapshot: ' + str(path))
    print('Files preserved: ' + str(len(manifest['files'])) + '; restore is opt-in and not package rollback.')


def parse_snapshot(archive):
    """Verify tar members, types, hashes, size and target allowlist before any restore."""
    path = Path(archive)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_TOTAL_BYTES + 4 * 1024 * 1024:
        raise SetupError('Snapshot missing, symlinked or too large')
    snapshots = []
    with tarfile.open(path, mode='r:gz') as tar:
        members = tar.getmembers()
        if not members or len(members) > 200:
            raise SetupError('Invalid snapshot member count')
        seen = set()
        blobs = {}
        for member in members:
            if not member.isfile() or member.name in seen or member.size > MAX_FILE_BYTES:
                raise SetupError('Invalid snapshot member')
            seen.add(member.name)
            if member.name != 'manifest.json' and not _allowed_snapshot_path('/' + member.name):
                raise SetupError('Snapshot contains path outside allowlist')
            obj = tar.extractfile(member)
            if obj is None:
                raise SetupError('Snapshot member unavailable')
            blob = obj.read(MAX_FILE_BYTES + 1)
            if len(blob) != member.size:
                raise SetupError('Snapshot member truncated')
            blobs[member.name] = blob
        if 'manifest.json' not in blobs:
            raise SetupError('Snapshot lacks integrity manifest')
        info = json.loads(blobs.pop('manifest.json'))
        if info.get('version') != VERSION or not isinstance(info.get('files'), dict):
            raise SetupError('Unsupported snapshot manifest')
        if set(blobs) != {k.lstrip('/') for k in info['files']}:
            raise SetupError('Snapshot and manifest entries differ')
        for source, entry in info['files'].items():
            if not _allowed_snapshot_path(source) or entry.get('sha256') != _hash(blobs[source.lstrip('/')]):
                raise SetupError('Snapshot integrity/path error: ' + source)
            mode = entry.get('mode')
            if not isinstance(mode, int) or not 0 <= mode <= 0o777:
                raise SetupError('Invalid restored file mode')
            snapshots.append((Path(source), blobs[source.lstrip('/')], mode))
    return snapshots


def restore_config_snapshot(path, confirmation):
    """Restore allowlisted configuration only after explicit typed authorization."""
    if confirmation != 'RESTORE':
        raise SetupError('Type RESTORE exactly to permit configuration restore')
    path = Path(path)
    if not path.is_absolute() or path.parent.resolve() != SNAPSHOT_ROOT.resolve():
        raise SetupError('Restore file must be inside the managed snapshots directory')
    files = parse_snapshot(path)
    # Capture before-state of existing configuration as a separate recovery generation.
    existing = [p for p, _, _ in files if p.exists()]
    for p in existing:
        if p.is_symlink() or not p.is_file():
            raise SetupError('Refusing to overwrite unexpected restored path: ' + str(p))
    if existing:
        dest = SNAPSHOT_ROOT / ('before-restore-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.tar.gz')
        build_snapshot(dest, existing)
    for p, blob, mode in files:
        if p.parent.is_symlink():
            raise SetupError('Refusing symlink parent during restore: ' + str(p))
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.restore-', dir=p.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, mode)
            os.replace(temp, p)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return len(files)


def preflight(r, cfg, ui):
    """Extra safety diagnostics; read-only and does not authorize formatting."""
    notes = []
    errors = detect_target()
    notes.extend('FAIL: ' + s for s in errors)
    root = Path(cfg.get('model_storage', '/var/lib/llm-stack/models'))
    if root.is_symlink() or not root.is_absolute() or '..' in root.parts:
        errors.append('Untrusted model storage path')
        notes.append('FAIL: Untrusted model storage path')
    if str(root) not in ('/srv/llm-data/models', '/var/lib/llm-stack/models'):
        errors.append('Unknown model storage location')
        notes.append('FAIL: Unknown model storage location')
    for folder in ('/', '/var', '/opt'):
        usage = shutil.disk_usage(folder)
        notes.append(f'Disk {folder}: free {usage.free // (1024**3)} GiB')
        if usage.free < 3 * 1024**3:
            errors.append('Low free disk capacity under ' + folder)
    sock = Path('/etc/systemd/system/cockpit.socket.d/llm-postinstall.conf')
    if sock.exists():
        if sock.is_symlink() or 'ListenStream=127.0.0.1:9090' not in sock.read_text():
            errors.append('Cockpit private listener override is invalid')
    output = ['# Managed by debian-llm-postinstall', datetime.now(timezone.utc).isoformat(), *notes]
    path = Path('/var/log/llm-postinstall/preflight.txt')
    r.write(path, '\n'.join(output) + '\n', mode=0o600)
    if errors:
        raise SetupError('Preflight failed: ' + '; '.join(errors))
    print('Preflight passed read-only checks. Manual disk topology and app login review still required.')


def cockpit_status(r, cfg, ui):
    """Install static, non-root Cockpit page with read-only systemd probes."""
    if not Path('/etc/systemd/system/cockpit.socket.d/llm-postinstall.conf').is_file():
        raise SetupError('Install private Cockpit socket before cockpit_status')
    if STATUS_DEST.is_symlink():
        raise SetupError('Cockpit status destination is a symlink')
    ensure_dir(STATUS_DEST, mode=0o755)
    for name in ('manifest.json', 'index.html', 'status.js'):
        src = STATUS_ASSETS / name
        dest = STATUS_DEST / name
        raw = src.read_text()
        if dest.exists():
            old = dest.read_text()
            if old != raw and 'um780-postinstall-managed' not in old:
                raise SetupError('Refusing to overwrite externally managed Cockpit page: ' + str(dest))
        r.write(dest, raw, owned=False)
    print('Cockpit Tools -> UM780 Status page added. Read-only, user-permission probes only.')
