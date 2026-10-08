"""Non-destructive diagnostics. Service outcomes: PASS / WARN / FAIL / PENDING."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import socket
import subprocess
import urllib.request
from .core import detect_target

MANAGEMENT_PORTS = (11434, 8081, 3000, 3001, 8082, 8443, 9090, 7681, 8888, 5901, 5902, 6080)

SERVICE_MAP = {
 'llama': 'llm-llama.service', 'ollama': 'llm-ollama.service',
 'webui': 'llm-webui.service', 'cockpit': 'cockpit.socket',
 'filebrowser': 'llm-filebrowser.service', 'codeserver': 'llm-codeserver.service',
 'tailscale': 'tailscaled.service', 'updates': 'apt-daily-upgrade.timer',
 'jupyterlab': 'llm-jupyterlab.service', 'novnc': 'llm-novnc.service',
 'service_watchdog': 'llm-service-watchdog.timer',
 'uptime_kuma': 'llm-uptime-kuma.service',
 'zram': 'zramswap.service', 'backup_restore': 'llm-backup.timer'
}


def probe(cmd, timeout=8):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def check_port(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def public_bindings(ss_output):
    # ss -lntH format: State Recv-Q Send-Q Local Address:Port Peer Address:Port
    found = []
    for line in ss_output.splitlines():
        fields = line.split()
        if len(fields) < 5: continue
        address = fields[3].strip()
        for port in MANAGEMENT_PORTS:
            if address.endswith(':' + str(port)):
                host = address.rsplit(':', 1)[0].strip('[]')
                if host in ('0.0.0.0', '::', '*', '[::]'):
                    found.append((port, address))
    return found


def diagnostics(components=None):
    components = components or list(SERVICE_MAP)
    result = []
    for err in detect_target():
        result.append(('FAIL', 'system', err))
    ss_ok, ss_text = probe(['ss', '-lntH'])
    if ss_ok:
        for port, address in public_bindings(ss_text):
            result.append(('FAIL', 'network exposure', f'{address} is public! Restrict TCP port {port}'))
    else:
        result.append(('WARN', 'network exposure', 'Cannot inspect listening port addresses (ss unavailable)'))
    for name, binaries in [('hardware_health', ('nvme', 'smartctl', 'sensors')),
                           ('developer_tools', ('rg', 'fdfind', 'fzf', 'lazygit', 'zoxide'))]:
        if name in components:
            missing = [cmd for cmd in binaries if shutil.which(cmd) is None]
            result.append(('WARN' if missing else 'PASS', name,
                           'missing: ' + ', '.join(missing) if missing else 'tools found on PATH'))
    if 'vulkan' in components:
        ok, msg = probe(['vulkaninfo', '--summary'], timeout=20)
        result.append(('PASS' if ok else 'WARN', 'vulkan',
                       'Vulkan device detected' if ok else 'Vulkan unavailable; AMD firmware or /dev/dri permissions may be missing'))
    if 'storage' in components:
        model_root = Path('/var/lib/llm-stack/models')
        import json
        conf = Path('/etc/llm-postinstall/storage.json')
        if conf.exists():
            try: model_root = Path(json.loads(conf.read_text()).get('model_storage', model_root))
            except (ValueError, OSError): pass
        need_mount = str(model_root).startswith('/srv/llm-data/')
        result.append(('PASS' if model_root.is_dir() and (not need_mount or Path('/srv/llm-data').is_mount()) else 'WARN',
                       'storage', str(model_root) + (' (mounted)' if need_mount else '')))
    for component, service in SERVICE_MAP.items():
        if component not in components: continue
        ok, _ = probe(['systemctl', 'is-active', '--quiet', service])
        enabled, _ = probe(['systemctl', 'is-enabled', '--quiet', service])
        if component == 'llama' and not Path('/etc/llm-postinstall/llama.env').exists():
            status = 'PENDING'
        elif component == 'llama' and not ok:
            status = 'PENDING'  # GGUF isn't configured yet
        else:
            status = 'PASS' if ok and enabled else 'WARN'
        result.append((status, component, f'{service}: active={ok}, enabled={enabled}'))
    for comp, port in [('ollama', 11434), ('webui', 3000), ('codeserver', 8443), ('filebrowser', 8082)]:
        if comp in components:
            ok = check_port('127.0.0.1', port)
            result.append(('PASS' if ok else 'WARN', comp + ' port', f'127.0.0.1:{port}'))
    if 'cockpit_ghsync' in components:
        pkg = Path('/usr/share/cockpit/ghsync/manifest.json')
        cli = Path('/usr/local/bin/ghsync')
        ok = pkg.is_file() and cli.is_file() and not pkg.is_symlink() and not cli.is_symlink()
        result.append(('PASS' if ok else 'WARN', 'cockpit-ghsync',
                       'Cockpit page and CLI installed; GitHub auth is per user and not tested'))
    if 'bookmark_sync' in components:
        pkg = Path('/usr/share/cockpit/cockpit-bookmarks/manifest.json')
        config = Path('/etc/cockpit/cockpit-bookmarks.json')
        result.append(('PASS' if pkg.is_file() and config.is_file() else 'WARN',
                       'bookmark-sync', 'file presence only; links and tunnels not tested'))
    if 'cockpit_bookmarks' in components:
        pkg = Path('/usr/share/cockpit/cockpit-bookmarks/manifest.json')
        ok = pkg.is_file() and not pkg.is_symlink()
        result.append(('PASS' if ok else 'WARN', 'cockpit-bookmarks',
                       'Cockpit page installed; config, login and launchers are not tested'))
    for component, cmd in [('fish', 'fish'), ('btop', 'btop'), ('mc', 'mc')]:
        if component in components:
            ok = shutil.which(cmd) is not None
            result.append(('PASS' if ok else 'WARN', component, 'binary on PATH' if ok else 'binary not found'))
    for component, binary in [('ttyd', '/opt/llm-stack/bin/ttyd'),
                              ('agent_of_empires', '/opt/llm-stack/bin/aoe')]:
        if component in components:
            installed = Path(binary).is_file()
            result.append(('PASS' if installed else 'WARN', component, 'binary installed; function not exercised'))
    for component, unit_name, port in [('ttyd', 'llm-ttyd.service', 7681),
                                        ('vnc', 'llm-vnc@.service', 5901)]:
        if component in components:
            exists = Path('/etc/systemd/system', unit_name).is_file()
            result.append(('PENDING' if exists else 'WARN', component+'-activation',
                           'manual per-user setup required; check service instance/listener yourself'))
    if 'novnc' in components:
        vnc = probe(['systemctl', 'is-active', '--quiet', 'llm-novnc-vnc.service'])[0]
        proxy = check_port('127.0.0.1', 6080)
        backend = check_port('127.0.0.1', 5902)
        result.append(('PASS' if vnc and proxy and backend else 'WARN', 'novnc-backend',
                       f'XFCE desktop active={vnc}; 127.0.0.1:5902={backend}; 127.0.0.1:6080={proxy}; VNC auth untested'))
    if 'jupyterlab' in components:
        result.append(('PASS' if check_port('127.0.0.1', 8888) else 'WARN', 'jupyter-port',
                       '127.0.0.1:8888 (TCP only, token auth not tested)'))
    for name, file in [('opencode', '/usr/local/bin/opencode'),
                       ('llama_swap', '/usr/local/bin/llama-swap'),
                       ('ups_wol', '/opt/llm-stack/cockpit-ups-wol/install.sh')]:
        if name in components:
            p = Path(file)
            result.append(('PASS' if p.is_file() else 'WARN', name,
                           'binary/source present; upstream execution not tested'))
    if 'uptime_kuma' in components:
        ok=check_port('127.0.0.1',3001)
        result.append(('PASS' if ok else 'WARN','uptime-port',
                       '127.0.0.1:3001 (TCP; authentication not verified)'))
    if 'tailscale' in components:
        ok, out = probe(['tailscale', 'status', '--json'])
        status = 'WARN'
        if ok:
            import json
            try:
                status = 'PASS' if json.loads(out).get('BackendState') == 'Running' else 'WARN'
            except ValueError:
                pass
        result.append((status, 'tailscale-login', 'Run sudo tailscale up if not connected'))
    return result


def render(components=None):
    entries = diagnostics(components)
    for status, name, details in entries:
        print(f'[{status:7}] {name:17} {details}')
    return 1 if any(status == 'FAIL' for status, _, _ in entries) else 0
