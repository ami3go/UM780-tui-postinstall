# Optional command-line tools, browser terminal, JupyterLab and remote desktop

Target: Debian 13 minimal / UM780 Pro. All installers are individually selectable in the post-install TUI or via `--component`. **No Docker is installed**. Several optional applications (Fish 4 and Agent of Empires) happen to be written in Rust, but neither replaces traditional GNU coreutils.

## Components and default selection

| TUI component | Installation method | Selected by default | Service behavior |
| --- | --- | --- | --- |
| `fish` | Debian `fish` package | Yes | Shell is installed; login shell **unchanged** |
| `btop` | Debian `btop` package | Yes | CLI, no daemon |
| `mc` | Debian `mc` package | Yes | Midnight Commander CLI, no daemon |
| `ttyd` | Verified upstream static release `1.7.7` | No | Installs local-only web terminal service, **disabled** |
| `agent_of_empires` | Verified upstream release `v1.17.2` | No | Installs `aoe` CLI; **no web server or agents started** |
| `jupyterlab` | Debian `jupyterlab` and kernel packages | No | Native non-root localhost-only systemd service |
| `vnc` | Debian TigerVNC + XFCE | No | Installs systemd user-instance template; **does not enable/start** |
| `novnc` | Debian noVNC + websockify | No | Installs localhost-only proxy unit; **does not enable/start** |

The headless default remains headless. Selecting `vnc` installs XFCE files and a virtual display service template, but no physical display manager or GUI login is enabled. The chosen JupyterLab module does run a localhost server.

## Install individually

```sh
cd UM780-tui-postinstall
git pull --ff-only
python3 install.py --plan --component fish --component btop --component mc
sudo python3 install.py --apply --component fish --component btop --component mc
sudo python3 install.py --apply --component ttyd
sudo python3 install.py --apply --component agent_of_empires
sudo python3 install.py --apply --component jupyterlab
sudo python3 install.py --apply --component vnc --component novnc
sudo python3 install.py --health
```

`--apply --component` never installs other optional modules automatically; install each needed prerequisite yourself. The installer uses verified upstream release downloads for ttyd and Agent of Empires: if checksum material is absent, the module **fails rather than bypassing verification**. The binary versions are intentionally fixed for repeatability; rerun does not silently upgrade a different executable.

## Fish, btop, Midnight Commander

Run these tools as your normal Linux user over SSH:

```sh
fish
btop
mc
```

Fish is an **interactive shell**, not a drop-in Bash replacement. The installer deliberately does **not** call `chsh`, alter `/etc/passwd`, rewrite interactive shell profiles or replace GNU tools.

## ttyd browser terminal

Debian 13 does not currently publish a `ttyd` binary package in its stable archive. The module downloads the pinned upstream `ttyd.x86_64` artifact, validates its GitHub release checksum, creates the unprivileged `llmterminal` account and writes `llm-ttyd.service`. It intentionally **does not start or enable it**.

The service runs Bash as a **dedicated, low-privilege account** (not as your normal administrative user), on `127.0.0.1:7681`. It accepts one browser client, enables terminal input, and checks WebSocket origins. There is no independent ttyd password: **SSH is the access-control boundary**.

To turn it on **after** verifying the unit:

```sh
sudo systemctl cat llm-ttyd.service
sudo systemctl enable --now llm-ttyd.service
sudo ss -lntp | grep ':7681'
```

From your PC:

```sh
ssh -N -L 7681:127.0.0.1:7681 USER@SERVER_IP
```

Browse `http://127.0.0.1:7681` on your client. Do not bind ttyd to `0.0.0.0` or expose a writable terminal directly on LAN/WAN. Stop with `sudo systemctl disable --now llm-ttyd.service`.

## Agent of Empires

The `agent_of_empires` component installs the `aoe` executable from pinned upstream `v1.17.2`, verified against the official release SHA256 manifest, plus tmux and git. The executable is made available as `/usr/local/bin/aoe`.

```sh
aoe --version
aoe
aoe agents
```

**Run as your normal login user, never root.** Existing Claude Code/Codex/OpenCode agent CLIs, authentication, working directories and user tmux sessions remain user-managed. This module does not install Docker, install AI agent CLIs, enable autonomous sessions, or start `aoe serve` (the optional web dashboard). If you enable the upstream web dashboard independently, bind it to loopback and provide authenticated/tunneled access; consult its own version-specific help.

## JupyterLab — notebook development service

