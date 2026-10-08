# Configuration and CLI reference

This file describes the **current code behavior**, not proposed settings. The single built-in default is [../config.json](../config.json). Always run `python3 install.py --plan` before modifying or applying it.

## JSON fields

| Key | Current default | Used by code? | Notes |
| --- | --- | --- | --- |
| `target_os` | `"debian-13"` | Yes | Must match exactly, not a general-purpose distro selector |
| `host` | `"bare-metal"` | Yes | VMs and containers rejected by preflight |
| `components` | 18 selected; 21 additional optional | Yes | TUI initially checks each item; see component order below |
| `backup_repository` | Not set | Optional | Existing separately mounted Restic repository path; until configured module only installs CLI |
| `auto_bookmarks` | `true` | Yes | After an apply run, merge missing application cards if Cockpit Bookmarks is installed; disable to opt out |
| `model` | `"qwen2.5-coder:7b"` | Yes | For `models`, only prefixes `qwen2.5-coder:` and `qwen3-coder:` pass the current basic check |
| `webui_bind` | `"127.0.0.1"` | **No** | Informational only; listener address is hardcoded in the service |
| `llama_model_path` | `""` | Yes | Optional existing GGUF path under selected `models/gguf/`; also set by `--gguf` |
| `model_storage` | `"/var/lib/llm-stack/models"` | Yes | Used unless valid `/etc/llm-postinstall/storage.json` overrides it |
| `tunnel_note` | Descriptive text | **No** | Informational, not a network policy |

Do **not** expect changing `webui_bind` or `tunnel_note` to change network listeners. Editing `model_storage` to an arbitrary path is **not** a supported safety-preserving way to mount disks. The current JSON parser does not fully validate arbitrary model paths on first run; use the interactive storage module instead.

## Five prioritized installation stages

The canonical component order is defined in `llmsetup/install_stages.py` and drives **both TUI categories and actual execution order**. Modules are grouped as follows:

| Step | Stage name | Component order |
| ---: | --- | --- |
| 1 | Essential system and data safety | `preflight`, `base`, `config_snapshot`, `storage`, `hardware_health`, `updates`, `zram` |
| 2 | Local LLM engines and models | `vulkan`, `ollama`, `llama`, `models`, `webui`, `benchmarks`, `llm_benchmark`, `llama_swap` |
| 3 | Administration and development | `cockpit`, `cockpit_storage`, `cockpit_ghsync`, `cockpit_bookmarks`, `cockpit_status`, `filebrowser`, `codeserver`, `fish`, `btop`, `mc`, `developer_tools`, `opencode`, `agent_of_empires`, `jupyterlab`, `ttyd` |
| 4 | Remote access and virtual desktop | `tailscale`, `secure_ingress`, `vnc`, `novnc` |
| 5 | Monitoring, backups and automation | `backup_restore`, `service_watchdog`, `uptime_kuma`, `ups_wol`, `bookmark_sync` |

The 18 default-selected components in `config.json` remain unchanged. Before installation use `--inventory` to inspect actual package/binary presence separately from managed configuration; `--inventory --stage N` includes all software in that stage regardless of whether it was selected by default. For precise rules and limitations see [Inventory](INSTALL_INVENTORY.md). The other 21 modules are **unchecked** and are not selected by `--stage N`; select them individually with `--component` or in the staged TUI.

`--stage 1` is the suggested starting point for the first controlled deployment, followed by steps 2–5. Step 5 currently has no default-selected modules. `--stage` is repeatable and can be used with `--plan`, `--health`, or `--apply`. The two selectors `--stage` and `--component` cannot be combined in one command. For a mixed custom selection use the interactive TUI.

**Prerequisites are advisory, not a dependency installer.** The plan labels recommended earlier modules not chosen for the current invocation as "Verify previously installed prerequisites" because they could have been installed in an earlier stage. No automatic prerequisite installation, storage formatting, power-control arm, or external network publishing occurs. See [Staged installation](INSTALL_STAGES.md) for the full table, operator setup actions, and exit criteria.


## CLI flags

| Flag | Actual behavior |
| --- | --- |
| `--config PATH` | Load another JSON file. Not a file editor or schema validator |
| `--plan` | Print high-level plan; do not apply installations or mounts |
| `--health` | Read-only service, Vulkan, mount and port checks (details in [Operations](OPERATIONS.md)) |
| `--apply` | Skip module checklist and run chosen modules; root required |
| `--component NAME` | Select one module; repeat flag for additional modules; runs in canonical priority order |
| `--inventory` | Read-only local installed/configured/running scan; all 39 modules by default, or filter by `--stage`/`--component` |
| `--json` | Machine-readable output only with `--inventory`; no passwords or tokens included |
| `--stage N` | Select only default-enabled software in stage N (1–5); repeatable; cannot combine with `--component` |
| `--list-stages` | Print all five categories, default/optional status and software descriptions; read-only |
| `--yes` | Accept ordinary confirmation prompts including model downloads; **still must type UUID** if mounting |
| `--gguf PATH` | Override the model path for the current `llama` invocation; existing `.gguf` under current model root |
| `-h`, `--help` | Show CLI help |

Examples:

```sh
python3 install.py --inventory
python3 install.py --inventory --json
python3 install.py --list-stages
python3 install.py --plan --stage 1
python3 install.py --plan
python3 install.py --plan --component storage --component llama
sudo python3 install.py --apply --component base
sudo python3 install.py --apply --component ollama --component webui
sudo python3 install.py --apply --component models  # opt-in download prompt
sudo python3 install.py --health
```

