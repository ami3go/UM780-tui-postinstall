# Optional GPU LLM Lab — rootless Podman + Distrobox

The Stage 2 **gpu_lab** option adds a separate, experimental LLM environment to the existing Debian 13 TUI. It is OFF by default. Production Ollama, llama.cpp, Open WebUI, systemd services, model stores and listeners are not changed.

## Install from the existing TUI

In Stage 2, check **gpu_lab — Optional rootless Distrobox GPU lab**. Or review and run only this module:

```bash
python3 install.py --plan --component gpu_lab
sudo python3 install.py --apply --component gpu_lab
python3 install.py --inventory --component gpu_lab
```

This uses Debian packages `podman`, `distrobox`, `crun`, `uidmap`, `slirp4netns`, `fuse-overlayfs`, `mesa-vulkan-drivers`, `vulkan-tools`, and provisions the `llm-lab` non-root account with `/var/lib/llm-lab` as home. Where present, the user is added to `render` and `video`. The installer writes a managed configuration marker but **does not** download a container, model or runtime, start a service, or enable a network listener. An existing conflicting account or non-owned lab home blocks provisioning.

## Interactive GPU Lab manager (whiptail or numbered fallback)

**After** completing a new login to pick up GPU group membership:

```bash
sudo -iu llm-lab
# Run from a repo checkout or another copy readable by this user:
python3 /path/to/UM780-tui-postinstall/install.py --gpu-lab
```

The manager refuses to execute as root or any account other than `llm-lab`. It offers the following explicit actions:

| Menu item | Effect |
| --- | --- |
| Status | View `podman` runtime, Distrobox list, host render device and Vulkan diagnostics |
| Create CPU-baseline box | Create `llm-cpu` Debian 13 container with its own container home |
| Create Vulkan GPU box | Create `llm-vulkan`, exposing `/dev/dri` using `crun` and `keep-groups` |
| Verify GPU in box | Install Mesa/Vulkan diagnostics **inside** the box, then run `vulkaninfo --summary` |
| CPU vs Vulkan benchmark | Run installed host `llama-bench` with `-ngl 0` and `-ngl 99`, sequentially |
| Enter CPU or Vulkan box | Open an interactive session for manual model/backend tests |

Images come from `docker.io/library/debian:13` on explicit creation only. Profile home directories are under `/var/lib/llm-lab/distrobox-homes/`. GPU visibility requires accessible `/dev/dri/renderD*`; membership changes need a **new login**. Container initialization may require interactive setup. The tool does not automatically install Ollama/llama.cpp inside the containers or claim a ROCm/HIP setup.

The existing host llama.cpp build must provide `/opt/llm-stack/llama.cpp/build/bin/llama-bench`. Enter an existing absolute `.gguf` model file path readable by the lab user. Benchmark reports go to `/var/lib/llm-lab/gpu-lab-results/<UTC>-cpu.json` and `<UTC>-vulkan.json` with mode 0600. Reports are timings, not coding-quality evaluation. GPU offload must be corroborated using diagnostic logs and GPU utilization.

## Security and limitations

- **Distrobox is not a security sandbox**. A custom `--home` does not fully prevent host-user filesystem access. Use trusted images and code only. For untrusted workloads, use a VM.
- Podman runs **rootless**. Never use `sudo distrobox`, `--root`, or `--privileged` for this workflow. Containers have access to the host kernel, physical RAM and GPU; compare heavy benchmarks sequentially.
- The CPU-labelled box is not prohibited from seeing GPU devices because Distrobox is host-integrated; CPU benchmarking explicitly uses `-ngl 0`.
- **No writable shared model mount is created.** To use existing GGUF weights, arrange safe read-only access for the lab account. Do not add `llm-lab` to write-enabled production model groups.
- Host kernel and AMDGPU driver remain shared; changing Mesa in the guest is not a kernel-driver upgrade.
- The installer and tests are not a substitute for a real hardware acceptance test on the UM780 Pro. A `vulkaninfo` result does not by itself verify llama.cpp Vulkan acceleration.

Reference documentation: [Distrobox custom home](https://github.com/89luca89/distrobox/blob/main/docs/useful_tips.md), [Distrobox container flags](https://manpages.debian.org/trixie/distrobox/distrobox-create.1.en.html), [Podman keep-groups](https://docs.podman.io/en/latest/markdown/podman-create.1.html).
