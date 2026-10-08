"""Single source of truth for phased installation priority and setup order.

Every module appears exactly once. The stages are an ordering and UX contract,
NOT implicit permission to install unchecked applications or dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    number: int
    name: str
    objective: str
    components: tuple[str, ...]


STAGES = (
    Stage(1, 'Essential system and data safety',
          'Prepare Debian, protect existing storage and establish baseline health.',
          ('preflight', 'base', 'config_snapshot', 'storage',
           'hardware_health', 'updates', 'zram')),
    Stage(2, 'Local LLM engines and models',
          'Configure AMD acceleration, inference engines, model downloads and performance checks.',
          ('vulkan', 'ollama', 'llama', 'models', 'webui',
           'benchmarks', 'llm_benchmark', 'llama_swap')),
    Stage(3, 'Administration and development',
          'Install Cockpit and its plugins, browser development tools and optional terminals.',
          ('cockpit', 'cockpit_storage', 'cockpit_ghsync', 'cockpit_bookmarks',
           'cockpit_status', 'filebrowser', 'codeserver', 'fish', 'btop', 'mc',
           'developer_tools', 'opencode', 'agent_of_empires', 'jupyterlab', 'ttyd')),
    Stage(4, 'Remote access and virtual desktop',
          'Prepare private remote networking and optional VNC desktop access.',
          ('tailscale', 'secure_ingress', 'vnc', 'novnc')),
    Stage(5, 'Monitoring, backups and automation',
          'Configure opt-in backups and alerts, other homelab control, and final bookmarks.',
          ('backup_restore', 'service_watchdog', 'uptime_kuma', 'ups_wol',
           'bookmark_sync')),
)

ORDER = tuple(name for stage in STAGES for name in stage.components)
STAGE_BY_COMPONENT = {name: stage.number for stage in STAGES for name in stage.components}

# Recommended prerequisites, not auto-selected dependencies. Modules can be
# rerun individually after their prerequisites were installed on earlier runs.
PREREQUISITES = {
    'storage': ('base',),
    'config_snapshot': ('base',),
    'updates': ('base',),
    'vulkan': ('base',),
    'ollama': ('storage',),
    'llama': ('vulkan', 'storage'),
    'models': ('ollama',),
    'webui': ('ollama',),
    'benchmarks': ('vulkan',),
    'llm_benchmark': ('llama',),
    'llama_swap': ('llama',),
    'cockpit_storage': ('cockpit',),
    'cockpit_ghsync': ('cockpit',),
    'cockpit_bookmarks': ('cockpit',),
    'cockpit_status': ('cockpit',),
    'filebrowser': ('storage',),
    'secure_ingress': ('tailscale',),
    'bookmark_sync': ('cockpit_bookmarks',),
    'backup_restore': ('storage',),
    'ups_wol': ('cockpit',),
    'service_watchdog': ('cockpit',),
}

# Step-specific guidance: manual setup is intentionally separate from apt
# installation. In particular, high-risk network/power actions remain opt-in.
SETUP_NOTES = {
    'preflight': 'Review results; this does not replace a disk/topology inspection.',
    'config_snapshot': 'Existing managed files only; root-only secrets; not package/disk rollback.',
    'storage': 'Inspect lsblk -f and mounts; an existing SSD mount requires typed UUID approval.',
    'hardware_health': 'Review SMART/NVMe and temperature report; no recurring SSD tests yet.',
    'updates': 'Unattended Debian security updates; reboot is not automatic.',
    'zram': 'Enable compressed RAM swap; review the existing Debian swap configuration.',
    'vulkan': 'Verify the AMD Radeon 780M is enumerated by vulkaninfo.',
    'ollama': 'Verify localhost:11434; AMD acceleration may fall back to CPU.',
    'llama': 'Select an existing GGUF to activate llama-server; do not assume GPU offload.',
    'models': 'Approve the multi-GB model download explicitly.',
    'webui': 'Verify first-run login and connection to Ollama via the SSH tunnel.',
    'llm_benchmark': 'Requires existing GGUF and built llama-bench; inspect CPU versus Vulkan results.',
    'llama_swap': 'Installs CLI only; review model mapping/config before manually starting a router.',
    'cockpit': 'Use a trusted SSH tunnel to the loopback Cockpit HTTPS port 9090.',
    'cockpit_ghsync': 'Run gh auth login as your regular Cockpit user; no scheduled sync by default.',
    'cockpit_bookmarks': 'Review generated app links and SSH forwarding on the browser client.',
    'cockpit_status': 'Read-only service page; active is not the same as functional.',
    'codeserver': 'Retrieve generated password from root-only config before login.',
    'filebrowser': 'Review model file permissions: read-only isolation is not yet reliable.',
    'ttyd': 'Service remains disabled; explicit activation and SSH forwarding required.',
    'jupyterlab': 'Use a tunnel and a Jupyter token; notebooks execute commands as the service user.',
    'opencode': 'Authenticate as your regular Linux user, not root.',
    'agent_of_empires': 'Run agent manager under your regular user; no agent sessions auto-start.',
    'tailscale': 'Enroll manually with sudo tailscale up; no unauthenticated public listeners.',
    'secure_ingress': 'Readiness check only; configure authenticated Tailscale Serve manually.',
    'vnc': 'Set a normal-user VNC password and explicitly activate the per-user :1 desktop.',
    'novnc': 'Creates a dedicated :2 desktop; retrieve root-only VNC password; tunnel 6080.',
    'backup_restore': 'Provide mounted external repository, initialize Restic, test an actual restore.',
    'service_watchdog': 'Logs inactive services to journal only, no automatic recovery/notifications.',
    'uptime_kuma': 'Create admin login via localhost:3001 and configure checks/notifications.',
    'ups_wol': 'Source preparation only; explicitly review the UPS topology and dry-run.',
    'bookmark_sync': 'Additively refresh installed app links; preserve custom Bookmarks entries.',
}


def get_stage(number: int) -> Stage:
    if type(number) is not int:
        raise ValueError('Stage number must be an integer')
    for stage in STAGES:
        if stage.number == number:
            return stage
    raise ValueError(f'Unknown installation stage: {number}')


def ordered_selection(selected):
    """Canonical order, duplicate-free; caller validates unknown components."""
    membership = set(selected)
    return [name for name in ORDER if name in membership]


def selected_from_stages(stage_numbers, default_components):
    """A --stage run chooses only already-default-selected modules in those stages."""
    allowed = set()
    for number in stage_numbers:
        allowed.update(get_stage(number).components)
    return ordered_selection(allowed.intersection(default_components))


def manual_prerequisites(name, selected):
    """Advisory only: a missing selection may have been installed on a previous run."""
    in_run = set(selected)
    return tuple(p for p in PREREQUISITES.get(name, ()) if p not in in_run)
