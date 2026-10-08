"""Public registry of independently maintainable installers."""
from .component_base import *
from .component_llms import ollama, webui, models
from .component_addons import cockpit, filebrowser, codeserver, tailscale, updates, benchmarks
INSTALLERS = {name: globals()[name] for name in ALL}
