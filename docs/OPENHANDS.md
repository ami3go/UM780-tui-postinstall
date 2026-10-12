# OpenHands (optional Docker-based coding agent)

This module is an **explicit exception** to the repository's otherwise native-app-only design. It does not change the 18 default selected modules. Selecting it creates a Docker daemon (if absent), a localhost-only OpenHands GUI, an agent sandbox image, and optionally a Docker-bridge-only relay to the existing native Ollama service. OpenHands/Docker have substantial host privileges through the Docker socket: use **single-user, trusted repositories only**.

## Installation

Read this document before enabling the module; back up relevant data. Install Ollama in stage 2 first if you want local inference:

```bash
sudo python3 install.py --apply --component ollama
sudo python3 install.py --plan --component openhands
sudo python3 install.py --apply --component openhands
sudo python3 install.py --inventory --component openhands
sudo python3 install.py --health --component openhands
```

Two separate interactive approvals are required when Docker is absent: OpenHands' Docker-root risk and installation of the `docker.io` package. `--yes` deliberately accepts them, so only use it after explicitly selecting `openhands` and reviewing this document. The Debian `docker.io` package is used; no curl-to-shell bootstrap or docker-group enrollment. When Docker already exists, the installer uses it. The module may pull sizeable versioned images. A systemd service launches the container on reboot.

`config.json` includes non-secret settings. Optional example:

```json
"openhands": {
  "port": 3002,
  "ollama_bridge": true,
  "local_model": "qwen2.5-coder:7b"
}
```

`ollama_bridge: false` disables a *previously managed* relay when rerunning the module; an unowned systemd unit is never overwritten. Port 3002 is reserved as the default so Open WebUI keeps 3000 and Uptime Kuma keeps 3001. Change the port only to an unused local port (a previous instance's port must be stopped before changing).

## Connect to GUI (SSH tunnel; no public network binding)

```bash
ssh -N -L 3002:127.0.0.1:3002 user@SERVER_IP
```

Open `http://127.0.0.1:3002`. The service is **single-user** and does not enable extra authentication; never expose port 3002 to the Internet or a shared LAN. Docker itself has root-equivalent control through the mounted `/var/run/docker.sock`. Agent sandbox containers should be treated as untrusted-code execution. Do not mount your whole home directory or secrets into an agent sandbox. GitHub connectivity/auth is set up by the user in the OpenHands UI.

## Choose model in OpenHands Settings → LLM

| Provider | Custom model example | Base URL | API key |
| --- | --- | --- | --- |
| OpenAI GPT | `openai/gpt-4.1` (or supported model) | Provider default | Your separately billed **OpenAI API** key |
| Anthropic Claude | `anthropic/claude-sonnet-4-20250514` (or supported model) | Provider default | Your separately billed **Anthropic API** key |
| Existing Ollama | `openai/qwen2.5-coder:7b` | `http://host.docker.internal:11435/v1` | `local-key` (dummy) |

Model IDs are **examples, not a promise** that a specific model is currently available or compatible. Choose a model available in your provider account. A ChatGPT or Claude chat subscription is not an API key. The installer deliberately **does not collect or write real cloud keys**, place keys on the command line, or claim to perform provider login.

The local relay binds only to the Docker default bridge gateway (e.g. `172.17.0.1:11435`) and forwards to host `127.0.0.1:11434`; Ollama itself remains loopback-only for local user tools. **Other containers on the default Docker bridge can call this unauthenticated relay**; avoid untrusted containers on that network, or set `ollama_bridge: false`. There is no host/LAN listener on `0.0.0.0:11435`. Verify the active firewall/network before production usage.

Local agentic models need an unusually long context window: upstream recommends at least 22k tokens, preferably 32k, and a capable tool-calling model. The repo's small default `qwen2.5-coder:7b` is a starter, not a guarantee of reliable OpenHands tool-use. Set an appropriate `OLLAMA_CONTEXT_LENGTH` in the native Ollama service separately and test RAM/performance; this module does not silently change the existing Ollama service.

## Multi-model routing limitations

Installation exposes **three provider choices**, but the local GUI selects one active model configuration at a time. It **does not** automatically delegate coding, review, and testing between GPT, Claude and Ollama. Implementing automatic task-based routing requires a separate OpenHands SDK workflow with delegation, escalation rules, test gates, and API budgets; it is not provided or advertised by this installer.

## Verification and operations

```bash
sudo systemctl status llm-openhands.service llm-openhands-ollama-bridge.service
sudo journalctl -u llm-openhands.service -n 100 --no-pager
docker ps --filter name=llm-openhands
curl -I http://127.0.0.1:3002/
sudo docker network inspect bridge
sudo ss -lntp | grep -E ':3002|:11435|:11434'
```

If the Ollama bridge was disabled, its service will be inactive or absent. `--health` only checks service and TCP reachability; **it does not test API auth, end-to-end agent tool use, model context, or repository sandbox safety**. The exact pinned images can be updated through reviewed code changes. Persistent app data is under `/var/lib/llm-openhands`; installation does not prune Docker images, delete user data, or remove existing Docker services.

Upstream versioned CLI/GUI reference (checked October 2026): https://docs.openhands.dev/openhands/usage/run-openhands/local-setup
Local LLM guide: https://docs.openhands.dev/openhands/usage/llms/local-llms
