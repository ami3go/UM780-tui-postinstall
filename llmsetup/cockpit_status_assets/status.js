// um780-postinstall-managed
"use strict";
(() => {
  const entries = [
    ["Ollama", "llm-ollama.service"], ["llama.cpp", "llm-llama.service"],
    ["Open WebUI", "llm-webui.service"], ["code-server", "llm-codeserver.service"],
    ["FileBrowser Quantum", "llm-filebrowser.service"], ["JupyterLab", "llm-jupyterlab.service"],
    ["noVNC Desktop", "llm-novnc-vnc.service"], ["noVNC Web Proxy", "llm-novnc.service"],
    ["Uptime Kuma", "llm-uptime-kuma.service"], ["Service Watchdog", "llm-service-watchdog.timer"],
    ["Backups", "llm-backup.timer"], ["Cockpit", "cockpit.socket"]
  ];
  const grid = document.getElementById("status");
  const info = document.getElementById("updated");
  const button = document.getElementById("refresh");
  async function check(label, unit) {
    let status = "Unavailable";
    try {
      const output = await window.cockpit.spawn(
        ["systemctl","is-active", unit], { superuser: null, err:"ignore" }
      );
      status = String(output || "").trim() || "unknown";
    } catch (_) {
      status = "inactive / missing";
    }
    const article = document.createElement("article");
    const title = document.createElement("h2");
    const line = document.createElement("p");
    title.textContent = label;
    line.textContent = status;
    line.className = status === "active" ? "ok" : "fail";
    article.append(title, line);
    return article;
  }
  async function refresh() {
    if (!window.cockpit?.spawn) {
      info.textContent = "Cockpit bridge unavailable";
      return;
    }
    button.disabled = true;
    info.textContent = "Checking native services...";
    const tiles = await Promise.all(entries.map(([name,unit]) => check(name,unit)));
    grid.replaceChildren(...tiles);
    info.textContent = "Updated " + new Date().toLocaleString();
    button.disabled = false;
  }
  button.addEventListener("click", refresh);
  refresh();
})();
