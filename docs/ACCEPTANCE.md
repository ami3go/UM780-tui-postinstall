# Bare-metal acceptance checklist (Debian 13 / UM780 Pro)

The development container can run mocked tests, but it cannot exercise the UM780 Pro GPU, network, SSDs, or systemd units. Perform these checks **on the target machine** before treating the installer as production-ready.

## Before apply

- [ ] Back up both NVMe drives; confirm the backup can be restored
- [ ] Confirm Debian 13, x86_64, systemd, sudo and working SSH
- [ ] `python3 install.py --plan` lists exactly the intended modules
- [ ] `lsblk -f` and `findmnt /` unambiguously distinguish root disk from second disk
- [ ] Record the UUID, filesystem and content of the existing second SSD
- [ ] Verify Debian `non-free-firmware` is enabled for Radeon firmware if needed
- [ ] Keep a console or second SSH connection available in case services change

## During install

- [ ] Model storage selection refuses root-disk partitions and already-mounted volumes
- [ ] Declining a second-SSD mount leaves `/etc/fstab` unchanged
- [ ] Typing the wrong UUID prevents changes
- [ ] Correct UUID approval mounts the **existing** filesystem without formatting or repartitioning
- [ ] Component failure records its name and log path, stops by default
- [ ] Logs omit secret commands/passwords; root-only files have 0600 permissions
- [ ] Rerunning the `base` and `storage` modules does not destroy or remount unrelated data

## GPU and inference

- [ ] `vulkaninfo --summary` reports an AMD RADV physical device, not only a software driver
- [ ] llama.cpp config uses `GGML_VULKAN=ON`, builds successfully and produces `llama-server`/`llama-bench`
- [ ] With GGUF configured, llama-server responds on localhost:8081
- [ ] Benchmark model tokens/second with GPU offload enabled and CPU-only, compare results
- [ ] Ollama responds to `curl -fsS http://127.0.0.1:11434/api/tags`
- [ ] Qwen coder model downloads, loads and generates a correct test response
- [ ] Open WebUI lists the Ollama model and cannot be accessed without authentication
- [ ] llama.cpp service remains disabled or pending without a GGUF, not restarting endlessly

## Services and network

- [ ] Cockpit works over forwarded HTTPS 9090
- [ ] FileBrowser Quantum works with an authenticated admin account
- [ ] code-server works over forwarded HTTP 8443 with authentication
- [ ] `ss -lntp` confirms localhost-only bindings for 11434, 8081, 3000, 8082, 8443, 9090
- [ ] Tailscale requires explicit enrollment and does not silently publish services
- [ ] SSH forwarding works over LAN and, after enrollment, through Tailscale
- [ ] Automatic Debian security updates are enabled with auto-reboot disabled
- [ ] `sudo python3 install.py --health` shows no unexpected FAIL states

## Durability

- [ ] Reboot twice; confirm UUID mount, SSH and managed services recover
- [ ] `/etc/llm-postinstall/` secrets are unchanged across reruns
- [ ] Selected modules rerun without overwriting unrelated configs
- [ ] Stop/start services through systemd; inspect `journalctl` for errors
- [ ] Test actual user workloads, thermal behavior, RAM consumption, GPU contention and storage capacity

Failure of any security or data-safety check is a **release blocker**.
