# Operator runbook

This guide applies **after** reviewing [installation](INSTALLATION.md), [security](SECURITY.md), and [known issues](KNOWN_ISSUES.md). Commands are intended for an administrator on the Debian 13 host. The project is not yet on-hardware validated.

## 1. Start, stop and inspect services

```sh
sudo systemctl status llm-ollama.service llm-webui.service --no-pager
sudo systemctl status llm-llama.service llm-filebrowser.service llm-codeserver.service --no-pager
sudo systemctl status cockpit.socket tailscaled.service --no-pager
sudo journalctl -u llm-ollama.service -n 100 --no-pager
sudo journalctl -u llm-webui.service --since '1 hour ago' --no-pager
```

To restart one component manually:

```sh
sudo systemctl restart llm-ollama.service
sudo systemctl stop llm-webui.service
sudo systemctl start llm-webui.service
sudo systemctl enable --now cockpit.socket
```

**Note:** `llm-llama.service` is not created until a valid local GGUF is configured with `--gguf` or `llama_model_path`. Rerunning a module may restart its service and modify configuration; inspect logs afterward.

For a high-level local check:

```sh
sudo python3 install.py --health
sudo ss -lntp
sudo systemctl --failed
```

Status meanings:
- `PASS`: that probe's limited condition was met; may only mean a TCP port is open.
- `WARN`: e.g. service inactive, port closed, Vulkan absent, storage path missing or Tailscale not enrolled.
- `FAIL`: e.g. incorrect OS/host or a monitored service port listening on wildcard address.
- `PENDING`: llama.cpp service absent/inactive (the code does not distinguish misconfiguration from service failure).

**Do not treat exit status 0 as a green deployment gate.** `--health` exits nonzero for `FAIL` only, while `WARN` and `PENDING` can leave exit code 0. The health probe does **not** authenticate, run inference or verify AMD GPU offload.

## 2. Access services from a client

From another computer on your trusted LAN:

```sh
ssh -N -L 3000:127.0.0.1:3000 \
  -L 9090:127.0.0.1:9090 \
  -L 8082:127.0.0.1:8082 \
  -L 8443:127.0.0.1:8443 \
  -L 11434:127.0.0.1:11434 user@SERVER_IP
```

Access:
- `http://127.0.0.1:3000` — Open WebUI.
- `https://127.0.0.1:9090` — Cockpit; check its certificate.
- `http://127.0.0.1:8082` — FileBrowser Quantum; **write-risk, restrict account**.
- `http://127.0.0.1:8443` — code-server.
- `http://127.0.0.1:11434/api/tags` — unauthenticated Ollama API **over the SSH tunnel only**.
- To forward llama.cpp separately use `-L 8081:127.0.0.1:8081` after GGUF setup.

SSH forwarding does not grant new network listeners on the server. Tailscale enrollment is a separate operation:

```sh
sudo tailscale up
tailscale status
tailscale ip -4
```

After enrollment, substitute the machine's tailnet IP/hostname in the `ssh` command. The installer does not configure Tailscale Serve or Funnel; **do not enable Funnel for the Ollama API**. Do not use unauthenticated endpoints over raw LAN/WAN.

## Automatic Cockpit Bookmarks entries

By default, an apply run adds missing app cards to an installed Cockpit Bookmarks plugin. On-demand ttyd application cards are created only when their binaries are installed and require SSH-forwarded browser access; app web links are to the browser's `127.0.0.1` (not the server LAN IP). The operation preserves existing entries and writes a backup when it changes the JSON. Run `sudo python3 install.py --apply --component bookmark_sync` to rescan, or set `auto_bookmarks` to `false` to disable the post-hook. See [Bookmarks auto-configuration](BOOKMARKS_AUTO.md) for port forwarding, recovery and limitations.

## Turnkey noVNC desktop

