"""Optional headless utilities and on-demand local development access.

Server components never expose arbitrary shells/desktops on the LAN automatically.
Requires explicit user activation for ttyd/VNC/noVNC; JupyterLab binds to localhost
and uses Jupyter's default token authentication under a non-root service user.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import urllib.request

from .core import ROOT_DIR, SetupError, ensure_dir
from .component_base import managed

BIN_DIR = ROOT_DIR / 'bin'
TTYD_TAG = '1.7.7'
TTYD_BINARY = 'ttyd.x86_64'
TTYD_DEST = BIN_DIR / 'ttyd'
AOE_TAG = 'v1.17.2'
AOE_ASSET = 'aoe-linux-amd64.tar.gz'
AOE_DEST = BIN_DIR / 'aoe'
VNC_UNIT = 'llm-vnc@.service'
NOVNC_UNIT = 'llm-novnc.service'
TTYD_UNIT = 'llm-ttyd.service'


def _official_release(r, repository, tag=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', repository):
        raise SetupError('Invalid release repository')
    suffix = '/tags/' + tag if tag else '/latest'
    release = r.get_json('https://api.github.com/repos/' + repository + '/releases' + suffix)
    if release.get('draft') or release.get('prerelease'):
        raise SetupError('Refusing prerelease or draft from ' + repository)
    if tag is not None and release.get('tag_name') != tag:
        raise SetupError('Unexpected release tag for ' + repository)
    return release


def _safe_release_url(repository, asset, tag):
    url = asset.get('browser_download_url', '')
    return (url.startswith('https://github.com/' + repository + '/releases/download/' + tag + '/') and
            url.rsplit('/', 1)[-1] == asset.get('name'))


def _checksum_text(url):
    """Tiny checksums file, bounded length, fetched only from vetted GitHub asset."""
    req = urllib.request.Request(url, headers={'User-Agent': 'UM780-tui-postinstall/0.2'})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read(65537)
    if len(data) > 65536:
        raise SetupError('Oversized upstream checksum manifest')
    return data.decode('utf-8', errors='strict')


def _checksum_line(text, name):
    """Support sha256sum formatted manifests and single-file digest manifests."""
    matches = []
    for raw in text.splitlines():
        line = raw.strip()
        m = re.fullmatch(r'([a-fA-F0-9]{64})\s+\*?(\S+)', line)
        if m and Path(m.group(2)).name == name:
            matches.append(m.group(1).lower())
        elif re.fullmatch(r'[a-fA-F0-9]{64}', line):
            matches.append(line.lower())
    if len(matches) != 1:
        raise SetupError('Unable to identify a unique SHA256 for ' + name)
    return matches[0]


def _release_binary(r, repository, filename, dest, *, tag=None, max_bytes=256 * 1024 * 1024):
    """Fetch only a named upstream release asset verified by a SHA256 manifest/API."""
    release = _official_release(r, repository, tag)
    tag = release['tag_name']
    assets = {item['name']: item for item in release.get('assets', [])
              if isinstance(item.get('name'), str)}
    if filename not in assets:
        raise SetupError(f'Missing {filename} in {repository} release {tag}')
    item = assets[filename]
    if not _safe_release_url(repository, item, tag):
        raise SetupError('Unexpected binary release URL')
    digest = item.get('digest') or ''
    if digest.startswith('sha256:') and re.fullmatch(r'[a-fA-F0-9]{64}', digest[7:]):
        checksum = digest[7:].lower()
    else:
        possibilities = [filename + '.sha256', 'SHA256SUMS']
        candidates = [assets[n] for n in possibilities if n in assets]
        if not candidates:
            raise SetupError('Upstream release has no approved checksum manifest')
        checksum_asset = candidates[0]
        if not _safe_release_url(repository, checksum_asset, tag):
            raise SetupError('Unexpected checksum release URL')
        checksum = _checksum_line(_checksum_text(checksum_asset['browser_download_url']), filename)
    target = Path(dest)
    if target.is_symlink():
        raise SetupError('Symlink installation target rejected: ' + str(target))
    if target.exists():
        if not target.is_file() or _file_digest(target) != checksum:
            raise SetupError('Existing installed binary differs; refusing silent upgrade')
        return target
    cache = Path('/var/cache/llm-postinstall') / (repository.replace('/', '-') + '-' + tag + '-' + filename)
    return r.download(item['browser_download_url'], checksum, cache, max_bytes=max_bytes)


def _file_digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def _atomic_binary_from_stream(source, destination, *, max_bytes=256 * 1024 * 1024):
    """Install a file atomically. Never follow preexisting symlinks or replace files."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise SetupError('Refusing to overwrite existing executable: ' + str(destination))
    ensure_dir(destination.parent, mode=0o755)
    fd, temp = tempfile.mkstemp(prefix='.incoming-', dir=destination.parent)
    try:
        size = 0
        with os.fdopen(fd, 'wb') as out:
            while True:
                block = source.read(1024 * 1024)
                if not block: break
                size += len(block)
                if size > max_bytes: raise SetupError('Executable exceeds maximum size')
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        if size < 10000:
            raise SetupError('Executable suspiciously short')
        os.chmod(temp, 0o755)
        os.link(temp, destination)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def _disabled_systemd_unit(r, name, body):
    """Provision service template, but never enable, restart or disable it on reruns."""
    path = Path('/etc/systemd/system') / name
    changed = r.write(path, managed(body))
    r.run(['systemd-analyze', 'verify', str(path)])
    if changed:
        r.run(['systemctl', 'daemon-reload'])
    return changed