The `jupyterlab` component installs Debian's JupyterLab packages, creates the isolated `llmjupyter` user and `/var/lib/llmjupyter/workspace`, and enables `llm-jupyterlab.service`. It binds to `127.0.0.1:8888`, **not all interfaces**. Jupyter's normal token login is retained. Notebook code runs under `llmjupyter`, not root.

```sh
sudo systemctl status llm-jupyterlab.service --no-pager
sudo journalctl -u llm-jupyterlab.service --no-pager -n 70
ssh -N -L 8888:127.0.0.1:8888 USER@SERVER_IP
```

Open `http://127.0.0.1:8888/lab` through the tunnel. Retrieve the login token from the private server-side Jupyter logs. **Treat notebook access as code execution access**; do not disable the token or publish port 8888. The separate Ollama service can be used via its localhost HTTP API from notebook code.

The packaged JupyterLab may install sizable Node/JavaScript-related Debian dependencies. This is a runtime application choice, not replacement of GNU coreutils.

## TigerVNC and noVNC — optional virtual XFCE desktop

`vnc` provisions `llm-vnc@.service` and a standalone **virtual display** at `:1` (normally `127.0.0.1:5901`). The template is intentionally disabled, and rejects root as the desktop user. Only an **existing ordinary Linux account** may run a VNC desktop. It requires an actual VNC password created interactively by that account.

Set up with a normal username (replace `YOUR_USER`):

```sh
# Run in that user's login shell, NOT via sudo as root:
tigervncpasswd

# Review the unit and confirm the target username:
sudo systemctl cat llm-vnc@.service
sudo systemctl enable --now llm-vnc@YOUR_USER.service
sudo systemctl status llm-vnc@YOUR_USER.service --no-pager
sudo ss -lntp | grep ':5901'
```

Only after VNC is authenticated and running, activate the browser proxy:

```sh
sudo systemctl cat llm-novnc.service
sudo systemctl enable --now llm-novnc.service
sudo ss -lntp | grep ':6080'
```

Both server listeners should be loopback-only. On your client:

```sh
ssh -N -L 6080:127.0.0.1:6080 -L 5901:127.0.0.1:5901 USER@SERVER_IP
```

Open `http://127.0.0.1:6080/vnc.html`; enter the VNC password when prompted. noVNC itself is **not a substitute for VNC authentication**. Its websocket proxy is local-only and there is no internet-facing HTTPS/reverse proxy configured.

Disable if not needed:

```sh
sudo systemctl disable --now llm-novnc.service
sudo systemctl disable --now llm-vnc@YOUR_USER.service
```

The VNC template is based on Debian 13's `tigervncserver` wrapper and `-xstartup /usr/bin/startxfce4`; validate actual display startup on your UM780 before relying on it. A virtual desktop does not require a monitor and may use **software rendering**, so it is not evidence of the Radeon 780M's Vulkan inference performance.

## Browser access summary

| Application | Default server listener | How to access |
| --- | --- | --- |
| ttyd (after manual enable) | `127.0.0.1:7681` | SSH port forward |
| JupyterLab (after installing module) | `127.0.0.1:8888` | SSH port forward + token |
| TigerVNC (after user setup and manual enable) | `127.0.0.1:5901` | SSH/VNC tunnel + VNC password |
| noVNC (after manual enable) | `127.0.0.1:6080` | SSH tunnel + VNC password |
| Agent of Empires | **No listener** | Local per-user TUI; web dashboard not enabled |

## Acceptance and limitations

The Python tests and GitHub Actions only validate configuration and mocked installation behavior. **None of these additions has been installed or browser-tested on the physical UM780 Pro.** The health check probes binaries/files and local ports but does not verify login, VNC startup, token security, desktop graphics, or agent sessions.

These optional modules currently have no uninstall/upgrade manager. Runtime versions of packaged tools follow Debian updates; the ttyd/AoE artifacts are intentionally pinned. The overall project remains pre-release due to unrelated existing blockers in [Known Issues](KNOWN_ISSUES.md).

References: [ttyd](https://github.com/tsl0922/ttyd), [Agent of Empires](https://github.com/agent-of-empires/agent-of-empires), [Debian TigerVNC](https://packages.debian.org/trixie/tigervnc-standalone-server), [Debian noVNC](https://packages.debian.org/trixie/novnc), [Debian JupyterLab](https://packages.debian.org/trixie/jupyterlab).