Selecting the `novnc` module generates an eight-character random VncAuth password (root-only path `/etc/llm-postinstall/novnc-vnc-password`), sets up the dedicated `llmvnc` user and enables two localhost-only services: `llm-novnc-vnc.service` (VNC display `:2`, TCP 5902) and `llm-novnc.service` (browser TCP 6080). When Cockpit Bookmarks is installed, its noVNC Desktop card is added during automatic post-install synchronization. To log in, forward 6080 over SSH and use `sudo cat /etc/llm-postinstall/novnc-vnc-password` locally. NoVNC authentication needs the password only; do not publish the secret in Bookmarks. [Turnkey noVNC instructions](NOVNC_DESKTOP.md).

## Optional terminal, notebook and desktop tools

The `fish`, `btop` and `mc` packages are CLI-only. The optional `ttyd`, `agent_of_empires`, `jupyterlab`, `vnc` and `novnc` components are documented in [Optional Tools](OPTIONAL_TOOLS.md). Ttyd and the user-specific VNC template require manual enablement; **novnc now autoconfigures a separate dedicated desktop**, with root-only generated credentials and no public listeners. VNC/noVNC should not be exposed beyond localhost; a Jupyter notebook is a remote code execution interface gated by its token and SSH.

## Cockpit GitHub Sync and Bookmarks

The optional `cockpit_ghsync` and `cockpit_bookmarks` modules add Cockpit pages, not extra always-on web listeners. Authenticate with `gh auth login` **as the Cockpit login user**, then use `ghsync check` before cloning repositories. Bookmarks application/terminal launchers are powerful remote execution features; their startup is opt-in, and their bindings must be checked individually. See [Cockpit plugins](COCKPIT_PLUGINS.md) for commands and configuration paths.

## 3. Authentication and credentials

Initial generated secrets are stored under `/etc/llm-postinstall/` (root-only). View individually:

```sh
sudo cat /etc/llm-postinstall/webui-admin-password
sudo cat /etc/llm-postinstall/filebrowser-admin-password
sudo cat /etc/llm-postinstall/codeserver-password
```

Open WebUI user bootstrap is on **first startup with an empty database only**. Its admin email defaults to `admin@llm.local`. If a database already exists, do not assume the contents of `webui-admin-password` are valid; change credentials through the application and follow upstream account recovery guidance.

Do not paste credentials into public issues, screenshots, CI logs or shell command lines. Changing a generated secret file by hand **does not guarantee rotating credentials inside the application database**. A managed credential-rotation command has not been implemented.

## 4. Test model availability and GPU backend

```sh
curl -fsS http://127.0.0.1:11434/api/tags
ollama list
vulkaninfo --summary
ls -l /dev/dri/ 2>/dev/null || true
sudo journalctl -u llm-ollama.service --since '30 minutes ago' --no-pager
sudo journalctl -u llm-llama.service --since '30 minutes ago' --no-pager
```

One-shot response test (may take time and use significant RAM):

```sh
ollama run qwen2.5-coder:7b 'Write a Python function that returns Fibonacci numbers.'
```

`ollama list` and `vulkaninfo` are not evidence that Ollama uses the Radeon GPU. For a valid acceleration comparison, run the same **local GGUF** with llama.cpp and `llama-bench` both with GPU layers enabled and disabled; record tokens/sec, memory, CPU/GPU load, system temperature and driver info. Example locations:

```sh
/opt/llm-stack/llama.cpp/build/bin/llama-bench -m /srv/llm-data/models/gguf/your-model.gguf -ngl 99
/opt/llm-stack/llama.cpp/build/bin/llama-bench -m /srv/llm-data/models/gguf/your-model.gguf -ngl 0
```

Only run after checking `llama-bench --help` for your installed version. Substitute default system-disk path if needed; benchmark arguments can change across upstream versions.

The `benchmarks` installer writes `/var/log/llm-postinstall/benchmark-report.txt` containing CPU/system diagnostics. This is **not** a Qwen throughput benchmark.

## 5. Storage checks and data backup

```sh
lsblk -e7 -o NAME,PATH,SIZE,FSTYPE,UUID,MOUNTPOINTS
findmnt -no SOURCE,UUID,FSTYPE,TARGET /srv/llm-data || true
df -h /srv/llm-data /var/lib/llm-stack 2>/dev/null || true
sudo cat /etc/llm-postinstall/storage.json
grep -n -A1 'llm-postinstall managed' /etc/fstab
```

