"""Optional first-party Cockpit plugins: GitHub Sync and Bookmarks.

Uses pinned GitHub Sync source and a SHA256-verified Bookmarks Debian release.
Neither module logs into GitHub, schedules synchronizations or enables launchers.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .core import CONF_DIR, ROOT_DIR, SetupError, ensure_dir

GHSYNC_REPOSITORY = 'https://github.com/ami3go/ghsync.git'
GHSYNC_SHA = 'a7486866b8be162e1321690d2f5991ea33f0f13b'
BOOKMARKS_REPOSITORY = 'ami3go/bookmarks'
GHSYNC_REQUIRED = {
    'usr/local/bin/ghsync',
    'usr/local/bin/ghsync-thirdparty',
    'usr/local/bin/ghsync-maintenance',
    'usr/share/cockpit/ghsync/manifest.json',
    'usr/share/metainfo/io.github.ami3go.ghsync.metainfo.xml',
}
GHSYNC_DIR = Path('/usr/share/cockpit/ghsync')
BOOKMARKS_DIR = Path('/usr/share/cockpit/cockpit-bookmarks')
GHSYNC_STATE = CONF_DIR / 'cockpit-ghsync.json'
BOOKMARKS_STATE = CONF_DIR / 'cockpit-bookmarks.json'


def _secure_cockpit_override(contents):
    """Only the reset and a single loopback address may be configured here."""
    lines = [line.strip() for line in contents.splitlines()]
    listeners = [line for line in lines if line.startswith('ListenStream=')]
    return '[Socket]' in lines and listeners == ['ListenStream=', 'ListenStream=127.0.0.1:9090']


def _check_cockpit():
    """Require an already installed, loopback-restricted Cockpit socket."""
    override = Path('/etc/systemd/system/cockpit.socket.d/llm-postinstall.conf')
    if not override.is_file() or override.is_symlink():
        raise SetupError('Install the cockpit module first (loopback socket override missing)')
    if not _secure_cockpit_override(override.read_text()):
        raise SetupError('Cockpit loopback restriction is missing or unexpected')


def _digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _read_state(path):
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise SetupError('Untrusted plugin state path: ' + str(path))
    raw = path.read_text()
    if not raw.startswith('# Managed by debian-llm-postinstall\n'):
        raise SetupError('Plugin state is not installer managed: ' + str(path))
    return json.loads(raw.split('\n', 1)[1])


def _state_text(state):
    return '# Managed by debian-llm-postinstall\n' + json.dumps(state, indent=2, sort_keys=True) + '\n'


def _ghsync_stage_files(stage):
    """Only accept the upstream installer layout; reject symlinks/unexpected paths."""
    allowed = ('usr/local/bin/', 'usr/share/cockpit/ghsync/', 'usr/share/metainfo/')
    root = Path(stage)
    files = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise SetupError('Symlink in staged GitHub Sync installer: ' + str(path))
        if path.is_dir():
            continue
        if not path.is_file():
            raise SetupError('Unexpected non-file in staged GitHub Sync bundle')
        rel = path.relative_to(root).as_posix()
        if not rel.startswith(allowed):
            raise SetupError('Unexpected GitHub Sync output path: ' + rel)
        if rel.startswith('usr/share/metainfo/') and rel != 'usr/share/metainfo/io.github.ami3go.ghsync.metainfo.xml':
            raise SetupError('Unexpected app metadata: ' + rel)
        if rel.startswith('usr/local/bin/') and rel not in GHSYNC_REQUIRED:
            raise SetupError('Unexpected executable in staged GitHub Sync: ' + rel)
        files[rel] = path
    if not GHSYNC_REQUIRED.issubset(files):
        raise SetupError('GitHub Sync staged bundle is incomplete: ' +
                         ', '.join(sorted(GHSYNC_REQUIRED - files.keys())))
    return files


def _copy_file(source, dest):
    """Create or replace one regular file atomically; do not follow symlink target."""
    if dest.is_symlink():
        raise SetupError('Refusing symlinked installation target: ' + str(dest))
    ensure_dir(dest.parent)
    fd, temp = tempfile.mkstemp(prefix='.' + dest.name + '-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as out, open(source, 'rb') as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, source.stat().st_mode & 0o755)
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def cockpit_ghsync(r, cfg, ui):
    """System-wide Cockpit plugin; sync credentials remain with each login user."""
    _check_cockpit()
    state = _read_state(GHSYNC_STATE)
    if state and state.get('source_sha') != GHSYNC_SHA:
        raise SetupError('Existing GitHub Sync is pinned to another commit; review upgrade manually')
    if state and state.get('status') == 'installed':
        recorded = state.get('files', {})
        if recorded and all(Path('/' + name).is_file() and
                            not Path('/' + name).is_symlink() and
                            _digest(Path('/' + name)) == expected
                            for name, expected in recorded.items()):
            print('GitHub Sync already installed at verified pinned revision')
            return
        raise SetupError('GitHub Sync installed files differ from recorded hashes; refusing replacement')
    if not state:
        if (GHSYNC_DIR.exists() or
            any(Path('/' + name).exists() or Path('/' + name).is_symlink()
                for name in GHSYNC_REQUIRED)):
            raise SetupError('Existing unmanaged GitHub Sync installation found; migrate manually')
    r.apt('git', 'gh', 'cron', 'bash')
    ensure_dir(ROOT_DIR)
    source = ROOT_DIR / 'cockpit-ghsync-src'
    if not source.exists():
        r.run(['git', 'clone', '--no-checkout', GHSYNC_REPOSITORY, str(source)])
        r.run(['git', '-C', str(source), 'checkout', '--detach', GHSYNC_SHA])
    elif source.is_symlink() or not (source / '.git').is_dir():
        raise SetupError('Existing source checkout is not a trusted Git directory')
    rev = r.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture=True).stdout.strip()
    if rev != GHSYNC_SHA:
        raise SetupError('GitHub Sync source revision does not match audited pin')
    origin = r.run(['git', '-C', str(source), 'remote', 'get-url', 'origin'],
                   capture=True).stdout.strip()
    if origin != GHSYNC_REPOSITORY:
        raise SetupError('GitHub Sync source origin differs from trusted repository')
    dirty = r.run(['git', '-C', str(source), 'status', '--porcelain'],
                  capture=True).stdout.strip()
    if dirty:
        raise SetupError('Pinned GitHub Sync checkout has local modifications; refusing execution')
    if not (source / 'install.sh').is_file():
        raise SetupError('Pinned GitHub Sync install.sh missing')
    with tempfile.TemporaryDirectory(prefix='cockpit-ghsync-', dir=ROOT_DIR) as stage:
        env = dict(os.environ, DESTDIR=stage)
        # Run upstream installer against an isolated staging tree, never against live /.
        r.run(['bash', str(source / 'install.sh'), '--system'], cwd=str(source), env=env)
        files = _ghsync_stage_files(stage)
        # An interrupted first install may be resumed only for the same pinned source.
        if not state:
            state = {'status': 'installing', 'source_sha': GHSYNC_SHA, 'files': {}}
            r.write(GHSYNC_STATE, _state_text(state), mode=0o600)
        digests = {name: _digest(path) for name, path in files.items()}
        for name, staged in sorted(files.items()):
            target = Path('/') / name
            if target.exists():
                if target.is_symlink() or not target.is_file():
                    raise SetupError('Existing unsafe GitHub Sync destination: ' + name)
                if _digest(target) != digests[name]:
                    raise SetupError('Existing GitHub Sync file differs from pinned package: ' + name)
            else:
                _copy_file(staged, target)
        r.write(GHSYNC_STATE, _state_text({
            'status': 'installed', 'source_sha': GHSYNC_SHA, 'files': digests
        }), mode=0o600)
    print('GitHub Sync installed under Cockpit Tools. Authenticate as each user: gh auth login')
    print('No repository synchronization or schedule has been activated.')


def select_bookmarks_asset(release):
    """Only accept one stable Bookmarks all-architecture Debian asset with API SHA256."""
    if release.get('draft') or release.get('prerelease'):
        raise SetupError('Bookmarks release is draft or prerelease')
    tag = release.get('tag_name', '')
    if not re.fullmatch(r'v?[0-9]+\.[0-9]+\.[0-9]+(?:[-.][0-9A-Za-z]+)*', tag):
        raise SetupError('Unexpected Bookmarks release tag: ' + tag)
    matches = [a for a in release.get('assets', []) if
               re.fullmatch(r'cockpit-bookmarks_[0-9][A-Za-z0-9.+:~-]*_all\.deb', a.get('name', ''))]
    if len(matches) != 1:
        raise SetupError('Expected exactly one release cockpit-bookmarks_*_all.deb asset')
    asset = matches[0]
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        raise SetupError('Bookmarks Debian asset is missing a usable SHA256 digest')
    url = asset.get('browser_download_url', '')
    prefix = 'https://github.com/ami3go/bookmarks/releases/download/'
    if not url.startswith(prefix) or not url.endswith('/' + asset['name']):
        raise SetupError('Unexpected Bookmarks download URL')
    return asset['name'], url, digest[7:], tag


def cockpit_bookmarks(r, cfg, ui):
    """Install a release-built no-Node.js .deb; preserve existing bookmark config."""
    _check_cockpit()
    installed = r.run(['dpkg-query', '-W', '-f=${Status}', 'cockpit-bookmarks'],
                      check=False, capture=True)
    if installed.returncode == 0 and installed.stdout.strip() == 'install ok installed':
        if not (BOOKMARKS_DIR / 'manifest.json').is_file():
            raise SetupError('Bookmarks package installed but Cockpit manifest missing')
        print('Cockpit Bookmarks already installed via dpkg; no implicit version upgrade')
        return
    if BOOKMARKS_DIR.exists():
        raise SetupError('Unmanaged Bookmarks directory found; refusing package overwrite')
    release = r.get_json('https://api.github.com/repos/ami3go/bookmarks/releases/latest')
    name, url, digest, tag = select_bookmarks_asset(release)
    ensure_dir(ROOT_DIR)
    # Downloader checks asset bytes against release metadata; no external install scripts.
    archive = r.download(url, digest, Path('/var/cache/llm-postinstall') / ('bookmarks-' + tag + '-' + name))
    r.run(['apt-get', 'install', '-y', str(archive)])
    if not (BOOKMARKS_DIR / 'manifest.json').is_file():
        raise SetupError('Bookmarks package installation produced no Cockpit manifest')
    r.write(BOOKMARKS_STATE, _state_text({
        'status': 'installed', 'release_tag': tag, 'sha256': digest, 'deb_asset': name
    }), mode=0o600)
    print('Cockpit Bookmarks installed; existing /etc/cockpit/cockpit-bookmarks.json is preserved.')
    print('Do not enable remote terminal launchers without reviewing bind and auth settings.')