def fish(r, cfg, ui):
    r.apt('fish')
    print('fish is available. No login shell is changed; run fish manually.')


def btop(r, cfg, ui):
    r.apt('btop')
    print('btop installed; run btop over SSH or in a terminal.')


def mc(r, cfg, ui):
    r.apt('mc')
    print('Midnight Commander installed; run mc from a terminal.')


def ttyd(r, cfg, ui):
    """Use verified static upstream release; ttyd is not in Debian 13 main."""
    ensure_dir(ROOT_DIR)
    ensure_dir(BIN_DIR)
    r.apt('ca-certificates', 'bash')
    artifact = _release_binary(r, 'tsl0922/ttyd', TTYD_BINARY, TTYD_DEST, tag=TTYD_TAG)
    if artifact != TTYD_DEST:
        with open(artifact, 'rb') as src:
            _atomic_binary_from_stream(src, TTYD_DEST, max_bytes=30 * 1024 * 1024)
    r.account('llmterminal')
    _disabled_systemd_unit(r, TTYD_UNIT, f"""[Unit]
Description=Local-only unprivileged browser terminal (ttyd)
After=network.target
[Service]
User=llmterminal
Group=llmterminal
WorkingDirectory=/var/lib/llmterminal
ExecStart={TTYD_DEST} --interface 127.0.0.1 --port 7681 --writable --check-origin --max-clients 1 /bin/bash --noprofile --norc
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/llmterminal
[Install]
WantedBy=multi-user.target
""")
    print('ttyd provisioned, NOT started. To opt in: sudo systemctl enable --now llm-ttyd.service')
    print('Connect using SSH port forwarding only: localhost:7681. Shell is low-privilege llmterminal.')


