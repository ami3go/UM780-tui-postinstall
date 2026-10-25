"""Optional rootless Podman/Distrobox GPU testing lab for Debian 13.

Distrobox is a developer convenience, NOT a security boundary. Run only
trusted images and commands. Experiments never modify production LLM units.
"""
from __future__ import annotations

import grp
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from .core import CONF_DIR, SetupError
from .component_base import managed

LAB_USER = "llm-lab"
LAB_HOME = Path("/var/lib/llm-lab")
IMAGE = "docker.io/library/debian:13"
PROFILES = ("llm-cpu", "llm-vulkan")
LLAMA_BENCH = Path("/opt/llm-stack/llama.cpp/build/bin/llama-bench")


def gpu_lab(r, cfg, ui):
    """Install lab prerequisites and provision a non-root account; NO boxes auto-created."""
    r.apt("podman", "distrobox", "crun", "uidmap", "slirp4netns",
          "fuse-overlayfs", "mesa-vulkan-drivers", "vulkan-tools")
    try:
        user = pwd.getpwnam(LAB_USER)
    except KeyError:
        if LAB_HOME.exists() or LAB_HOME.is_symlink():
            raise SetupError("Lab home exists without lab account; inspect manually")
        r.run(["useradd", "--create-home", "--home-dir", str(LAB_HOME),
               "--shell", "/bin/bash", LAB_USER])
        user = pwd.getpwnam(LAB_USER)
    if user.pw_uid == 0 or user.pw_dir != str(LAB_HOME):
        raise SetupError("Existing llm-lab account has unexpected UID or home; refusing changes")
    if LAB_HOME.is_symlink() or not LAB_HOME.is_dir():
        raise SetupError("Lab home must be a real directory")
    groups = []
    for group in ("render", "video"):
        try:
            grp.getgrnam(group)
            groups.append(group)
        except KeyError:
            print("WARNING: missing device group: " + group)
    if groups:
        r.run(["usermod", "-aG", ",".join(groups), LAB_USER])
    r.write(CONF_DIR / "gpu-lab.conf",
            managed("LAB_USER=llm-lab\nROOTLESS=true\nIMAGE=" + IMAGE), mode=0o644)
    print("GPU Lab installed: rootless Podman + Distrobox, no containers pulled.")
    print("Log into llm-lab (a fresh login is required for GPU group changes),")
    print("then run: python3 /path/to/UM780-tui-postinstall/install.py --gpu-lab")
    print("The checked-out project must be readable by the llm-lab account.")


def create_args(profile: str, home: Path) -> list[str]:
    """Fixed-name, fixed-image container command. No rootful or privileged flags."""
    if profile not in PROFILES:
        raise SetupError("Unsupported GPU Lab profile")
    command = ["distrobox", "create", "--name", profile, "--image", IMAGE,
               "--home", str(home)]
    if profile == "llm-vulkan":
        command += ["--additional-flags",
                    "--runtime=crun --device=/dev/dri --group-add=keep-groups"]
    return command


def benchmark_args(model: Path, gpu_layers: int) -> list[str]:
    if gpu_layers not in (0, 99):
        raise SetupError("Only CPU baseline and Vulkan offload are supported")
    return [str(LLAMA_BENCH), "-m", str(model), "-p", "512", "-n", "128",
            "-r", "3", "-ngl", str(gpu_layers), "-o", "json"]


def _run(argv, *, capture=False, timeout=None):
    try:
        result = subprocess.run(argv, check=False, text=True, timeout=timeout,
                                capture_output=capture)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError("GPU Lab command could not complete: " + argv[0]) from exc
    if result.returncode:
        details = (result.stderr or "")[-400:] if capture else ""
        raise SetupError(f"{argv[0]} exited {result.returncode}: {details}")
    return result.stdout if capture else ""


def _device_ok():
    dri = Path("/dev/dri")
    return dri.is_dir() and any(
        p.name.startswith("renderD") and os.access(p, os.R_OK | os.W_OK)
        for p in dri.glob("renderD*")
    )


def _choice():
    options = (
        ("1", "Show rootless containers and host GPU"),
        ("2", "Create Debian CPU-baseline box"),
        ("3", "Create Debian Vulkan GPU box"),
        ("4", "Verify Vulkan inside GPU box"),
        ("5", "Run CPU vs Vulkan GGUF benchmark"),
        ("6", "Enter CPU box"),
        ("7", "Enter Vulkan box"),
        ("8", "Exit"),
    )
    if shutil.which("whiptail") and sys.stdin.isatty():
        argv = ["whiptail", "--title", "GPU LLM Lab (rootless)",
                "--menu", "Choose an action (lab user only)", "20", "85", "9"]
        for key, title in options:
            argv.extend([key, title])
        response = subprocess.run(argv, capture_output=True, text=True, check=False)
        return response.stderr.strip() if response.returncode == 0 else "8"
    print("\n=== GPU LLM LAB ===")
    for key, title in options:
        print(f" {key}. {title}")
    return input("Choice: ").strip()


