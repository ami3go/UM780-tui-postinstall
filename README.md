# UM780-tui-postinstall

A **native, modular Debian 13 (Trixie) post-install CLI/TUI** for a bare-metal local-LLM server. Designed around a Minisforum UM780 Pro, Ryzen 7 7840HS / Radeon 780M, 64 GB RAM and two 512 GB NVMe drives. No Docker is installed by this project.

> **Status: PRE-RELEASE — unvalidated on the target hardware.** The GitHub Actions workflow tests Python logic on Ubuntu runners; it does not install the stack on Debian, exercise the Radeon GPU, verify login flows, or prove data safety across reboots. Back up both disks before first use. See [known limitations](docs/KNOWN_ISSUES.md) and [hardware acceptance checks](docs/ACCEPTANCE.md).

## Documentation

| Guide | Purpose |
| --- | --- |
| [Optional safety and status](docs/OPTIONAL_SAFETY.md) | Preflight, private config snapshots/manual restore, Cockpit service overview |
| [Optional native applications](docs/OPTIONAL_NATIVE_APPS.md) | OpenCode, llama-swap, Uptime Kuma, ingress readiness and UPS/WOL |
| [Optional maintenance tools](docs/OPTIONAL_MAINTENANCE.md) | NVMe health, Restic, watchdog, zram, developer tools and model benchmarks |
| [Five-stage installation workflow](docs/INSTALL_STAGES.md) | Priority 1–5 grouping, per-step setup order, prerequisites, verification and CLI examples |
| [Installation](docs/INSTALLATION.md) | Prerequisites, staged install, selecting existing second NVMe, first login |
| [Configuration](docs/CONFIGURATION.md) | Exact JSON keys, flags, module dependencies, default ports/paths |
| [Architecture](docs/ARCHITECTURE.md) | Modules, state, systemd and data flows, design constraints |
| [Operations](docs/OPERATIONS.md) | Start/stop, SSH/Tailscale forwarding, updates, backups, diagnostics |
| [Automatic application bookmarks](docs/BOOKMARKS_AUTO.md) | Auto-add web apps and safe on-demand terminal cards into Cockpit Bookmarks |
| [Turnkey noVNC desktop](docs/NOVNC_DESKTOP.md) | Auto-configured XFCE session, generated VNC password and Cockpit bookmark |
| [Optional server tools](docs/OPTIONAL_TOOLS.md) | Fish, btop, MC, ttyd, AoE, JupyterLab and on-demand VNC/noVNC |
| [Cockpit extensions](docs/COCKPIT_PLUGINS.md) | GitHub Sync and Bookmarks setup, access, security, and updates |
| [Security and storage](docs/SECURITY.md) | Threat model, disk safeguards, permissions, network exposure and trust |
| [Known issues](docs/KNOWN_ISSUES.md) | Implementation gaps and unverified integration assumptions |
| [Development and testing](docs/DEVELOPMENT.md) | Test suite, CI scope, contribution and documentation rules |
| [Acceptance checklist](docs/ACCEPTANCE.md) | Evidence required before first production deployment |

## Quick start

On an existing **Debian 13 x86_64, bare-metal** installation, preferably with SSH and working DNS:

```sh
sudo apt update
sudo apt install -y git python3
git clone https://github.com/ami3go/UM780-tui-postinstall.git
cd UM780-tui-postinstall
python3 install.py --plan
python3 -m unittest discover -s tests -v
# Stage modules one at a time after reading docs/INSTALLATION.md:
sudo python3 install.py --apply --component base
sudo python3 install.py --apply --component vulkan
# Interactive staged TUI / numbered fallback (preserves 18 default selections):
sudo python3 install.py
sudo python3 install.py --health
```

**Installation priorities:** To install in controlled phases, run `python3 install.py --list-stages`, then `python3 install.py --plan --stage 1` and `sudo python3 install.py --apply --stage 1`, followed by stages 2–5. `--stage N` selects only modules already enabled in `config.json`; optional tools remain unchecked. The interactive TUI has five category screens. See [Staged installation](docs/INSTALL_STAGES.md).

**Do not select the full default checklist until the known integration risks have been reviewed.** If `whiptail` is not yet installed, the installer uses a numbered text selection screen. The `--plan` command is a high-level read-only plan, **not** a full diff of package, fstab or service changes. Use `--component` to reduce scope; dependencies are not automatically resolved. The staged plan displays advisory prerequisites, but will never auto-select optional tools.

## Available components

