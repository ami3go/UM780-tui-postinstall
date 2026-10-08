"""Public registry of independently maintainable installers."""
from .component_base import *
from .component_llms import ollama, webui, models
from .component_cockpit_plugins import cockpit_ghsync, cockpit_bookmarks
from .component_bookmarks_auto import bookmark_sync
from .component_safety import preflight, config_snapshot, cockpit_status
from .component_native_apps import opencode, llama_swap, uptime_kuma, secure_ingress, ups_wol
from .component_maintenance import hardware_health, backup_restore, cockpit_storage, service_watchdog, developer_tools, llm_benchmark, zram
from .component_optional_tools import fish, btop, mc, ttyd, agent_of_empires, jupyterlab, vnc, novnc
from .component_addons import cockpit, filebrowser, codeserver, tailscale, updates, benchmarks
INSTALLERS = {name: globals()[name] for name in ALL}