For automatic application bookmarks, see [Bookmarks auto-configuration](BOOKMARKS_AUTO.md). It is controlled by the separate `auto_bookmarks` JSON setting; `bookmark_sync` can also be called explicitly.

For the turnkey noVNC virtual desktop, separate root-only credential file, automatic systemd startup and generated bookmark, see [noVNC Desktop](NOVNC_DESKTOP.md).

For headless tools and optional browser/desktop services, see [Optional tools](OPTIONAL_TOOLS.md). These five remote-facing optional modules are not selected by default; enable only after reviewing their separate authentication boundaries.

For the Cockpit extensions, see [Cockpit plugins](COCKPIT_PLUGINS.md). Neither module logs into GitHub, starts sync jobs, or enables terminal launchers automatically.

## Service endpoints and credentials

| Service | Bind | Scheme | Credential |
| --- | --- | --- | --- |
| Ollama API | `127.0.0.1:11434` | HTTP | **No API authentication** |
| llama.cpp API (after GGUF) | `127.0.0.1:8081` | HTTP | No auth configured |
| Open WebUI | `127.0.0.1:3000` | HTTP | Bootstrap `admin@llm.local` (first empty DB only) |
| FileBrowser Quantum | `127.0.0.1:8082` | HTTP | `admin`, generated password |
| code-server | `127.0.0.1:8443` | HTTP | Generated password |
| Cockpit | `127.0.0.1:9090` | HTTPS | Existing Linux account / PAM |
| GitHub Sync | Cockpit page (no extra TCP port) | Cockpit | Uses logged-in Linux user's `gh` authentication |
| Bookmarks | Cockpit page (no extra TCP port until optional launchers) | Cockpit | Admin required to edit config; launcher settings must be reviewed |
| Tailscale | No web UI from installer | N/A | Must enroll manually |
| ttyd | `127.0.0.1:7681`, after explicit enable | HTTP/WebSocket | No app password; access via SSH tunnel, low-privilege service account |
| JupyterLab | `127.0.0.1:8888` | HTTP | Per-instance token, SSH port forwarding |
| TigerVNC | `127.0.0.1:5901`, after manual setup | VNC | VNC password; ordinary Linux account |
| noVNC | `127.0.0.1:6080` when novnc module installed | HTTP/WebSocket | Generated root-only VNC password; dedicated backend at `127.0.0.1:5902` |

All locations are host-side; SSH forward to view from another machine. The listener bindings are intended and **must be verified** with `ss -lntp` after installation. FileBrowser's current configured model source is **not reliably read-only**.

## Persistent locations

| Path | Purpose |
| --- | --- |
| `/opt/llm-stack/cockpit-ghsync-src/` | Pinned GitHub Sync source revision |
| `/etc/llm-postinstall/cockpit-ghsync.json` | Root-only installed plugin manifest / SHA256 hashes |
| `/etc/cockpit/cockpit-bookmarks.json` | Persistent Bookmarks user configuration |
| `/opt/llm-stack/llama.cpp/` | Source/build |
| `/opt/llm-stack/ollama/` | Versioned Ollama binary distribution |
| `/opt/llm-stack/open-webui/venv/` | Open WebUI virtual environment |
| `/opt/llm-stack/uv-python/` | uv-managed Python install |
| `/var/lib/llm-stack/models/` | Default root for Ollama and GGUF files |
| `/srv/llm-data/models/` | Model root when existing second-disk filesystem mounted |
| `/var/lib/ollama/` | Ollama user's service state |
| `/var/lib/openwebui/` | Open WebUI persistent data |
| `/var/lib/filebrowser/` | FileBrowser Quantum data/config/database |
| `/var/lib/codeserver/` | code-server workspace/user data |
| `/etc/llm-postinstall/` | Generated env files, passwords and storage decision |
| `/etc/systemd/system/llm-*.service` | Installer-managed units |
| `/etc/systemd/system/cockpit.socket.d/llm-postinstall.conf` | Cockpit loopback socket override |
| `/var/log/llm-postinstall/` | Installer logs and benchmark diagnostic |
| `/var/lib/llm-postinstall/last-run.json` | Last per-component result summary |
| `/var/backups/llm-postinstall/` | Backups of modified files handled by `Runner.write` |
| `/var/cache/llm-postinstall/` | Verified upstream binary asset cache |

## When config changes take effect

- Rerun the **relevant component**; editing `config.json` alone does nothing.
- `storage.json` overrides `model_storage` for later invocations. Inspect existing `findmnt /srv/llm-data` and don't edit this state file by guesswork.
- The llama GGUF env file is written only after selecting an existing file. Ollama models do not automatically become llama.cpp GGUFs.
- Open WebUI's autogenerated admin is a **first empty-database bootstrap only**; changing its generated secret later does not reliably reset an existing application account.
- The code does not have a managed uninstall, config migration, or all-components upgrade command. See [Operations](OPERATIONS.md).

## Version strategy

llama.cpp, Ollama, uv and code-server are selected from current upstream release APIs at install time (not fixed for reproducible deployments). FileBrowser Quantum is pinned to `v1.5.6-stable`. Python packages installed through uv are not version-locked. To reproduce a machine, capture exact binaries, git commit IDs, Python packages and model checksums manually as described in [Acceptance](ACCEPTANCE.md).
