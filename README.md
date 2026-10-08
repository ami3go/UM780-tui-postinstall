# UM780 Pro — Debian 13 headless LLM post-install

Modular, rerunnable TUI for a **bare-metal Minisforum UM780 Pro** (Radeon 780M, 64 GB RAM, 2 × 512 GB NVMe) running **Debian 13 minimal**. Installs native services with systemd. No Docker, no Rust coreutils replacement.

**Status:** pre-release. Unit-tested offline only; installation and AMD Vulkan inference have **not** yet been verified on the target machine. Read the plan and back up important data before applying.

## Quick start

```sh
sudo apt update
sudo apt install -y python3 git
git clone https://github.com/ami3go/UM780-tui-postinstall.git
cd UM780-tui-postinstall
python3 install.py --plan
python3 -m unittest discover -s tests -v
sudo python3 install.py
sudo python3 install.py --health
```

Choose modules interactively (whiptail checkbox when available; numbered fallback). Initial configuration is in [config.json](config.json). You can change the selected modules before applying them.

Install/re-run individual modules without opening the TUI:

```sh
sudo python3 install.py --apply --component base
sudo python3 install.py --apply --component vulkan
sudo python3 install.py --apply --component ollama
sudo python3 install.py --apply --component webui
sudo python3 install.py --health
```

`--plan` is read-only; `--health` performs non-destructive checks. `--yes` skips routine prompts, but **never bypasses the typed SSD UUID authorization**. Do not use unattended application for storage changes.

## Components

| Module | Installation / endpoint |
| --- | --- |
| `base` | Debian packages, SSH, whiptail |
| `storage` | Detect existing second-SSD filesystem; optionally mount after typed UUID confirmation |
| `vulkan` | AMD firmware, Mesa Vulkan, diagnostic tools |
| `llama` | Compile llama.cpp Vulkan; server on 127.0.0.1:8081 **only when GGUF configured** |
| `ollama` | Native Ollama, 127.0.0.1:11434 |
| `webui` | Native Open WebUI using Python 3.11/uv, 127.0.0.1:3000 |
| `models` | Opt-in Qwen2.5-Coder 7B pull, can consume multiple GB |
| `cockpit` | Cockpit on 127.0.0.1:9090 (HTTPS) |
| `filebrowser` | FileBrowser Quantum, 127.0.0.1:8082 |
| `codeserver` | code-server, 127.0.0.1:8443 |
| `tailscale` | Install signed repository and service; requires manual `tailscale up` |
| `updates` | Debian unattended security upgrades; no automatic reboot |
| `benchmarks` | CPU benchmark and GPU/system diagnostics |

Services use dedicated service accounts and systemd units. Upstream GitHub release assets are required to have SHA256 digests. Existing managed files are backed up before changes; unrelated files are not silently overwritten.

## Storage safety

The script **does not format, wipe, repartition, resize, or initialize disks**. It discovers only an *existing unmounted* ext4/XFS/Btrfs partition on a non-root disk. Ambiguous layouts (RAID, LVM, dm-crypt) are deliberately excluded.

If accepted, the installer requires entering the partition's full UUID; it adds a UUID-based `/etc/fstab` entry for `/srv/llm-data`, attempts the mount, and restores the previous fstab if mounting fails. Model data then goes under `/srv/llm-data/models`. Otherwise the fallback is `/var/lib/llm-stack/models`. A mountpoint already in use is left unchanged.

Inspect `lsblk -f` and take backups before selecting any partition. **Never accept storage operations based on disk numbering alone.**

## Access from LAN or Tailnet

The web interfaces and model APIs listen **on localhost only** by default; they do not become directly exposed on the LAN/Tailnet. Use SSH port forwarding (or configure a separately authenticated reverse proxy / Tailscale Serve after installation).

```sh
ssh -N -L 3000:127.0.0.1:3000 -L 11434:127.0.0.1:11434 \
  -L 9090:127.0.0.1:9090 -L 8443:127.0.0.1:8443 \
  -L 8082:127.0.0.1:8082 user@SERVER_IP
```

Use http://127.0.0.1:3000 for Open WebUI, https://127.0.0.1:9090 for Cockpit and http://127.0.0.1:8443 for code-server. After running `sudo tailscale up` on the server, you can SSH to its Tailscale IP using the same forwarding method. Never publish an unauthenticated Ollama API on the public internet.

## Secrets, logs and state

On initial setup, random passwords are written to root-only files and **reused on reruns**:

```sh
sudo cat /etc/llm-postinstall/webui-admin-password       # admin@llm.local
sudo cat /etc/llm-postinstall/filebrowser-admin-password # admin
sudo cat /etc/llm-postinstall/codeserver-password
```

Log directory: `/var/log/llm-postinstall/`. Last module statuses: `/var/lib/llm-postinstall/last-run.json`. Managed systemd units: `/etc/systemd/system/llm-*.service`. Backups: `/var/backups/llm-postinstall/`.

No automatic uninstall/rollback of apt packages or downloaded applications is promised. Do not commit credentials, logs, private keys or downloaded model files.

## llama.cpp GGUF

Ollama's managed model storage is separate from llama.cpp GGUF files. To start llama-server, place a verified GGUF under the selected `models/gguf` directory and rerun:

```sh
sudo python3 install.py --apply --component llama \
  --gguf /srv/llm-data/models/gguf/my-coder.gguf
```

Substitute `/var/lib/llm-stack/models/gguf/` if the second disk was not mounted. Check `vulkaninfo --summary`, then systemd logs and `llama-bench` to confirm **real** GPU offload. Ollama on this APU may use CPU despite the presence of Radeon 780M; ROCm support is not assumed.

## Verification

```sh
python3 -m compileall -q .
python3 -m unittest discover -s tests -v
python3 install.py --plan
sudo python3 install.py --health
sudo journalctl -u llm-ollama -u llm-webui -n 80 --no-pager
sudo ss -lntp | grep -E '11434|8081|3000|8082|8443|9090'
```

After a real installation, validate mount persistence across reboot, no unexpected open network listeners, WebUI and code-server authentication, Qwen response generation, GPU offload versus CPU-only tok/s, and rerunning one module without losing state.

**The offline suite does not prove on-device installation success.** See [the target acceptance checklist](docs/ACCEPTANCE.md).

## Architecture

```text
install.py                   CLI entry point
llmsetup/cli.py              TUI, plan, per-module execution and run-state
llmsetup/core.py             Command runner, safe file writes, managed accounts
llmsetup/assets.py           Verified downloads
llmsetup/storage.py          Safe existing-partition detection and UUID mounting
llmsetup/component_base.py   Base dependencies, Vulkan, llama.cpp
llmsetup/component_llms.py   Ollama, Open WebUI and Qwen model
llmsetup/component_addons.py Cockpit, Quantum, code-server, Tailscale, updates
llmsetup/components.py       Module registry
llmsetup/health.py           Read-only diagnostics
tests/                       Unittest safety and workflow coverage
.github/workflows/           CI on push and pull request
```

Official references: [Debian packages](https://packages.debian.org/trixie/) · [llama.cpp Vulkan](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md) · [Ollama](https://github.com/ollama/ollama) · [Open WebUI](https://docs.openwebui.com/) · [Tailscale](https://tailscale.com/kb).