def _create(profile):
    if shutil.which("distrobox") is None or shutil.which("podman") is None:
        raise SetupError("Install optional gpu_lab component first")
    if profile == "llm-vulkan" and not _device_ok():
        raise SetupError("No accessible AMD/DRM render node; check render group and new login")
    existing = subprocess.run(["podman", "container", "exists", profile],
                              check=False, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    if existing.returncode == 0:
        print(f"{profile} already exists. No modifications made.")
        return
    if existing.returncode != 1:
        raise SetupError("Could not reliably check for an existing container")
    home = Path.home() / "distrobox-homes" / profile
    if home.is_symlink():
        raise SetupError("Refusing symlinked profile home")
    home.mkdir(parents=True, mode=0o700, exist_ok=True)
    if home.resolve() != home or not home.is_dir():
        raise SetupError("Unexpected lab profile path")
    _run(create_args(profile, home))
    print("Created " + profile + ". Enter the box to install your inference runtime.")
    print("CPU baseline means -ngl 0 in llama-bench, not GPU device isolation.")


def _verify_vulkan():
    if not _device_ok():
        raise SetupError("GPU render device unavailable to lab user")
    # Installs only into the selected container, never into the host OS.
    _run(["distrobox", "enter", "llm-vulkan", "--", "sudo", "apt-get", "update"])
    _run(["distrobox", "enter", "llm-vulkan", "--", "sudo", "apt-get",
          "install", "-y", "mesa-vulkan-drivers", "vulkan-tools"])
    output = _run(["distrobox", "enter", "llm-vulkan", "--",
                   "vulkaninfo", "--summary"], capture=True, timeout=90)
    print(output[:6000])
    if "llvmpipe" in output.lower() and not any(x in output.lower() for x in ("radeon", "amd", "radv")):
        raise SetupError("Vulkan appears to be software-only (llvmpipe)")
    print("Inspect the device list above: GPU visibility does not prove LLM offload.")


def _benchmark(ui):
    if not LLAMA_BENCH.is_file():
        raise SetupError("Install/build native llama.cpp llama-bench first")
    raw = ui.ask("Existing, readable .gguf absolute path (no downloads): ").strip()
    model = Path(raw)
    if not model.is_absolute() or model.suffix.lower() != ".gguf":
        raise SetupError("Provide an absolute path to a .gguf file")
    if model.is_symlink() or not model.is_file() or not os.access(model, os.R_OK):
        raise SetupError("Model must exist and be readable by llm-lab, not a symlink")
    results = Path.home() / "gpu-lab-results"
    results.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for label, layers in (("cpu", 0), ("vulkan", 99)):
        print(f"Running {label} test sequentially; no production services altered.")
        output = _run(benchmark_args(model, layers), capture=True, timeout=900)
        dest = results / f"{stamp}-{label}.json"
        dest.write_text(output, encoding="utf-8")
        dest.chmod(0o600)
        print(f"{label} benchmark saved: {dest}")
    print("Compare throughput, utilization and model quality separately.")


def gpu_lab_menu(ui):
    """Operated by dedicated unprivileged account; never run rootful Podman."""
    if os.geteuid() == 0:
        raise SetupError("GPU Lab menu refuses root. Log in with: sudo -iu llm-lab")
    if pwd.getpwuid(os.geteuid()).pw_name != LAB_USER:
        raise SetupError("GPU Lab must run under dedicated account: llm-lab")
    while True:
        choice = _choice()
        if choice in ("", "8"):
            return 0
        try:
            if choice == "1":
                _run(["podman", "info", "--format", "{{.Host.OCIRuntime.Name}}"])
                _run(["distrobox", "list"])
                print("GPU render device accessible:", _device_ok())
                if shutil.which("vulkaninfo"):
                    print(_run(["vulkaninfo", "--summary"], capture=True, timeout=30)[:4000])
            elif choice in ("2", "3"):
                _create("llm-cpu" if choice == "2" else "llm-vulkan")
            elif choice == "4":
                _verify_vulkan()
            elif choice == "5":
                _benchmark(ui)
            elif choice in ("6", "7"):
                _run(["distrobox", "enter", "llm-cpu" if choice == "6" else "llm-vulkan"])
            else:
                print("Invalid menu option")
        except (SetupError, OSError) as exc:
            print("GPU Lab error:", exc)
