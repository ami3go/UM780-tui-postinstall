"""Modular installers; native services only, no container or remote shell scripts."""
from __future__ import annotations
import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import urllib.request
from .core import (CONF_DIR, OWNER_MARK, ROOT_DIR, STATE_DIR, SetupError,
                   ensure_dir, github_asset, install_release_asset, stable_secret)
from .storage import configure_storage

ALL = ['base', 'storage', 'vulkan', 'llama', 'ollama', 'webui', 'models',
       'cockpit', 'cockpit_ghsync', 'cockpit_bookmarks', 'filebrowser', 'codeserver', 'tailscale', 'updates', 'benchmarks',
       'fish', 'btop', 'mc', 'ttyd', 'agent_of_empires', 'jupyterlab', 'vnc', 'novnc', 'bookmark_sync', 'hardware_health', 'backup_restore',
       'cockpit_storage', 'service_watchdog', 'developer_tools', 'llm_benchmark', 'zram', 'opencode', 'llama_swap', 'uptime_kuma',
       'secure_ingress', 'ups_wol']
DESCRIPTIONS = {
 'base': 'System utilities, SSH and prerequisite packages',
 'storage': 'Optional existing second-SSD mount (typed UUID approval)',
 'vulkan': 'AMD firmware, Mesa/Vulkan driver + diagnostics',
 'llama': 'Build llama.cpp with Vulkan; optional GGUF service',
 'ollama': 'Ollama native service (localhost API, CPU fallback)',
 'webui': 'Open WebUI native Python 3.11 environment, authenticated',
 'models': 'Opt-in Qwen2.5-Coder:7b model download (~several GB)',
 'cockpit': 'Cockpit management, loopback-only TLS socket',
 'cockpit_ghsync': 'Your GitHub Sync Cockpit page (manual gh login)',
 'cockpit_bookmarks': 'Your Bookmarks Cockpit page (prebuilt .deb)',
 'filebrowser': 'FileBrowser Quantum stable, localhost, read-only model files',
 'codeserver': 'code-server native Debian package, localhost, password',
 'tailscale': 'Official signed Tailscale Debian 13 repository; login manual',
 'updates': 'Automated Debian security updates (no auto reboot)',
 'benchmarks': 'Diagnostics and benchmark prerequisites',
 'fish': 'Fish interactive shell (does not change login shell)',
 'btop': 'btop CPU, RAM and process monitor',
 'mc': 'Midnight Commander file manager',
 'ttyd': 'Optional browser terminal (local-only, disabled initially)',
 'agent_of_empires': 'Agent of Empires tmux coding-agent manager (no daemon)',
 'jupyterlab': 'Local-only token-authenticated JupyterLab workspace',
 'vnc': 'Virtual XFCE desktop via TigerVNC (manual activation)',
 'novnc': 'Browser VNC proxy (manual activation after VNC)',
 'bookmark_sync': 'Refresh Cockpit Bookmarks from installed applications',
 'hardware_health': 'SMART/NVMe/thermal monitoring and baseline report',
 'backup_restore': 'Restic backup CLI; timed backups only with verified external repository',
 'cockpit_storage': 'Cockpit storage and package update pages',
 'service_watchdog': 'Read-only periodic systemd service health journal alerts',
 'developer_tools': 'Git/terminal tools rg, fd, fzf, lazygit, zoxide',
 'llm_benchmark': 'Compare llama.cpp CPU and Vulkan token throughput with an existing GGUF',
 'zram': 'Debian compressed RAM swap via zram-tools',
 'opencode': 'Verified OpenCode coding-agent CLI, no daemon or auth setup',
 'llama_swap': 'Verified llama-swap model router binary, no listener',
 'uptime_kuma': 'Pinned native Uptime Kuma on localhost:3001, first-login admin',
 'secure_ingress': 'Inspect enrolled Tailscale identity, manual HTTPS Serve setup',
 'ups_wol': 'Prepare Cockpit UPS/WOL sources for reviewed dry-run installation'
}


def managed(body):
    return OWNER_MARK + '\n' + body.rstrip() + '\n'


def unit(r, name, body, *, start=True, force_restart=False):
    path = Path('/etc/systemd/system') / name
    changed = r.write(path, managed(body))
    r.run(['systemd-analyze', 'verify', str(path)])
    r.service(name, enable=start, restart=(changed or force_restart))


def model_root(cfg):
    return cfg.get('model_storage', '/var/lib/llm-stack/models')