| Component | Effect |
| --- | --- |
| `base` | Apt prerequisites and SSH |
| `storage` | Offers to mount a **pre-existing**, unmounted ext4/XFS/Btrfs filesystem; exact UUID typed confirmation |
| `vulkan` | AMD firmware and Vulkan packages; diagnostic probe |
| `llama` | Builds llama.cpp with Vulkan; server remains unconfigured until a local GGUF is selected |
| `ollama` | Native local Ollama API, `127.0.0.1:11434` |
| `webui` | Python 3.11/uv Open WebUI, `127.0.0.1:3000` |
| `models` | Optional `qwen2.5-coder:7b` pull into Ollama |
| `cockpit` | Cockpit HTTPS `127.0.0.1:9090` |
| `cockpit_ghsync` | [Your GitHub Sync](https://github.com/ami3go/ghsync) Cockpit plugin; per-user GitHub authentication |
| `cockpit_bookmarks` | [Your Bookmarks](https://github.com/ami3go/bookmarks) Cockpit plugin; prebuilt `.deb`, launchers opt-in |
| `filebrowser` | FileBrowser Quantum v1.5.6-stable, `127.0.0.1:8082` |
| `codeserver` | code-server HTTP `127.0.0.1:8443` |
| `tailscale` | Tailscale software and daemon, **manual enrollment required** |
| `updates` | Debian unattended security updates; no automatic reboot |
| `benchmarks` | sysbench CPU and basic Vulkan/system diagnostics; **not** LLM tokens/second |
| `fish` | Interactive shell; does not change default login shell |
| `btop` | CLI CPU/memory/system activity monitor |
| `mc` | Midnight Commander TUI file manager |
| `ttyd` | Local-only browser terminal service; **disabled until explicitly enabled** |
| `agent_of_empires` | User-run Agent of Empires `aoe`/tmux manager, no daemon |
| `jupyterlab` | Authenticated, local-only notebook server, `127.0.0.1:8888` |
| `vnc` | Optional TigerVNC virtual XFCE desktop, **not started**; password required |
| `novnc` | Configures a dedicated XFCE VNC server + noVNC browser proxy; generates root-only VNC password, enables localhost services and adds Cockpit bookmark |
| `bookmark_sync` | Rescan installed applications into Cockpit Bookmarks; automatic on successful apply by default |
| `hardware_health` | Non-destructive SSD SMART, NVMe and temperature baseline |
| `backup_restore` | Restic CLI, optional external encrypted backup timer after repository validation |
| `cockpit_storage` | Storage and package update Cockpit pages |
| `service_watchdog` | Read-only service monitoring timer and journal alerts |
| `developer_tools` | Additional terminal Git and navigation tools |
| `llm_benchmark` | Real llama-bench CPU/GPU throughput comparison (existing GGUF required) |
| `zram` | zram-tools compressed swap in memory |
| `opencode` | Verified OpenCode AI coding agent binary; no automatic authentication |
| `llama_swap` | Verified model router executable, no active listener by default |
| `uptime_kuma` | Native, localhost-only Uptime Kuma on port 3001; first-login setup |
| `secure_ingress` | Tailscale identity readiness check; explicitly configure Serve yourself |
| `ups_wol` | Prepare source of Cockpit UPS/WOL appliance for manual dry-run setup |
| `preflight` | Optional early-stage free space/storage-root and private Cockpit checks |
| `config_snapshot` | Root-only SHA-verified configuration snapshot with explicit restore CLI |
| `cockpit_status` | Read-only service status page under Cockpit Tools |

The default `config.json` selects the original core components plus Fish, btop and Midnight Commander. The five additional components (ttyd, Agent of Empires, JupyterLab, VNC and noVNC) start **unchecked**. The selected core components still include the optional Qwen model download module. Dependencies are not installed implicitly by per-component reruns. Only the `models` module prompts before pulling a model; `--yes` accepts that prompt as well as the initial apply prompt, so review the plan first.

By default, each successful apply run also adds missing app cards to Cockpit Bookmarks if the plugin is installed. This does **not** start services or make localhost-bound ports accessible remotely; read [automatic bookmarks](docs/BOOKMARKS_AUTO.md) before relying on the links.

## Access model

Management and inference listeners are configured for **localhost only**. This does **not** provide direct LAN access by default; LAN and Tailscale access are via SSH forwarding unless you separately configure an authenticated ingress. From your client:

```sh
ssh -N -L 3000:127.0.0.1:3000 -L 11434:127.0.0.1:11434 \
  -L 9090:127.0.0.1:9090 -L 8082:127.0.0.1:8082 \
  -L 8443:127.0.0.1:8443 user@SERVER_IP
```

Browse `http://127.0.0.1:3000` (Open WebUI) or `https://127.0.0.1:9090` (Cockpit; inspect browser certificate warning). **Do not expose Ollama's unauthenticated API** to untrusted networks. Tailscale `up` and any Tailscale Serve setup are manual.

## Data protection and integrity

- **No `mkfs`, `wipefs`, repartitioning, or resizing operations are implemented.** An existing second-disk filesystem may be mounted only after entering its complete UUID. The script **does modify** `/etc/fstab` and mount state if authorized.
- Data stored by Ollama and llama.cpp lives under `/var/lib/llm-stack/models` or, following a successful optional mount, `/srv/llm-data/models`. Existing filesystems and data are **not** backed up by the installer.
- Systemd services and app configuration are installed or changed. Reruns are only **partially idempotent**; no transaction-wide rollback or automatic package uninstall exists.
- Binary releases are downloaded from upstream GitHub releases and require the API-provided SHA256 digest. Other sources (apt repositories, Python packages and Git source) follow their respective trust mechanisms; versions are **not all pinned**.
- **FileBrowser Quantum's model source is not enforced read-only by current code**. Treat its credentials as privileged model-storage access. See [Security](docs/SECURITY.md).

## Status and support

```sh
python3 install.py --plan
sudo python3 install.py --health
sudo systemctl status llm-ollama.service llm-webui.service --no-pager
sudo journalctl -u llm-ollama.service -n 60 --no-pager
```

`--health` can report `PASS`/`WARN`/`FAIL`/`PENDING`, but it is a **shallow availability check**, not a proof of GPU offload, successful inference, security, password login, or disk integrity. Unhealthy services may show only `WARN` and produce exit code 0; consult [Operations](docs/OPERATIONS.md).

Read [Known issues](docs/KNOWN_ISSUES.md) before deployment. Feature and safety work should be addressed in focused PRs with tests before claiming this installer production-ready.
