# Five-stage Debian 13 post-install workflow

The interactive installer now uses **five priority steps**. Every one of the 39 available modules belongs to exactly one category and has a deterministic installation order within it.

**Important:** Priority means the recommended sequence for a new UM780 Pro. It does **not** mean every tool is essential, and it does not authorize automatic disk changes, extra model downloads, public interfaces or power management. The same original 18 modules remain selected by default; the other **21 modules remain opt-in**.

## Step 1 — Essential system and data safety

Goal: establish a stable Debian foundation, inspect both NVMe SSDs, then add safe maintenance.

| Order | Module | Default | Installation action | Setup/verification afterward |
| ---: | --- | :---: | --- | --- |
| 1.1 | `preflight` | No | Read-only storage path, free-space, OS and Cockpit checks | Resolve warnings before applying further changes |
| 1.2 | `base` | Yes | APT, Git, Python, SSH, base utilities | Check SSH access, package sources, Debian 13 |
| 1.3 | `config_snapshot` | No | Save previous managed configurations in root-only hashed archive | For existing installs: test explicit recovery; no package rollback |
| 1.4 | `storage` | Yes | Offer to mount a **pre-existing** second SSD filesystem | Confirm physical disk/UUID, mount and model path; never format |
| 1.5 | `hardware_health` | No | nvme-cli, SMART and thermal tools; capture baseline | Inspect SSD temperature, wear and media errors |
| 1.6 | `updates` | Yes | Debian security update timer | Check apt source, journal and no unattended reboot |
| 1.7 | `zram` | No | zram-tools compressed RAM swap | Verify `swapon --show`, keep existing disk swap intact |

**Exit check:** SSH access survives reboot; root and secondary SSDs are correctly identified; storage is mounted as intended and logs show no destructive action. Do not proceed until the storage situation is understood.

## Step 2 — Local LLM engines and models

Goal: GPU drivers first, engines second, models and UI after prerequisites.

| Order | Module | Default | Installation action | Setup/verification afterward |
| ---: | --- | :---: | --- | --- |
| 2.1 | `vulkan` | Yes | AMD firmware, Mesa, Vulkan | `vulkaninfo --summary`; verify Radeon 780M |
| 2.2 | `ollama` | Yes | Native Ollama localhost API | Verify Ollama service and `127.0.0.1:11434` |
| 2.3 | `llama` | Yes | Build llama.cpp with Vulkan | Select a real GGUF if you want to enable `llama-server` |
| 2.4 | `models` | Yes | Offer Qwen Coder model download | Explicit approval, model size/storage check |
| 2.5 | `webui` | Yes | Authenticated Open WebUI | First-login validation and Ollama connection |
| 2.6 | `benchmarks` | Yes | CPU/system/Vulkan diagnostic packages | Review temperatures and resource baseline |
| 2.7 | `llm_benchmark` | No | Actual llama-bench CPU vs Vulkan | Existing GGUF required; verify offload and tokens/sec |
| 2.8 | `llama_swap` | No | Install router executable, **no running service** | Supply and validate model mapping before manually starting |

**Exit check:** Ollama responds, a selected model generates text, GPU backend is verified rather than assumed, and the Open WebUI login works.

## Step 3 — Administration and development

Goal: Cockpit first, then its plugins; file managers and IDEs; then terminal/developer extras.

| Order | Module | Default | Installation action | Setup/verification afterward |
| ---: | --- | :---: | --- | --- |
| 3.1 | `cockpit` | Yes | Native Cockpit management | SSH tunnel to localhost HTTPS 9090 |
| 3.2 | `cockpit_storage` | No | Cockpit storage and package-update pages | Check only intended drives and admin permissions |
| 3.3 | `cockpit_ghsync` | Yes | GitHub Sync Cockpit plugin | `gh auth login` as normal user; no scheduled jobs |
| 3.4 | `cockpit_bookmarks` | Yes | Cockpit Bookmarks plugin | Confirm custom bookmarks remain intact |
| 3.5 | `cockpit_status` | No | Read-only UM780 status page | Inspect service states; not an application health guarantee |
| 3.6 | `filebrowser` | Yes | FileBrowser Quantum | Verify login and storage permissions; known read-only isolation issue |
| 3.7 | `codeserver` | Yes | Native code-server | Obtain generated password; login through SSH tunnel |
| 3.8 | `fish` | Yes | Fish shell | Run `fish`; login shell unchanged |
| 3.9 | `btop` | Yes | Terminal resource monitor | Run `btop` |
| 3.10 | `mc` | Yes | Midnight Commander | Run `mc` |
| 3.11 | `developer_tools` | No | rg, fdfind, fzf, lazygit, zoxide | Configure personal shell shortcuts if wanted |
| 3.12 | `opencode` | No | AI coding-agent CLI | User-level auth, no root-run agent |
| 3.13 | `agent_of_empires` | No | Tmux-based coding-agent manager | Start user sessions manually |
| 3.14 | `jupyterlab` | No | Localhost Jupyter notebooks | Authenticate with notebook token via tunnel |
| 3.15 | `ttyd` | No | Local-only browser terminal binary and unit | Explicit activation required; low-privilege service user |

