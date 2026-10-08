# Installation guide — Debian 13 / UM780 Pro

This is a **staged bare-metal procedure**, not a guarantee that an entire default-run succeeds. Review [known issues](KNOWN_ISSUES.md) first; pass the [acceptance checklist](ACCEPTANCE.md) before putting valuable data or remotely reachable services on this system.

## 1. System prerequisites

- Debian **13 / trixie**, `amd64 / x86_64`, systemd, working Internet/DNS and administrator `sudo` access.
- A spare console / KVM session or a second SSH session, especially when altering SSH and mounts.
- Enough space for application builds, release archives, Python wheels and models. Several downloads exceed 1 GB; check both `df -h` and `df -i`.
- In Debian APT sources, include `non-free-firmware` if `firmware-amd-graphics` cannot be located.
- Save a separate recoverable backup of **both** SSDs. Installer backups are config-only and not full-device snapshots.

Baseline inventory:

```sh
cat /etc/os-release
uname -m
systemctl is-system-running || true
lsblk -e7 -o NAME,PATH,SIZE,FSTYPE,UUID,MOUNTPOINTS
findmnt -no SOURCE,FSTYPE,UUID /
df -h /
lspci -nn | grep -Ei 'vga|display|amd' || true
ip -br a
```

Confirm the second NVMe's filesystem contents and UUID **before consenting** to any mount. The installer never formats an empty SSD: if the second disk has no supported existing filesystem, keep storage on the OS disk or create/restore a filesystem separately using your own recovery procedure.

## 2. Install project and inspect the plan

```sh
sudo apt update
sudo apt install -y python3 git
git clone https://github.com/ami3go/UM780-tui-postinstall.git
cd UM780-tui-postinstall
python3 -m unittest discover -s tests -v
python3 install.py --plan
```

The plan is **not an exhaustive filesystem diff**. It lists selected components and policy reminders. `--plan` can run without root and displays compatibility warnings when you run it on another OS or inside a VM/container.

## 3. Stage prerequisites, drivers and storage

Recommended order:

```sh
sudo python3 install.py --apply --component base
sudo python3 install.py --apply --component vulkan
vulkaninfo --summary
```

Confirm a **real AMD Radeon/RADV physical device**, not merely a software Vulkan renderer. Vulkan availability does not prove that LLM layers are offloaded.

For a second SSD, use the interactive storage module **without** `--yes`:

```sh
sudo python3 install.py --apply --component storage
findmnt /srv/llm-data
grep -n 'llm-postinstall' /etc/fstab
lsblk -f
```

When the target is an existing, unmounted ext4, XFS or Btrfs partition on a different non-root disk, the module shows candidates, asks for consent, requires the **full filesystem UUID**, writes one fstab line and mounts it at `/srv/llm-data`. Reject any unexpected device, mount, label or filesystem. If refused or none is eligible, models default to `/var/lib/llm-stack/models`. The selected model root is persisted in `/etc/llm-postinstall/storage.json`.

**Important:** The existing-mount shortcut accepts `/srv/llm-data` if already mounted; verify it is the correct disk with `findmnt -no SOURCE,UUID,TARGET /srv/llm-data` before running the module. This path is an outstanding safety limitation.

## 4. Install inference backends

```sh
sudo python3 install.py --apply --component llama
sudo python3 install.py --apply --component ollama
sudo systemctl status llm-ollama.service --no-pager
curl -fsS http://127.0.0.1:11434/api/tags
```

`llama` clones the then-current latest upstream release tag and compiles using `GGML_VULKAN=ON` into `/opt/llm-stack/llama.cpp/build`. It will **not** start `llm-llama.service` before a local GGUF has been chosen. Verify any third-party model file separately; this installer does not download GGUF files.

Put a trusted GGUF inside the active `models/gguf/` directory. For example, when you selected the second disk:

```sh
sudo python3 install.py --apply --component llama \
  --gguf /srv/llm-data/models/gguf/your-model.gguf
sudo systemctl status llm-llama.service --no-pager
```

Change path to `/var/lib/llm-stack/models/gguf/` when using the system disk. The selected file must already exist, be accessible by the `llama` service user, and be under that root.

Optionally download the default coding-oriented model into Ollama:

```sh
sudo python3 install.py --apply --component models
curl -fsS http://127.0.0.1:11434/api/tags
ollama list
```

The `models` module asks separately for confirmation unless you pass `--yes`. A successful pull does **not** prove AMD GPU usage. For evidence, compare CPU-only and Vulkan-enabled llama.cpp runs using the **same GGUF, prompt and sampling settings**; record tokens/sec and device logs.

## 5. Add web and administration services

Use one module at a time until each returns a meaningful result:

```sh
sudo python3 install.py --apply --component webui
sudo python3 install.py --apply --component cockpit
sudo python3 install.py --apply --component filebrowser
sudo python3 install.py --apply --component codeserver
sudo python3 install.py --apply --component tailscale
sudo python3 install.py --apply --component updates
sudo python3 install.py --apply --component benchmarks
```

All management listeners are **configured to bind to 127.0.0.1**; independently confirm with `ss -lntp`. In particular, the FileBrowser Quantum module must be treated as **potentially able to modify models** until its permissions are corrected. Do not expose it externally.

Retrieve generated login secrets locally as root (never copy them to tickets or logs):

```sh
sudo cat /etc/llm-postinstall/webui-admin-password
sudo cat /etc/llm-postinstall/filebrowser-admin-password
sudo cat /etc/llm-postinstall/codeserver-password
```

Open WebUI bootstrap credentials are `admin@llm.local` and the WebUI password above. The automated account creation applies only when its user database is empty. Confirm authentication manually on first start; do **not** assume a successful systemd status proves an account was created.

Tailscale does not enroll automatically:

```sh
sudo tailscale up
tailscale status
```

Use SSH forwarding for LAN or tailnet client access. See [Operations](OPERATIONS.md). Tailscale **Serve is not configured by the installer**.

## 6. Verify and reboot

```sh
sudo python3 install.py --health
sudo systemctl status llm-ollama.service llm-webui.service --no-pager
sudo ss -lntp | grep -E ':(11434|8081|3000|8082|8443|9090)\b' || true
sudo journalctl -u llm-ollama.service -u llm-webui.service -n 100 --no-pager
findmnt /srv/llm-data || true
```

The health tool's `WARN`/**`PENDING`** states can still yield exit status 0. A missing `llm-llama` service may be displayed as pending even if the real cause is a startup failure. Test inference and login flows directly.

After manual checks and a tested backup, reboot; verify mounts and services survive **two** restarts before considering installation accepted. Fill out [ACCEPTANCE.md](ACCEPTANCE.md) with dates, firmware/software versions and evidence.

## CLI synopsis

```text
python3 install.py [--config path.json] [--plan | --health | --apply]
                   [--component NAME ...] [--yes] [--gguf /absolute/path.gguf]
```

Without `--apply`, `--plan` or `--health`, the tool opens the interactive checklist, then asks to apply. On a minimal Debian host before installing `whiptail` it uses an in-terminal numbered selector.

`--yes` automatically accepts ordinary prompts, **including model pulls**, but never removes the storage UUID entry requirement. It is inappropriate for first-run storage configuration.

## Problems?

Start with [Known issues](KNOWN_ISSUES.md), then [Operations](OPERATIONS.md). Look for the first failure in `/var/log/llm-postinstall/` and `/var/lib/llm-postinstall/last-run.json`. An installer success status is not a substitute for on-device evidence.
