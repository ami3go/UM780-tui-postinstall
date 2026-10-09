"""SHA256-enforced release download utilities."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request
from .core import SetupError

def download(r, url, digest, path, *, max_bytes=3 * 1024**3):
    """GitHub release asset must have API sha256 digest; never execute downloaded scripts."""
    if not re.fullmatch(r'[a-fA-F0-9]{64}', digest or ''):
        raise SetupError('Missing trusted sha256 digest for ' + url)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and sha256(path) == digest.lower():
        r.logger.info('CACHE HIT %s', path)
        return path
    # Leave room for staging/extraction and existing workloads.
    if shutil.disk_usage(path.parent).free < min(max_bytes, 1024**3):
        raise SetupError('Insufficient free space to cache and extract release archive')
    fd, temp = tempfile.mkstemp(prefix='partial-', dir=path.parent)
    try:
        h = hashlib.sha256()
        total = 0
        with os.fdopen(fd, 'wb') as out:
            req = urllib.request.Request(url, headers={'User-Agent': 'debian-llm-postinstall/0.1'})
            with urllib.request.urlopen(req, timeout=60) as src:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk: break
                    total += len(chunk)
                    if total > max_bytes:
                        raise SetupError('Download exceeds maximum allowed release archive size')
                    if total + 200 * 1024**2 > shutil.disk_usage(path.parent).free:
                        raise SetupError('Download aborted: low disk free space')
                    out.write(chunk)
                    h.update(chunk)
        if h.hexdigest() != digest.lower():
            raise SetupError('SHA256 mismatch: ' + url)
        os.replace(temp, path)
        r.logger.info('VERIFIED DOWNLOAD %s sha256:%s', path, digest)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    return path

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def github_asset(r: Runner, repo: str, asset_name: str, *, version=None):
    url = f'https://api.github.com/repos/{repo}/releases/' + ('tags/' + version if version else 'latest')
    data = r.get_json(url)
    for asset in data['assets']:
        if asset['name'] == asset_name:
            digest = asset.get('digest', '')
            if not digest.startswith('sha256:'):
                raise SetupError(f'GitHub release {repo} asset lacks SHA256 digest; refusing unchecked download')
            download_url = asset['browser_download_url']
            if not download_url.startswith(f'https://github.com/{repo}/releases/download/'):
                raise SetupError('Release asset not hosted at official repository')
            return data['tag_name'], download_url, digest.removeprefix('sha256:')
    raise SetupError(f'{asset_name} missing from {repo} release {data.get("tag_name")}')


def install_release_asset(r, repo, asset_name, *, version=None):
    tag, url, digest = github_asset(r, repo, asset_name, version=version)
    out = r.download(url, digest, Path('/var/cache/llm-postinstall') / (tag + '-' + asset_name))
    return tag, out