def agent_of_empires(r, cfg, ui):
    """Agent of Empires command only. Never start AoE Serve as root."""
    ensure_dir(ROOT_DIR)
    ensure_dir(BIN_DIR)
    r.apt('tmux', 'git', 'ca-certificates')
    artifact = _release_binary(r, 'agent-of-empires/agent-of-empires', AOE_ASSET, AOE_DEST, tag=AOE_TAG)
    if artifact != AOE_DEST:
        with tarfile.open(artifact, mode='r:gz') as tar:
            candidates = [m for m in tar.getmembers() if
                          Path(m.name).name in ('aoe', 'aoe-linux-amd64')]
            if len(candidates) != 1 or not candidates[0].isfile():
                raise SetupError('AoE release archive lacks one regular binary')
            if candidates[0].size < 10000 or candidates[0].size > 256 * 1024 * 1024:
                raise SetupError('AoE binary has unexpected size')
            stream = tar.extractfile(candidates[0])
            if stream is None: raise SetupError('AoE executable unavailable in archive')
            with stream: _atomic_binary_from_stream(stream, AOE_DEST)
    cli = Path('/usr/local/bin/aoe')
    if cli.is_symlink():
        if cli.resolve() != AOE_DEST.resolve():
            raise SetupError('Existing aoe symlink belongs to another installation')
    elif cli.exists():
        raise SetupError('Existing /usr/local/bin/aoe is unmanaged')
    else:
        cli.symlink_to(AOE_DEST)
    print('AoE installed at ' + str(AOE_DEST) + ' and linked as /usr/local/bin/aoe')
    print('Run as your normal Linux user; tmux sessions and agents remain user-owned.')
    print('Do not run AoE serve as root. No dashboard or Docker integration started.')


def jupyterlab(r, cfg, ui):
    """Debian-packaged Jupyter, localhost-only token auth, dedicated non-root user."""
    r.apt('jupyterlab', 'python3-ipykernel')
    r.account('llmjupyter')
    ensure_dir('/var/lib/llmjupyter/workspace', user='llmjupyter', mode=0o700)
    # Jupyter's default token authentication is retained; do not set password='' or token=''.
    from .component_base import unit
    unit(r, 'llm-jupyterlab.service', """[Unit]
Description=JupyterLab local-only service
After=network.target
[Service]
User=llmjupyter
Group=llmjupyter
WorkingDirectory=/var/lib/llmjupyter/workspace
Environment=HOME=/var/lib/llmjupyter
ExecStart=/usr/bin/jupyter-lab --no-browser --ip=127.0.0.1 --port=8888 --ServerApp.root_dir=/var/lib/llmjupyter/workspace --ServerApp.allow_remote_access=False
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/llmjupyter
[Install]
WantedBy=multi-user.target
""")
    print('JupyterLab bound to 127.0.0.1:8888, with default token authentication.')
    print('Use SSH -L 8888:127.0.0.1:8888; obtain per-instance token from local journal.')


def vnc(r, cfg, ui):
    """Install virtual XFCE desktop + TigerVNC; do not start until user sets password."""
    r.apt('tigervnc-standalone-server', 'tigervnc-tools', 'xfce4', 'dbus-x11')
    _disabled_systemd_unit(r, VNC_UNIT, """[Unit]
Description=Opt-in local TigerVNC XFCE desktop for %i
After=network.target
[Service]
Type=simple
User=%i
WorkingDirectory=~
ExecStartPre=/usr/bin/test %i != root
ExecStartPre=/usr/bin/test -s %h/.config/tigervnc/passwd
ExecStart=/usr/bin/tigervncserver -fg :1 -localhost yes -SecurityTypes VncAuth -geometry 1600x900 -xstartup /usr/bin/startxfce4
ExecStop=/usr/bin/tigervncserver -kill :1
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
[Install]
WantedBy=multi-user.target
""")
    print('TigerVNC/XFCE installed. VNC server is NOT enabled or started.')
    print('First, as an existing normal user run: tigervncpasswd')
    print('Then opt in: sudo systemctl enable --now llm-vnc@YOUR_USER.service')
    print('Never use root as YOUR_USER. VNC listens only on localhost:5901.')


def novnc(r, cfg, ui):
    """Turnkey dedicated XFCE desktop + noVNC, password generated securely."""
    from .component_novnc_setup import configure_novnc
    return configure_novnc(r, cfg, ui)
