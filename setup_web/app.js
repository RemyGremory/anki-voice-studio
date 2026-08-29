const $ = (id) => document.getElementById(id);
let snapshot = null;
let closing = false;
let installParent = null;

async function request(path, payload) {
  const response = await fetch(path, payload ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)} : undefined);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "The setup could not complete this action.");
  return data;
}

function selectedEdition() {
  return document.querySelector('input[name="edition"]:checked')?.value || "cpu";
}

function selectedInstallPath(data) {
  return installParent ? installParent + "\\Anki Voice Studio" : (data.install_path || "");
}

function displayInstallLocation(data) {
  if (installParent === null) installParent = data.install_parent || "";
  const path = selectedInstallPath(data);
  $("installLocation").textContent = path ? "Program folder: " + path : "Program folder will use the default location.";
  $("chooseLocation").disabled = Boolean(data.working);
}

function setStatus(data) {
  snapshot = data;
  const ready = data.release_ready;
  const active = data.working;
  const current = data.current;
  $("statusIcon").textContent = current ? "✓" : active ? "↓" : ready ? "✦" : "!";
  $("statusTitle").textContent = current ? `Version ${data.version} is current` : active ? "Working…" : ready ? "Ready" : "Setup needs attention";
  $("statusText").textContent = data.message;
  const gpuText = data.nvidia ? `Detected NVIDIA: ${data.nvidia}` : "No NVIDIA card detected — Compact CPU is recommended.";
  $("gpuText").textContent = gpuText;
  const recommended = data.recommended || "cpu";
  const target = data.installed && data.installed_edition ? data.installed_edition : recommended;
  const selected = document.querySelector('input[name="edition"]:checked');
  if (!selected) document.querySelector(`input[value="${target}"]`).checked = true;
  $("nvidiaChoice").classList.toggle("recommended", recommended === "nvidia");
  $("cpuChoice").classList.toggle("recommended", recommended === "cpu");
  $("nvidiaChoice").classList.toggle("unavailable", !data.available?.nvidia);
  $("cpuChoice").classList.toggle("unavailable", !data.available?.cpu);
  document.querySelector('input[value="nvidia"]').disabled = !data.available?.nvidia;
  document.querySelector('input[value="cpu"]').disabled = !data.available?.cpu;
  const progress = Number.isFinite(data.progress) ? data.progress : null;
  $("progressWrap").hidden = progress === null;
  if (progress !== null) { $("progressBar").style.width = `${progress}%`; $("progressValue").textContent = `${progress}%`; }
  const sameLocation = selectedInstallPath(data).toLocaleLowerCase() === (data.install_path || "").toLocaleLowerCase();
  const currentSelection = current && data.installed_edition === selectedEdition() && sameLocation;
  $("installButton").disabled = !ready || active || currentSelection || !data.available?.[selectedEdition()];
  $("installButton").textContent = data.update_available ? "Install update" : "Install Anki Voice Studio";
  $("closeButton").disabled = active;
  $("closeButton").textContent = active ? "Installing…" : "Close setup";
  displayInstallLocation(data);
  $("launchCard").hidden = !data.installed;
  $("launchText").textContent = data.current ? "Everything is up to date." : "A previous version is installed.";
}

async function refresh() { if (closing) return; try { setStatus(await request("/api/status")); } catch (error) { $("statusText").textContent = error.message; } }
$("refreshButton").onclick = async () => { try { await request("/api/refresh", {}); } finally { refresh(); } };
$("installButton").onclick = async () => { try { await request("/api/install", {edition: selectedEdition(), install_parent: installParent || ""}); } catch (error) { alert(error.message); } finally { refresh(); } };
$("chooseLocation").onclick = async () => { try { const data = await request("/api/pick-install-location", {}); if (data.path) { installParent = data.path; displayInstallLocation(snapshot || {}); if (snapshot?.release_ready && !snapshot.working && snapshot.available?.[selectedEdition()]) $("installButton").disabled = false; } } catch (error) { alert(error.message); } };
$("launchButton").onclick = async () => { try { await request("/api/launch", {}); } catch (error) { alert(error.message); } };
$("closeButton").onclick = async () => {
  closing = true;
  try {
    await request("/api/close", {});
    $("statusIcon").textContent = "✓";
    $("statusTitle").textContent = "Setup closed";
    $("statusText").textContent = "You can close this browser tab.";
    $("closeButton").disabled = true;
    window.setTimeout(() => window.close(), 350);
  } catch (error) {
    closing = false;
    $("statusText").textContent = error.message;
  }
};
document.querySelectorAll('input[name="edition"]').forEach((item) => item.onchange = () => setStatus(snapshot || {}));
refresh();
setInterval(refresh, 900);
