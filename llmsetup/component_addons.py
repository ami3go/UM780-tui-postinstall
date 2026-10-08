"""Optional management and maintenance services."""
from __future__ import annotations
from .component_base import *
from .component_llms import _safe_tar_list

def cockpit(r, cfg, ui):
    r.apt('cockpit', 'cockpit-system', 'cockpit-storaged')
    # Cockpit socket vendor defaults listen publicly; override to loopback.
    path = Path('/etc/systemd/system/cockpit.socket.d/llm-postinstall.conf')
    r.write(path, managed('[Socket]\nListenStream=\nListenStream=127.0.0.1:9090'))
    r.run(['systemctl', 'daemon-reload'])
    r.run(['systemctl', 'stop', 'cockpit.service'], check=False)
    r.run(['systemctl', 'stop', 'cockpit.socket'], check=False)
    r.run(['systemctl', 'enable', '--now', 'cockpit.socket'])


def filebrowser(r, cfg, ui):
    # Original filebrowser/filebrowser was archived Aug 2026; do not install unmaintained software.
    prepare_model_dirs(r, cfg)
    # Quantum v1.5 stable only. GitHub release API "latest" may be beta in future; validate tag.
    r.account('filebrowser', groups=('llmshare',))
    tag, asset_url, digest = github_asset(r, 'gtsteffaniak/filebrowser', 'linux-amd64-filebrowser', version='v1.5.6-stable')
    if tag.startswith('v2') or 'beta' in tag.lower() or 'rc' in tag.lower():
        raise SetupError('Quantum latest release is not stable v1.x; pin/review before upgrade')
    dest = ROOT_DIR / 'filebrowser-quantum' / tag
    ensure_dir(dest, mode=0o755)
    dest.parent.chmod(0o755)
    dest.chmod(0o755)
    binpath = dest / 'filebrowser'
    if not binpath.exists():
        r.download(asset_url, digest, binpath)
        binpath.chmod(0o755)
    base = Path('/var/lib/filebrowser')
    ensure_dir(base, user='filebrowser')
    pw = stable_secret(CONF_DIR / 'filebrowser-admin-password', 24)
    import json as _json
    config = managed(f'''server:
  port: 8082
  listen: "127.0.0.1"
  database: "/var/lib/filebrowser/database.db"
  sources:
    - name: "llm-models"
      path: "{model_root(cfg)}"
      config:
        defaultEnabled: true
auth:
  adminUsername: admin
  adminPassword: {_json.dumps(pw)}
  methods:
    password:
      enabled: true
''')
    path = base / 'config.yaml'
    conf_changed = r.write(path, config, mode=0o640)
    r.run(['chown', 'root:filebrowser', str(path)])
    unit(r, 'llm-filebrowser.service', f'''[Unit]
Description=FileBrowser Quantum stable file manager
After=network.target
RequiresMountsFor={model_root(cfg)}
[Service]
User=filebrowser
Group=filebrowser
SupplementaryGroups=llmshare
WorkingDirectory={base}
ExecStart={binpath} -c {path}
Restart=on-failure
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths={base}
[Install]
WantedBy=multi-user.target''', force_restart=conf_changed)
    print(f'FileBrowser Quantum admin password: {CONF_DIR}/filebrowser-admin-password')


def codeserver(r, cfg, ui):
    # Install a verified official GitHub release .deb using apt to resolve deps.
    if not shutil.which('code-server'):
        tag, data = install_release_asset(r, 'coder/code-server', _code_server_asset_name(r))
        r.run(['apt-get', 'install', '-y', str(data)])
    r.account('codeserver')
    ensure_dir('/var/lib/codeserver/workspace', user='codeserver')
    password = stable_secret(CONF_DIR / 'codeserver-password', 24)
    env_changed = r.write(CONF_DIR / 'codeserver.env', managed('PASSWORD=' + password), mode=0o600)
    unit(r, 'llm-codeserver.service', f'''[Unit]
Description=code-server local web IDE
After=network.target
[Service]
User=codeserver
EnvironmentFile={CONF_DIR}/codeserver.env
WorkingDirectory=/var/lib/codeserver
ExecStart=/usr/bin/code-server --auth password --bind-addr 127.0.0.1:8443 --user-data-dir /var/lib/codeserver/user-data /var/lib/codeserver/workspace
Restart=on-failure
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/codeserver
[Install]
WantedBy=multi-user.target''', force_restart=env_changed)
    print(f'code-server password: {CONF_DIR}/codeserver-password')


def _code_server_asset_name(r):
    info = r.get_json('https://api.github.com/repos/coder/code-server/releases/latest')
    # Latest .deb naming is version without leading v.
    version = info['tag_name'].removeprefix('v')
    return f'code-server_{version}_amd64.deb'


def tailscale(r, cfg, ui):
    # Official Debian Trixie signed repository. No curl|sh or unattended tailnet enrollment.
    r.apt('ca-certificates', 'curl')
    key_path = Path('/usr/share/keyrings/tailscale-archive-keyring.gpg')
    list_path = Path('/etc/apt/sources.list.d/tailscale.list')
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        with urllib.request.urlopen('https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg', timeout=30) as req:
            key = req.read(100000)
        if len(key) < 128:
            raise SetupError('Tailscale repository key appears malformed')
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, 'wb') as f: f.write(key)
    if not list_path.exists():
        with urllib.request.urlopen('https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list', timeout=30) as req:
            content = req.read(100000).decode()
        if ('pkgs.tailscale.com/stable/debian' not in content or
                'signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg' not in content):
            raise SetupError('Unexpected Tailscale repository definition')
        r.write(list_path, '# Installed by debian-llm-postinstall\n' + content, owned=False)
    r.run(['apt-get', 'update'])
    r.apt('tailscale')
    r.service('tailscaled.service', restart=False)
    print('Tailscale installed. Complete enrollment manually: sudo tailscale up')


def updates(r, cfg, ui):
    r.apt('unattended-upgrades', 'apt-listchanges')
    r.write('/etc/apt/apt.conf.d/52-llm-postinstall', managed('''Unattended-Upgrade::Origins-Pattern {
  "origin=Debian,codename=trixie-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
'''))
    r.write('/etc/apt/apt.conf.d/21-llm-postinstall-periodic', managed('''APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
'''))
    r.service('apt-daily.timer', restart=False)
    r.service('apt-daily-upgrade.timer', restart=False)


def benchmarks(r, cfg, ui):
    r.apt('sysstat', 'lm-sensors', 'nvme-cli', 'htop', 'iperf3', 'bc', 'jq', 'vulkan-tools', 'sysbench')
    outfile = Path('/var/log/llm-postinstall') / 'benchmark-report.txt'
    lines = [OWNER_MARK, 'Benchmark diagnostic report; CPU test only (not model tok/s)']
    for cmd in [['lscpu'], ['free', '-h'], ['sysbench', 'cpu', '--threads=' + str(min(os.cpu_count() or 4, 16)), '--cpu-max-prime=10000', 'run'], ['vulkaninfo', '--summary']]:
        result = r.run(cmd, check=False, capture=True, timeout=120)
        lines += ['', '> ' + ' '.join(cmd), result.stdout[:12000]]
    r.write(outfile, '\n'.join(lines) + '\n')
    print('Benchmark report: ' + str(outfile))
    print('For LLM tok/s measurements, use llama-bench -m /path/to/model.gguf after adding a GGUF.')