**Exit check:** Cockpit and intended web apps are reachable **only over approved access paths**; auth works; no arbitrary terminal is exposed to LAN/WAN.

## Step 4 — Remote access and virtual desktop

Goal: configure networking and desktop access without accidentally publishing APIs or terminals.

| Order | Module | Default | Installation action | Setup/verification afterward |
| ---: | --- | :---: | --- | --- |
| 4.1 | `tailscale` | Yes | Tailscale native daemon | Explicit `sudo tailscale up` and identity enrollment |
| 4.2 | `secure_ingress` | No | Check enrolled Tailscale identity | Configure desired HTTPS Serve access manually; does not open ports |
| 4.3 | `vnc` | No | Optional per-user VNC template on display `:1` | Set password manually and enable user instance |
| 4.4 | `novnc` | No | Dedicated XFCE `:2`, generated VNC password, localhost noVNC service | Retrieve root-held password; forward `6080`; Bookmarks card added |

**Exit check:** Verify localhost bindings (including IPv6), authentication, intended remote reachability and reboot persistence. Remote VNC/terminal endpoints must not be opened directly to the internet.

## Step 5 — Monitoring, backups and automation

Goal: only after the foundational services are configured, add ongoing monitoring and recovery tools.

| Order | Module | Default | Installation action | Setup/verification afterward |
| ---: | --- | :---: | --- | --- |
| 5.1 | `backup_restore` | No | Restic CLI and *conditional* timer | Mount external/NAS repository, initialize encrypted Restic, **test restore** |
| 5.2 | `service_watchdog` | No | Five-minute service-state monitoring | Review journal; currently alerts only, **no auto-restart** |
| 5.3 | `uptime_kuma` | No | Native localhost Uptime Kuma | First-run admin, service probes and notification setup |
| 5.4 | `ups_wol` | No | Source preparation for Cockpit UPS/WOL | Validate power topology, use upstream preflight/dry-run; never auto-arm |
| 5.5 | `bookmark_sync` | No | Explicit final Cockpit Bookmarks rescan | Auto-bookmark merge is already enabled after ordinary apply runs |

**Exit check:** Monitoring reflects true failures; backup restore drill passes; Cockpit shows expected final bookmarks; no power-control actions are armed without separate verification.

## CLI commands

List every category and default/optional status **without changing anything**:

```sh
python3 install.py --list-stages
```

Review and run the currently preselected modules of one category at a time:

```sh
python3 install.py --plan --stage 1
sudo python3 install.py --apply --stage 1

python3 install.py --plan --stage 2
sudo python3 install.py --apply --stage 2

python3 install.py --plan --stage 3
sudo python3 install.py --apply --stage 3

python3 install.py --plan --stage 4
sudo python3 install.py --apply --stage 4

python3 install.py --plan --stage 5
sudo python3 install.py --apply --stage 5
```

**Crucial:** A `--stage N` operation selects only modules already marked on in your `config.json`. Step 5 therefore has **no default-selected modules** and does nothing until you explicitly select something. No optional module is silently enabled. To add optional software, use `--component NAME`:

```sh
sudo python3 install.py --apply --component hardware_health
sudo python3 install.py --apply --component novnc
sudo python3 install.py --apply --component backup_restore
```

To customize all five stages in one guided workflow:

```sh
sudo python3 install.py
```

Five sequential selection screens appear (whiptail if available, numbered terminal fallback). Checkboxes are grouped by stage, and Cancel at any step aborts the wizard. After selection, the plan shows the canonical installation order and each selected tool's manual setup notes. A final explicit confirmation is required before applying. No changes are made just by entering a selection screen.

A user can also combine stages with repeated `--stage N` arguments. `--stage` and `--component` cannot be combined; use the interactive TUI for mixed default-and-optional selections.

## Dependency / safety contract

- All 39 modules appear exactly once in the stage registry, `llmsetup/install_stages.py`.
- Installation execution follows stage number and the declared within-stage order, **not the order of CLI arguments**.
- The planning output warns about recommended predecessors that were **not selected in the same run**; they may already exist from an earlier installation. These notes are not assertions about live system state.
- The installer deliberately does **not** auto-install missing components, auto-format SSDs, enroll Tailscale, enable third-party agents, or initialize UPS power actions.
- Stage completion is **not** tracked across independent installations yet. Validate prior stages using `sudo python3 install.py --health` and physical checks before proceeding.
- The project is **pre-release**, with unresolved disk UUID, FileBrowser permission, supply-chain and bare-metal acceptance blockers. See [Known Issues](KNOWN_ISSUES.md).