def prepare_model_dirs(r, cfg):
    r.run(['groupadd', '-f', 'llmshare'])
    root = Path(model_root(cfg))
    # Never automatically mount or create filesystem; if storage was configured, assert mounted.
    if str(root).startswith('/srv/llm-data/') and not Path('/srv/llm-data').is_mount():
        raise SetupError('Model volume not mounted; refusing to write into its empty mountpoint')
    ensure_dir(root, group='llmshare', mode=0o2775)
    ensure_dir(root / 'ollama', group='llmshare', mode=0o2775)
    ensure_dir(root / 'gguf', group='llmshare', mode=0o2775)
    return root


def base(r, cfg, ui):
    r.run(['apt-get', 'update'])
    r.apt('ca-certificates', 'curl', 'git', 'openssh-server', 'jq', 'xz-utils', 'zstd',
          'tar', 'python3', 'sudo', 'pciutils', 'usbutils', 'lsof', 'iproute2', 'util-linux', 'whiptail')
    r.service('ssh.service', restart=False)
    ensure_dir(ROOT_DIR, mode=0o755)
    ROOT_DIR.chmod(0o755)  # service accounts must traverse this prefix
    ensure_dir(CONF_DIR, mode=0o700)
    ensure_dir(STATE_DIR, mode=0o700)


def storage(r, cfg, ui):
    chosen = configure_storage(r, ui.confirm, ui.ask)
    cfg['model_storage'] = chosen
    r.write(CONF_DIR / 'storage.json', json.dumps({'model_storage': chosen}, indent=2) + '\n', mode=0o600, owned=False)
    prepare_model_dirs(r, cfg)


def vulkan(r, cfg, ui):
    r.apt('firmware-amd-graphics', 'mesa-vulkan-drivers', 'libvulkan1', 'vulkan-tools',
          'libvulkan-dev', 'spirv-headers', 'glslc', 'libdrm-amdgpu1')
    output = r.run(['vulkaninfo', '--summary'], check=False, capture=True, timeout=30)
    if output.returncode:
        print('WARNING: Vulkan not yet functional; check Debian non-free-firmware and /dev/dri/render*')
    else:
        print(output.stdout[:1800])


def llama(r, cfg, ui):
    r.apt('build-essential', 'cmake', 'ninja-build', 'pkg-config', 'git', 'libssl-dev',
          'libvulkan-dev', 'glslc', 'spirv-headers', 'mesa-vulkan-drivers')
    src = ROOT_DIR / 'llama.cpp'
    exe = src / 'build/bin/llama-server'
    if not exe.is_file():
        if src.exists():
            if not (src / '.git').is_dir():
                raise SetupError('Existing llama.cpp directory is not an installer-managed Git repo')
            # No automatic update during repeat runs; state is stable and reproducible.
        else:
            tag = r.get_json('https://api.github.com/repos/ggml-org/llama.cpp/releases/latest')['tag_name']
            r.run(['git', 'clone', '--depth', '1', '--branch', tag,
                   'https://github.com/ggml-org/llama.cpp.git', str(src)])
        r.run(['cmake', '-S', str(src), '-B', str(src / 'build'), '-G', 'Ninja',
               '-DCMAKE_BUILD_TYPE=Release', '-DGGML_VULKAN=ON', '-DLLAMA_BUILD_SERVER=ON'])
        r.run(['cmake', '--build', str(src / 'build'), '-j', str(min(os.cpu_count() or 4, 8))])
    if not exe.is_file():
        raise SetupError('llama-server binary missing after build')
    prepare_model_dirs(r, cfg)
    r.account('llama', groups=('render', 'video', 'llmshare'))
    model = cfg.get('llama_model_path', '')
    if not model:
        existing = CONF_DIR / 'llama.env'
        if existing.exists():
            for line in existing.read_text().splitlines():
                if line.startswith('LLAMA_MODEL='):
                    model = line.split('=', 1)[1]
        if not model:
            print('llama.cpp built. Its service remains disabled until you select a GGUF model.')
            if not existing.exists(): r.write(existing, managed('LLAMA_MODEL='), mode=0o600)
            return
    from .core import safe_model
    if any(c.isspace() for c in model):
        raise SetupError('GGUF paths with whitespace are not supported by the systemd env file')
    if not safe_model(model, str(Path(model_root(cfg)) / 'gguf')):
        raise SetupError('GGUF must be an existing file within the designated gguf model directory')
    env_changed = r.write(CONF_DIR / 'llama.env', managed('LLAMA_MODEL=' + model), mode=0o600)
    unit(r, 'llm-llama.service', f'''[Unit]
Description=llama.cpp Vulkan inference server
After=network.target
[Service]
User=llama
SupplementaryGroups=render video llmshare
EnvironmentFile={CONF_DIR}/llama.env
ExecStart={exe} --model ${{LLAMA_MODEL}} --host 127.0.0.1 --port 8081 --n-gpu-layers 99
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
[Install]
WantedBy=multi-user.target''', force_restart=env_changed)