The installer does not back up model weights, service databases, code-server workspace, or disk partitions. Arrange **external** backups for:
- Model directory (either `/srv/llm-data/models` or `/var/lib/llm-stack/models`).
- `/var/lib/openwebui/`, `/var/lib/filebrowser/` and `/var/lib/codeserver/`.
- `/etc/llm-postinstall/`, `/etc/fstab`, `/etc/systemd/system/llm-*.service` and the Cockpit override.

Stop services before backing up live SQLite/application state to avoid inconsistent copies; use application-provided exports where available. Encrypt exported secrets and keep an offline recoverable copy.

## 6. Repeated runs and updates

```sh
git pull --ff-only
python3 install.py --plan --component ollama
sudo python3 install.py --apply --component ollama
sudo python3 install.py --health
```

The `--apply --component` path reruns that component without a component-selection menu. It **does not** resolve dependencies, coordinate concurrent installers, guarantee an in-place upgrade or roll back prior steps. Some modules reuse existing binary versions; others pull latest or install packages again. Treat each execution as a change window. Do not run two copies concurrently.

Security-upgrade module only configures unattended Debian security packages and timers. It does not provide unattended updates for Ollama, llama.cpp source, WebUI, FileBrowser Quantum or code-server.

## 7. Troubleshooting

Check the first failing module:

```sh
sudo cat /var/lib/llm-postinstall/last-run.json
sudo ls -lth /var/log/llm-postinstall/
sudo tail -n 100 /var/log/llm-postinstall/install-*.log
sudo journalctl -b -p warning --no-pager
```

| Symptom | First check |
| --- | --- |
| `apt-get` cannot find AMD firmware | Debian `non-free-firmware` in sources; `apt update` |
| Vulkan lists only software renderer | AMD firmware, `lsmod | grep amdgpu`, render node groups, `vulkaninfo --summary` |
| Ollama port closed | `systemctl status llm-ollama`, `journalctl` and `ss` |
| WebUI port closed | Python/uv install success, unit status, first-start logs |
| WebUI password rejected | Was DB already initialized? Generated password is initial-bootstrap only |
| llama server missing | GGUF was not selected; run module with `--gguf` |
| Storage selected but not mounted | `findmnt`, `mount -a` **only after reviewing fstab**, filesystem UUID/health |
| FileBrowser permission denied or unexpectedly writable | Actual filesystem ACL/group, current source permissions; see [Security](SECURITY.md) |
| `--health` reports no failure but app unusable | It only tests coarse service/port predicates; test endpoint and authentication |
| Tailscale disconnected | `tailscale status` then deliberate `sudo tailscale up` |

## 8. Manual recovery / rollback boundaries

There is no transactional rollback or `uninstall` command. `Runner.write` can create backups of files it replaces under `/var/backups/llm-postinstall/`; it does not snapshot the whole system or uniformly manage all commands.

For service trouble, stop the *specific* affected service, check journal, restore a known-good managed config backup **after inspecting the diff**, and run `systemctl daemon-reload`. Do not blindly replace `/etc/fstab` while mounted volumes are busy, and do not unmount a disk with active inference or file-manager processes.

Never format or wipe a device to fix a mount problem. Escalate unknown storage or authentication failures rather than applying destructive workaround commands.


## Staged component operations

Run `python3 install.py --list-stages` to review all categorized software. `sudo python3 install.py --apply --stage N` applies only currently default-selected components of phase N; it does not silently install optional services. `--plan --stage N` is read-only and includes manual setup and prerequisite guidance; `--health --stage N` provides the existing read-only checks for the same selection. Use [the five-stage guide](INSTALL_STAGES.md) to validate exit criteria before moving to the next phase.


## Installed/configured inventory

Run `python3 install.py --inventory` or `python3 install.py --inventory --stage 3` for a read-only overview of installed binaries/packages, managed configuration and current service activity. JSON is available as `python3 install.py --inventory --json`. The installation plan and staged TUI include these current statuses, and each successful apply run records a post-install observation in `/var/lib/llm-postinstall/last-run.json`. Inventory is not a service login, GPU offload or backup restore test. See [inventory guide](INSTALL_INVENTORY.md).
