"""Ollama, Open WebUI and Qwen model installers."""
from __future__ import annotations
from .component_base import *

def _safe_tar_list(r, archive, compressed_zst=False):
    args = ['tar', '--zstd' if compressed_zst else '-z', '-tf', str(archive)]
    listing = r.run(args, capture=True).stdout.splitlines()
    if not listing:
        raise SetupError('Empty release archive')
    for name in listing:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts:
            raise SetupError('Unsafe archive path: ' + name)


def ollama(r, cfg, ui):
    r.apt('zstd', 'tar')
    prepare_model_dirs(r, cfg)
    r.account('ollama', groups=('render', 'video', 'llmshare'))
    dest = ROOT_DIR / 'ollama'
    marker = dest / 'version'
    binary = dest / 'current/bin/ollama'
    if not binary.exists():
        tag, archive = install_release_asset(r, 'ollama/ollama', 'ollama-linux-amd64.tar.zst')
        _safe_tar_list(r, archive, compressed_zst=True)
        release_dir = dest / tag
        ensure_dir(release_dir, mode=0o755)
        dest.chmod(0o755)
        release_dir.chmod(0o755)
        r.run(['tar', '--zstd', '-xf', str(archive), '-C', str(release_dir),
               '--no-same-owner', '--no-same-permissions'])
        if not (release_dir / 'bin/ollama').is_file():
            raise SetupError('Ollama archive missing bin/ollama')
        current = dest / 'current'
        if current.is_symlink(): current.unlink()
        elif current.exists(): raise SetupError('Ollama current path is unmanaged')
        current.symlink_to(release_dir, target_is_directory=True)
        marker.write_text(tag + '\n')
    link = Path('/usr/local/bin/ollama')
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() != binary.resolve():
            raise SetupError('Existing /usr/local/bin/ollama is not ours; refusing replacement')
    else:
        link.symlink_to(binary)
    env_file = CONF_DIR / 'ollama.env'
    env_changed = r.write(env_file, managed('OLLAMA_HOST=127.0.0.1:11434\nOLLAMA_MODELS=' + str(Path(model_root(cfg)) / 'ollama')), mode=0o640)
    unit(r, 'llm-ollama.service', f'''[Unit]
Description=Ollama local model inference
After=network-online.target
Wants=network-online.target
RequiresMountsFor={model_root(cfg)}
[Service]
User=ollama
SupplementaryGroups=render video llmshare
EnvironmentFile={env_file}
ExecStart={binary} serve
Environment=HOME=/var/lib/ollama
StateDirectory=ollama
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/ollama {Path(model_root(cfg)) / 'ollama'}
[Install]
WantedBy=multi-user.target''', force_restart=env_changed)


def _install_uv(r):
    dest = Path('/usr/local/bin/uv')
    if dest.exists(): return dest
    tag, archive = install_release_asset(r, 'astral-sh/uv', 'uv-x86_64-unknown-linux-gnu.tar.gz')
    _safe_tar_list(r, archive)
    tmp = ROOT_DIR / 'uv-release' / tag
    ensure_dir(tmp)
    r.run(['tar', '-xzf', str(archive), '-C', str(tmp), '--no-same-owner', '--no-same-permissions'])
    binaries = list(tmp.rglob('uv'))
    found = [x for x in binaries if x.is_file() and os.access(x, os.X_OK)]
    if len(found) != 1:
        raise SetupError('UV release archive missing executable')
    shutil.copy2(found[0], dest)
    os.chmod(dest, 0o755)
    return dest


def webui(r, cfg, ui):
    r.apt('libgomp1', 'libstdc++6', 'libglib2.0-0t64', 'libgl1', 'ca-certificates')
    _install_uv(r)
    r.account('openwebui')
    prefix = ROOT_DIR / 'open-webui'
    ensure_dir(prefix, mode=0o755)
    prefix.chmod(0o755)
    python_store = ROOT_DIR / 'uv-python'
    env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(python_store), UV_PYTHON_PREFERENCE='managed')
    venv = prefix / 'venv'
    exe = venv / 'bin/open-webui'
    if not exe.is_file():
        r.run(['/usr/local/bin/uv', 'python', 'install', '3.11'], env=env)
        r.run(['/usr/local/bin/uv', 'venv', '--python', '3.11', str(venv)], env=env)
        # CPU PyTorch instead of pulling NVIDIA CUDA packages to an AMD APU machine.
        r.run(['/usr/local/bin/uv', 'pip', 'install', '--python', str(venv / 'bin/python'),
               'torch', '--index-url', 'https://download.pytorch.org/whl/cpu'], env=env)
        r.run(['/usr/local/bin/uv', 'pip', 'install', '--python', str(venv / 'bin/python'),
               'open-webui'], env=env)
    ensure_dir(Path('/var/lib/openwebui/data'), user='openwebui')
    secret_key = stable_secret(CONF_DIR / 'webui-secret')
    admin_pwd = stable_secret(CONF_DIR / 'webui-admin-password', 24)
    admin_email = 'admin@llm.local'
    conf = managed(f'''DATA_DIR=/var/lib/openwebui/data
OLLAMA_BASE_URL=http://127.0.0.1:11434
WEBUI_SECRET_KEY={secret_key}
WEBUI_AUTH=True
ENABLE_SIGNUP=False
WEBUI_ADMIN_EMAIL={admin_email}
WEBUI_ADMIN_PASSWORD={admin_pwd}
ENABLE_OPENAI_API=False
''')
    # root-only secret environment. Note bootstrap admin variables only take effect on empty DB.
    env_changed = r.write(CONF_DIR / 'webui.env', conf, mode=0o600)
    unit(r, 'llm-webui.service', f'''[Unit]
Description=Open WebUI native Python 3.11
After=network.target llm-ollama.service
Wants=llm-ollama.service
[Service]
User=openwebui
WorkingDirectory=/var/lib/openwebui
EnvironmentFile={CONF_DIR}/webui.env
ExecStart={exe} serve --host 127.0.0.1 --port 3000
Restart=on-failure
RestartSec=8
TimeoutStartSec=180
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/openwebui
[Install]
WantedBy=multi-user.target''', force_restart=env_changed)
    print(f'Open WebUI admin: {admin_email}; initial password in {CONF_DIR}/webui-admin-password (root only)')


def models(r, cfg, ui):
    model = cfg.get('model', 'qwen2.5-coder:7b')
    if not model.startswith(('qwen2.5-coder:', 'qwen3-coder:')):
        raise SetupError('Only explicitly configured Qwen coder models supported')
    if not ui.confirm(f'Download {model} now? This uses several GB of SSD space and internet bandwidth.'):
        print('Model download skipped')
        return
    if not Path('/usr/local/bin/ollama').exists():
        raise SetupError('Ollama binary absent; install Ollama first')
    r.run(['systemctl', 'start', 'llm-ollama.service'])
    r.run(['/usr/local/bin/ollama', 'pull', model], env={**os.environ, 'OLLAMA_HOST': '127.0.0.1:11434'})
