/**
 * Sentinel v0.2 — Live 60 Hz WebSocket Telemetry Client, Tactical Banner,
 * Diffed Sidebar Roster, Dossier/Forensics Reader Modal, Swarm Spawner,
 * and Forensic Combat Log Console Controller.
 */

(function () {
  "use strict";

  function sessionToken() {
    if (typeof window.SENTINEL_TOKEN === "string" && window.SENTINEL_TOKEN) {
      return window.SENTINEL_TOKEN;
    }
    try {
      return new URLSearchParams(window.location.search).get("token") || "";
    } catch (_e) {
      return "";
    }
  }

  function apiHeaders(extra) {
    const headers = extra ? Object.assign({}, extra) : {};
    const token = sessionToken();
    if (token) {
      headers["X-Sentinel-Token"] = token;
    }
    return headers;
  }

  const canvas = document.getElementById("overseer-canvas");
  const engine = new window.OverseerEngine(canvas);

  let activeCasteFilter = "all";
  let activeLogFilter = "all";
  let logSearchQuery = "";
  let isLogPaused = false;
  let latestSnapshot = null;
  let lastRenderedLogSeq = -1;
  let lastUnitRosterSig = "";
  let lastNodeRosterSig = "";
  let lastInspectorSig = "";
  let lastReceiptsSig = "";
  let currentModalFolder = "harvest";
  let ws = null;

  // Top bar elements
  const elUnits = document.getElementById("m-units");
  const elHrv = document.getElementById("m-hrv");
  const elWrd = document.getElementById("m-wrd");
  const elSan = document.getElementById("m-san");
  const elTrp = document.getElementById("m-trp");
  const elWarrants = document.getElementById("m-warrants");
  const elThreats = document.getElementById("m-threats");
  const elFps = document.getElementById("m-fps");
  const elBeacon = document.getElementById("conn-beacon");
  const elEmpBanner = document.getElementById("emp-banner");
  const elEmpReason = document.getElementById("emp-reason-text");
  const elScenarioSelect = document.getElementById("scenario-select");
  const elTierSelect = document.getElementById("tier-select");
  const elThemeSelect = document.getElementById("theme-select");
  const elCamSelect = document.getElementById("camera-select");
  const elFooterTheme = document.getElementById("footer-theme-info");

  // Tactical Banner
  const elTacticalBanner = document.getElementById("tactical-banner");
  const elTacticalTitle = document.getElementById("tactical-title");
  const elTacticalSub = document.getElementById("tactical-sub");

  // Side panels & Bottom Console
  const elUnitRoster = document.getElementById("unit-roster");
  const elNodeRoster = document.getElementById("node-roster");
  const elInspector = document.getElementById("inspector-card");
  const elReceiptFeed = document.getElementById("receipt-feed");
  const elConsoleBody = document.getElementById("telemetry-console-body");
  const elLogSearch = document.getElementById("log-search-input");
  const elBtnLogPause = document.getElementById("btn-log-pause");
  const elConsoleLiveDot = document.getElementById("console-live-dot");

  // Dossier & Forensics Reader Modal
  const elModal = document.getElementById("dossier-modal");
  const elModalTitle = document.getElementById("modal-title");
  const elModalSubtitle = document.getElementById("modal-subtitle");
  const elModalBody = document.getElementById("modal-body");
  const elBtnModalCopy = document.getElementById("btn-modal-copy");
  const elBtnModalFolder = document.getElementById("btn-modal-folder");
  const elBtnModalClose = document.getElementById("btn-modal-close");

  // Restore saved camera preference from localStorage (never boot into targetless 'chase')
  try {
    const savedCam = localStorage.getItem("sentinel_camera_mode");
    if (savedCam && ["orbit", "top", "core"].includes(savedCam)) {
      elCamSelect.value = savedCam;
      engine.setCameraMode(savedCam);
    }
    const savedTheme = localStorage.getItem("sentinel_theme_id");
    if (savedTheme && ["sodium", "filament", "night", "matrix"].includes(savedTheme)) {
      document.documentElement.setAttribute("data-theme", savedTheme);
      elThemeSelect.value = savedTheme;
    }
  } catch (_e) {}

  function setCameraAndSave(mode) {
    elCamSelect.value = mode;
    engine.setCameraMode(mode);
    if (mode !== "chase") {
      try {
        localStorage.setItem("sentinel_camera_mode", mode);
      } catch (_e) {}
    }
  }

  // Immortal 60 FPS animation loop
  let lastFpsUpdateMs = 0;
  function animate(now) {
    requestAnimationFrame(animate);
    try {
      engine.renderFrame(now);
      if (now - lastFpsUpdateMs > 250) {
        lastFpsUpdateMs = now;
        const fpsStr = String(Math.round(engine.fpsSmoothed));
        if (elFps.textContent !== fpsStr) elFps.textContent = fpsStr;
      }
    } catch (err) {
      if (!animate._warned) {
        animate._warned = true;
        console.error("Overseer render frame error:", err);
      }
    }
  }
  requestAnimationFrame(animate);

  let lastInspectorRenderMs = 0;

  engine.onSelectionChanged = function (id, _kind) {
    if (id && elCamSelect.value !== "chase") {
      setCameraAndSave("chase");
    } else if (!id && elCamSelect.value === "chase") {
      setCameraAndSave("orbit");
    }
    renderInspector(true);
    renderRoster(true);
    renderReceipts(true);
  };

  function badgeClassForState(state, caste) {
    if (state === "ENGAGED_DEFENSE" || state === "QUARANTINING" || state === "EMP_DISABLED") {
      return "badge badge-defense";
    }
    if (state === "ENGAGED_SANITIZE" || (caste === "sanitizer" && state !== "PATROLLING")) {
      return "badge badge-sanitize";
    }
    if (state !== "PATROLLING") {
      return "badge badge-active";
    }
    return "badge badge-patrol";
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function hasActiveSelectionInside(el) {
    try {
      const sel = window.getSelection();
      if (!sel || sel.toString().length === 0) return false;
      return el.contains(sel.anchorNode) || el.contains(sel.focusNode);
    } catch (_e) {
      return false;
    }
  }

  function openFolderInExplorer(folderKind) {
    fetch("/api/overseer/open_folder", {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ folder: folderKind }),
    });
  }

  function openDossierModal(kind, nameOrId) {
    if (!elModal) return;
    currentModalFolder = kind === "harvest" ? "harvest" : "quarantine";
    elModalTitle.textContent = `LOADING ${kind.toUpperCase()} // ${nameOrId}...`;
    elModalSubtitle.textContent = "Fetching verified payload from Sentinel loopback bridge...";
    elModalBody.textContent = "Reading disk artifact...";
    elModal.classList.remove("hidden");

    fetch(`/api/overseer/file?kind=${encodeURIComponent(kind)}&name=${encodeURIComponent(nameOrId)}`, {
      headers: apiHeaders(),
    })
      .then((r) => r.json())
      .then((data) => {
        if (!data || !data.ok) {
          elModalTitle.textContent = `ERROR // ${nameOrId}`;
          elModalSubtitle.textContent = (data && data.error) || "Could not load file";
          elModalBody.textContent = JSON.stringify(data || {}, null, 2);
          return;
        }
        elModalTitle.textContent = data.title || `${kind.toUpperCase()} // ${nameOrId}`;
        elModalSubtitle.textContent = data.subtitle || "";
        elModalBody.textContent = data.content || "";
      })
      .catch((err) => {
        elModalTitle.textContent = "READ ERROR";
        elModalBody.textContent = String(err);
      });
  }

  function closeDossierModal() {
    if (elModal) {
      elModal.classList.add("hidden");
    }
  }

  if (elBtnModalClose) {
    elBtnModalClose.addEventListener("click", closeDossierModal);
  }
  if (elModal) {
    elModal.addEventListener("click", (ev) => {
      if (ev.target === elModal) closeDossierModal();
    });
  }
  if (elBtnModalCopy) {
    elBtnModalCopy.addEventListener("click", () => {
      const txt = elModalBody ? elModalBody.textContent || "" : "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(txt);
      }
      const orig = elBtnModalCopy.textContent;
      elBtnModalCopy.textContent = "✓ COPIED TO CLIPBOARD";
      setTimeout(() => {
        elBtnModalCopy.textContent = orig;
      }, 1400);
    });
  }
  if (elBtnModalFolder) {
    elBtnModalFolder.addEventListener("click", () => {
      openFolderInExplorer(currentModalFolder);
    });
  }

  // Event delegation bound ONCE per container (zero listener churn)
  elUnitRoster.addEventListener("click", (ev) => {
    const row = ev.target.closest(".unit-row");
    if (!row) return;
    engine.selectedId = row.getAttribute("data-uid");
    engine.selectedKind = "unit";
    setCameraAndSave("chase");
    renderInspector(true);
    renderRoster(true);
  });

  elNodeRoster.addEventListener("click", (ev) => {
    const row = ev.target.closest(".node-row");
    if (!row) return;
    engine.selectedId = row.getAttribute("data-nid");
    engine.selectedKind = "node";
    setCameraAndSave("chase");
    renderInspector(true);
    renderRoster(true);
  });

  elInspector.addEventListener("click", (ev) => {
    const pill = ev.target.closest(".doc-pill-link");
    if (!pill) return;
    ev.stopPropagation();
    const unbanIp = pill.getAttribute("data-unban-ip");
    if (unbanIp) {
      fetch("/api/overseer/unban", {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ ip: unbanIp }),
      });
      return;
    }

    const kind = pill.getAttribute("data-doc-kind") || "harvest";
    const name = pill.getAttribute("data-doc-name") || "";
    if (name) openDossierModal(kind, name);
  });

  elReceiptFeed.addEventListener("click", (ev) => {
    const row = ev.target.closest(".receipt-row");
    if (!row) return;
    const rid = row.getAttribute("data-rid");
    engine.selectedId = rid;
    engine.selectedKind = "receipt";
    renderInspector(true);
    renderReceipts(true);
  });

  elReceiptFeed.addEventListener("dblclick", (ev) => {
    const row = ev.target.closest(".receipt-row");
    if (!row) return;
    const rid = row.getAttribute("data-rid");
    if (rid) openDossierModal("receipt", rid);
  });

  elConsoleBody.addEventListener("click", (ev) => {
    if (hasActiveSelectionInside(elConsoleBody)) return;
    const line = ev.target.closest(".log-line");
    if (!line) return;
    const uid = line.getAttribute("data-uid") || "";
    if (uid.startsWith("SNT-") && latestSnapshot && (latestSnapshot.units || []).some((u) => u.unit_id === uid)) {
      engine.selectedId = uid;
      engine.selectedKind = "unit";
      setCameraAndSave("chase");
      renderInspector(true);
      renderRoster(true);
    }
  });

  function renderTacticalBanner() {
    if (!latestSnapshot) return;
    const banner = latestSnapshot.active_banner;
    if (!banner || !banner.title) {
      elTacticalBanner.classList.add("hidden");
      return;
    }
    elTacticalBanner.classList.remove("hidden");
    elTacticalBanner.setAttribute("data-severity", banner.severity || "info");
    if (elTacticalTitle.textContent !== banner.title) {
      elTacticalTitle.textContent = banner.title;
    }
    const sub = banner.subtitle || "";
    if (elTacticalSub.textContent !== sub) {
      elTacticalSub.textContent = sub;
    }
  }

  let lastUnitIdsSig = "";
  let lastNodeIdsSig = "";

  function renderRoster(force) {
    if (!latestSnapshot) return;
    const units = (latestSnapshot.units || []).filter(
      (u) => activeCasteFilter === "all" || u.caste === activeCasteFilter
    );

    const unitSig =
      `${activeCasteFilter}|${engine.selectedKind}|${engine.selectedId}|` +
      units
        .map((u) => `${u.unit_id}:${u.tier}:${u.state}:${u.current_task}:${u.pack_role}:${u.pack_size}`)
        .join(";");

    if (force || unitSig !== lastUnitRosterSig) {
      lastUnitRosterSig = unitSig;
      const idsSig = `${activeCasteFilter}|` + units.map((u) => u.unit_id).join(",");

      if (idsSig !== lastUnitIdsSig || elUnitRoster.children.length !== units.length) {
        lastUnitIdsSig = idsSig;
        const prevScroll = elUnitRoster.scrollTop;
        elUnitRoster.innerHTML = units
          .map((u) => {
            const sel = engine.selectedKind === "unit" && engine.selectedId === u.unit_id ? "selected" : "";
            const bCls = badgeClassForState(u.state, u.caste);
            const doc = u.doctrine || "HUNTER-SEEKER";
            const shortDoc = doc.replace("HUNTER-", "");
            const packBadge = u.pack_size > 1 ? ` • PACK ${u.pack_role} (x${u.pack_size})` : "";
            return `
              <div class="unit-row ${sel}" data-uid="${escapeHtml(u.unit_id)}">
                <div class="row-top">
                  <span class="u-title">${escapeHtml(u.unit_id)} <small>(${escapeHtml(u.tier.toUpperCase())} • ${escapeHtml(shortDoc)})</small></span>
                  <span class="${bCls} u-badge">${escapeHtml(u.state)}</span>
                </div>
                <div class="row-sub">${escapeHtml(u.current_task || "Patrolling sector")}${escapeHtml(packBadge)}</div>
              </div>
            `;
          })
          .join("");
        elUnitRoster.scrollTop = prevScroll;
      } else {
        // In-place DOM update: zero layout/scroll reset, zero click interruption
        for (let i = 0; i < units.length; i++) {
          const u = units[i];
          const row = elUnitRoster.children[i];
          if (!row) continue;
          const isSel = engine.selectedKind === "unit" && engine.selectedId === u.unit_id;
          row.classList.toggle("selected", isSel);
          const doc = u.doctrine || "HUNTER-SEEKER";
          const shortDoc = doc.replace("HUNTER-", "");
          const titleEl = row.querySelector(".u-title");
          const wantTitle = `${escapeHtml(u.unit_id)} <small>(${escapeHtml(u.tier.toUpperCase())} • ${escapeHtml(shortDoc)})</small>`;
          if (titleEl && titleEl.innerHTML !== wantTitle) titleEl.innerHTML = wantTitle;
          const badgeEl = row.querySelector(".u-badge");
          if (badgeEl) {
            const wantCls = `${badgeClassForState(u.state, u.caste)} u-badge`;
            if (badgeEl.className !== wantCls) badgeEl.className = wantCls;
            if (badgeEl.textContent !== u.state) badgeEl.textContent = u.state;
          }
          const subEl = row.querySelector(".row-sub");
          const packBadge = u.pack_size > 1 ? ` • PACK ${u.pack_role} (x${u.pack_size})` : "";
          const wantSub = `${u.current_task || "Patrolling sector"}${packBadge}`;
          if (subEl && subEl.textContent !== wantSub) subEl.textContent = wantSub;
        }
      }
    }

    const nodes = latestSnapshot.nodes || [];
    const nodeSig =
      `${engine.selectedKind}|${engine.selectedId}|` +
      nodes
        .map((n) => {
          const m = n.metadata || {};
          return `${n.node_id}:${n.label}:${n.status}:${m.listening}:${m.connections}:${m.merkle_root || ""}`;
        })
        .join(";");

    if (force || nodeSig !== lastNodeRosterSig) {
      lastNodeRosterSig = nodeSig;
      const nodeIdsSig = nodes.map((n) => n.node_id).join(",");

      if (nodeIdsSig !== lastNodeIdsSig || elNodeRoster.children.length !== nodes.length) {
        lastNodeIdsSig = nodeIdsSig;
        const prevNodeScroll = elNodeRoster.scrollTop;
        elNodeRoster.innerHTML = nodes
          .map((n) => {
            const sel = engine.selectedKind === "node" && engine.selectedId === n.node_id ? "selected" : "";
            const meta = n.metadata || {};
            const isListening = !!meta.listening;
            const bCls =
              n.kind === "threat" || n.status === "quarantined" || n.status === "under_attack"
                ? "badge badge-defense"
                : n.kind === "harvest_target"
                ? "badge badge-active"
                : isListening || (n.node_id && n.node_id.startsWith("merkle-root-"))
                ? "badge badge-sanitize"
                : "badge badge-patrol";

            let subDetail = `Kind: ${escapeHtml(n.kind)} • Pos: [${n.position.join(", ")}]`;
            if (n.kind === "bastion") {
              subDetail = isListening
                ? `LIVE PID ${escapeHtml(meta.pid || "-")} (${escapeHtml(meta.process || "os")}) • Bind ${escapeHtml(meta.bind_ip || "127.0.0.1")} • ${meta.connections || 0} peers`
                : `Port :${escapeHtml(meta.port)} CLOSED / STANDBY`;
            } else if (n.node_id && n.node_id.startsWith("merkle-root-")) {
              subDetail = `BLAKE2b ${escapeHtml((meta.merkle_root || "").slice(0, 16))}… • ${meta.file_count || 0} files verified`;
            }

            return `
              <div class="node-row ${sel}" data-nid="${escapeHtml(n.node_id)}">
                <div class="row-top">
                  <span class="n-title">${escapeHtml(n.label)}</span>
                  <span class="${bCls} n-badge">${escapeHtml(n.status)}</span>
                </div>
                <div class="row-sub">${subDetail}</div>
              </div>
            `;
          })
          .join("");
        elNodeRoster.scrollTop = prevNodeScroll;
      } else {
        for (let i = 0; i < nodes.length; i++) {
          const n = nodes[i];
          const row = elNodeRoster.children[i];
          if (!row) continue;
          const isSel = engine.selectedKind === "node" && engine.selectedId === n.node_id;
          row.classList.toggle("selected", isSel);
          const meta = n.metadata || {};
          const isListening = !!meta.listening;
          const bCls =
            n.kind === "threat" || n.status === "quarantined" || n.status === "under_attack"
              ? "badge badge-defense"
              : n.kind === "harvest_target"
              ? "badge badge-active"
              : isListening || (n.node_id && n.node_id.startsWith("merkle-root-"))
              ? "badge badge-sanitize"
              : "badge badge-patrol";

          const titleEl = row.querySelector(".n-title");
          if (titleEl && titleEl.textContent !== n.label) titleEl.textContent = n.label;
          const badgeEl = row.querySelector(".n-badge");
          if (badgeEl) {
            const wantCls = `${bCls} n-badge`;
            if (badgeEl.className !== wantCls) badgeEl.className = wantCls;
            if (badgeEl.textContent !== n.status) badgeEl.textContent = n.status;
          }
          let subDetail = `Kind: ${n.kind} • Pos: [${n.position.join(", ")}]`;
          if (n.kind === "bastion") {
            subDetail = isListening
              ? `LIVE PID ${meta.pid || "-"} (${meta.process || "os"}) • Bind ${meta.bind_ip || "127.0.0.1"} • ${meta.connections || 0} peers`
              : `Port :${meta.port} CLOSED / STANDBY`;
          } else if (n.node_id && n.node_id.startsWith("merkle-root-")) {
            subDetail = `BLAKE2b ${(meta.merkle_root || "").slice(0, 16)}… • ${meta.file_count || 0} files verified`;
          }
          const subEl = row.querySelector(".row-sub");
          if (subEl && subEl.textContent !== subDetail) subEl.textContent = subDetail;
        }
      }
    }
  }

  function renderInspector(force) {
    if (!latestSnapshot) return;
    // Do not wipe out Inspector DOM while user is hovering clickable links or highlighting text
    if (!force && (elInspector.matches(":hover") || hasActiveSelectionInside(elInspector))) {
      return;
    }
    const nowMs = performance.now();
    if (!force && nowMs - lastInspectorRenderMs < 280) {
      return;
    }

    const ht = latestSnapshot.host_telemetry || {};

    if (!engine.selectedId || engine.selectedKind === "core") {
      const rootsObj = ht.merkle_roots || {};
      const rootsStr = Object.entries(rootsObj)
        .map(([k, v]) => `${k.replace(" Workspace", "")}: ${String(v).slice(0, 8)}…`)
        .join(" • ");
      const remotePeersStr = (ht.remote_peers_sample || []).slice(0, 3).join(" • ") || "0 external sockets";
      const newPortsArr = ht.new_listening_ports || [];
      const newPortsStr = newPortsArr.length > 0 ? `⚠ ${newPortsArr.join(", ")}` : "0 new ports (baseline intact)";

      const bannedList = (ht.banned_peers || []).slice(0, 4);
      const bannedPills = bannedList.length
        ? `<div style="margin-top:3px;">` +
          bannedList
            .map(
              (b) =>
                `<span class="doc-pill-link" data-unban-ip="${escapeHtml(b.ip)}" title="Banned: ${escapeHtml(b.reason || '')} • Click to unban">🚫 ${escapeHtml(b.ip)} (x${b.hits_blocked || 1})</span>`
            )
            .join("") +
          `</div>`
        : "";

      const immCount = ht.immunized_hashes_count ?? 0;

      const harvFiles = (ht.recent_harvest_files || []).slice(0, 4);
      const harvPills = harvFiles.length
        ? harvFiles
            .map(
              (f) =>
                `<span class="doc-pill-link" data-doc-kind="harvest" data-doc-name="${escapeHtml(f)}" title="Click to read ${escapeHtml(f)}">📄 ${escapeHtml(f.replace(/\.md$/i, ""))}</span>`
            )
            .join("")
        : "None yet";

      const quarFiles = (ht.recent_quarantine_files || []).slice(0, 4);
      const quarPills = quarFiles.length
        ? quarFiles
            .map(
              (f) =>
                `<span class="doc-pill-link" data-doc-kind="quarantine" data-doc-name="${escapeHtml(f)}" title="Click to inspect forensics ${escapeHtml(f)}">🔍 ${escapeHtml(f.replace(/\.json$/i, ""))}</span>`
            )
            .join("")
        : "None yet";

      const html = `
        <div class="insp-grid">
          <div class="insp-key">SOVEREIGN HOST</div><div class="insp-val"><strong>${escapeHtml(ht.hostname || "ATRIA")} (${escapeHtml(ht.os || "Windows")})</strong></div>
          <div class="insp-key">LIVE CPU / RAM</div><div class="insp-val">${ht.cpu_percent ?? 0}% CPU • ${ht.ram_used_gb ?? 0} / ${ht.ram_total_gb ?? 64} GiB (${ht.ram_percent ?? 0}%)</div>
          <div class="insp-key">NET I/O</div><div class="insp-val">↑ ${ht.net_sent_mb ?? 0} MiB sent • ↓ ${ht.net_recv_mb ?? 0} MiB recv</div>
          <div class="insp-key">OS TCP SOCKETS</div><div class="insp-val">${ht.listening_tcp_count ?? 0} LISTENING • ${ht.established_tcp_count ?? 0} ESTABLISHED</div>
          <div class="insp-key">REMOTE PEERS</div><div class="insp-val">${ht.wan_peers_count ?? 0} WAN • ${ht.lan_peers_count ?? 0} LAN • ${ht.loopback_peers_count ?? 0} LOOP (${escapeHtml(remotePeersStr)})</div>
          <div class="insp-key">PORT BASELINE</div><div class="insp-val">${escapeHtml(newPortsStr)}</div>
          <div class="insp-key">BLACKLIST / IMM</div><div class="insp-val">${ht.banned_peers_count ?? 0} Banned IPs • ${immCount} Immunized Hashes${bannedPills}</div>
          <div class="insp-key">MERKLE ANCHORS</div><div class="insp-val">${ht.merkle_files_hashed ?? 0} files (${escapeHtml(rootsStr)})</div>
          <div class="insp-key">SHADOW CACHE</div><div class="insp-val">${ht.merkle_shadow_files ?? 0} files (${ht.merkle_shadow_kb ?? 0} KiB RAM comparison snapshots)</div>
          <div class="insp-key">DISK HARVESTS</div><div class="insp-val">${ht.harvest_reports_on_disk ?? 0} reports (click to read):<br/>${harvPills}</div>
          <div class="insp-key">QUARANTINE VAULT</div><div class="insp-val">${ht.quarantine_files_on_disk ?? 0} forensics JSONs (click to read):<br/>${quarPills}</div>
        </div>
      `;
      if (force || html !== lastInspectorSig) {
        lastInspectorSig = html;
        lastInspectorRenderMs = nowMs;
        const prevScroll = elInspector.scrollTop;
        elInspector.innerHTML = html;
        elInspector.scrollTop = prevScroll;
      }
      return;
    }

    if (engine.selectedKind === "unit") {
      const u = (latestSnapshot.units || []).find((x) => x.unit_id === engine.selectedId);
      if (!u) {
        engine.selectedId = null;
        engine.selectedKind = null;
        renderInspector(true);
        return;
      }
      const packStr = u.pack_id ? `${u.pack_role} (${u.pack_id} • Slot ${u.pack_slot + 1}/${u.pack_size})` : "SOLO ORBITAL";
      const posFixed = (u.position || [0, 0, 0]).map((v) => Number(v).toFixed(1)).join(", ");
      const velFixed = (u.velocity || [0, 0, 0]).map((v) => Number(v).toFixed(1)).join(", ");
      const html = `
        <div class="insp-grid">
          <div class="insp-key">UNIT CALLSIGN</div><div class="insp-val"><strong>${escapeHtml(u.unit_id)}</strong></div>
          <div class="insp-key">MATRIX DOCTRINE</div><div class="insp-val"><strong>${escapeHtml(u.doctrine || "HUNTER-SEEKER")}</strong></div>
          <div class="insp-key">SWARM PACK</div><div class="insp-val">${escapeHtml(packStr)}</div>
          <div class="insp-key">CASTE LOCK</div><div class="insp-val">${escapeHtml(u.caste.toUpperCase())} (v${u.version})</div>
          <div class="insp-key">VISUAL MODEL</div><div class="insp-val">${escapeHtml(u.tier.toUpperCase())} (${u.tentacles} IK Tentacles)</div>
          <div class="insp-key">FSM STATE</div><div class="insp-val">${escapeHtml(u.state)}</div>
          <div class="insp-key">CURRENT TASK</div><div class="insp-val">${escapeHtml(u.current_task)}</div>
          <div class="insp-key">3D POSITION</div><div class="insp-val">[${posFixed}]</div>
          <div class="insp-key">3D VELOCITY</div><div class="insp-val">[${velFixed}]</div>
          <div class="insp-key">LASER STATUS</div><div class="insp-val">${u.laser_active ? "ACTIVE (" + escapeHtml(u.laser_kind.toUpperCase()) + ")" : "STANDBY"}</div>
          <div class="insp-key">MISSIONS</div><div class="insp-val">${u.missions_completed} completed • ${u.security_events || 0} security events</div>
          <div class="insp-key">THROUGHPUT</div><div class="insp-val">${(u.bytes_processed / 1024).toFixed(2)} KiB verified</div>
        </div>
      `;
      if (force || html !== lastInspectorSig) {
        lastInspectorSig = html;
        lastInspectorRenderMs = nowMs;
        const prevScroll = elInspector.scrollTop;
        elInspector.innerHTML = html;
        elInspector.scrollTop = prevScroll;
      }
    } else if (engine.selectedKind === "node") {
      const n = (latestSnapshot.nodes || []).find((x) => x.node_id === engine.selectedId);
      if (!n) {
        engine.selectedId = null;
        engine.selectedKind = null;
        renderInspector(true);
        return;
      }
      const meta = n.metadata || {};
      const metaRows = Object.entries(meta)
        .filter(([k]) => k !== "diffs")
        .map(
          ([k, v]) =>
            `<div class="insp-key">${escapeHtml(k.toUpperCase())}</div><div class="insp-val">${escapeHtml(typeof v === "object" ? JSON.stringify(v) : String(v))}</div>`
        )
        .join("");


      const html = `
        <div class="insp-grid">
          <div class="insp-key">NODE ID</div><div class="insp-val"><strong>${escapeHtml(n.node_id)}</strong></div>
          <div class="insp-key">LABEL</div><div class="insp-val">${escapeHtml(n.label)}</div>
          <div class="insp-key">KIND / STATUS</div><div class="insp-val">${escapeHtml(n.kind.toUpperCase())} / ${escapeHtml(n.status.toUpperCase())}</div>
          <div class="insp-key">SEVERITY</div><div class="insp-val">${escapeHtml(n.severity.toUpperCase())}</div>
          <div class="insp-key">ACTION</div><div class="insp-val">Observation only; inspect evidence below.</div>
          <div class="insp-key">3D COORDS</div><div class="insp-val">[${n.position.join(", ")}]</div>
          ${metaRows}
        </div>
      `;
      if (force || html !== lastInspectorSig) {
        lastInspectorSig = html;
        lastInspectorRenderMs = nowMs;
        const prevScroll = elInspector.scrollTop;
        elInspector.innerHTML = html;
        elInspector.scrollTop = prevScroll;
      }
    } else if (engine.selectedKind === "receipt") {
      const r = (latestSnapshot.recent_receipts || []).find((x) => x.receipt_id === engine.selectedId);
      if (!r) {
        engine.selectedId = null;
        engine.selectedKind = null;
        renderInspector(true);
        return;
      }
      const meta = r.metadata || {};
      const reportFile = meta.report_file ? String(meta.report_file).split(/[\\/]/).pop() : "";
      const reportPill = reportFile
        ? `<span class="doc-pill-link" data-doc-kind="harvest" data-doc-name="${escapeHtml(reportFile)}">📄 OPEN MARKDOWN REPORT (${escapeHtml(reportFile)})</span>`
        : "";
      const receiptPill = `<span class="doc-pill-link" data-doc-kind="receipt" data-doc-name="${escapeHtml(r.receipt_id)}">🔍 EXPAND FULL WARRANT JSON</span>`;

      const html = `
        <div class="insp-grid">
          <div class="insp-key">WARRANT ID</div><div class="insp-val"><strong>[WARRANT:${escapeHtml(r.receipt_id)}]</strong></div>
          <div class="insp-key">UNIT / CASTE</div><div class="insp-val">${escapeHtml(r.unit_id)} (${escapeHtml(r.caste.toUpperCase())})</div>
          <div class="insp-key">SHA-256</div><div class="insp-val">${escapeHtml(r.sha256 || "")}</div>
          <div class="insp-key">SOURCE</div><div class="insp-val">${escapeHtml(r.source)}</div>
          <div class="insp-key">DOSSIER</div><div class="insp-val">${receiptPill} ${reportPill}</div>
          <div class="insp-key">VERIFIED SPAN</div><div class="insp-val" style="max-height:95px;overflow-y:auto;user-select:text;">${escapeHtml(r.span)}</div>
        </div>
      `;
      if (force || html !== lastInspectorSig) {
        lastInspectorSig = html;
        lastInspectorRenderMs = nowMs;
        const prevScroll = elInspector.scrollTop;
        elInspector.innerHTML = html;
        elInspector.scrollTop = prevScroll;
      }
    }
  }

  function renderReceipts(force) {
    if (!latestSnapshot) return;
    if (!force && elReceiptFeed.matches(":hover")) return;
    const receipts = (latestSnapshot.recent_receipts || []).slice().reverse();
    const sig =
      `${engine.selectedKind}|${engine.selectedId}|` +
      receipts.map((r) => r.receipt_id).join(",");

    if (!force && sig === lastReceiptsSig) return;
    lastReceiptsSig = sig;

    const prevScroll = elReceiptFeed.scrollTop;
    elReceiptFeed.innerHTML = receipts
      .map((r) => {
        const sel = engine.selectedKind === "receipt" && engine.selectedId === r.receipt_id ? "selected" : "";
        const bCls = r.ok ? "badge badge-sanitize" : "badge badge-defense";
        return `
          <div class="receipt-row ${sel}" data-rid="${escapeHtml(r.receipt_id)}" title="Click to inspect • Double-click to open full Warrant Reader">
            <div class="row-top">
              <span>${escapeHtml(r.receipt_id)} • ${escapeHtml(r.unit_id)}</span>
              <span class="${bCls}">${escapeHtml(r.caste)}</span>
            </div>
            <div class="row-sub">${escapeHtml(r.span)}</div>
          </div>
        `;
      })
      .join("");
    elReceiptFeed.scrollTop = prevScroll;
  }

  function matchesLogFilter(entry, filter, query) {
    const lvl = (entry.level || "").toUpperCase();
    const cat = (entry.caste || "").toLowerCase();
    const src = (entry.unit_id || "").toUpperCase();

    if (filter === "threat") {
      const ok =
        lvl === "THREAT" ||
        lvl === "BLOCK" ||
        lvl === "CRITICAL" ||
        lvl === "WARDEN" ||
        lvl === "ALERT" ||
        lvl === "EMP" ||
        cat.includes("warden");
      if (!ok) return false;
    } else if (filter === "sanitize") {
      if (!(lvl === "SANITIZE" || cat.includes("sanitize") || src.includes("SAN"))) return false;
    } else if (filter === "harvest") {
      if (!(lvl === "HARVEST" || lvl === "WARRANT" || cat.includes("harvest") || src.includes("HRV"))) return false;
    } else if (filter === "tripwire") {
      if (!(lvl === "TRIPWIRE" || cat.includes("tripwire") || src.includes("TRP"))) return false;
    }

    if (query) {
      const hay = `${entry.unit_id || ""} ${entry.caste || ""} ${entry.phase || ""} ${entry.message || ""} ${JSON.stringify(entry.details || {})}`.toLowerCase();
      if (!hay.includes(query)) return false;
    }
    return true;
  }

  function formatLogDetails(details) {
    if (!details || typeof details !== "object") return "";
    const parts = [];
    for (const [k, v] of Object.entries(details)) {
      if (v === undefined || v === null || v === "") continue;
      if (Array.isArray(v) && v.length === 0) continue;
      const valStr = typeof v === "object" ? JSON.stringify(v) : String(v);
      parts.push(`${k}=${valStr.slice(0, 70)}`);
    }
    return parts.length ? `[${parts.join(" | ")}]` : "";
  }

  function renderTelemetryConsole(force) {
    if (!latestSnapshot) return;
    if (isLogPaused && !force) return;
    if (!force && hasActiveSelectionInside(elConsoleBody)) return;

    const logs = latestSnapshot.telemetry_log || [];
    const newestSeq = logs.length ? logs[logs.length - 1].seq : 0;
    if (!force && newestSeq === lastRenderedLogSeq) return;
    lastRenderedLogSeq = newestSeq;

    const q = (logSearchQuery || "").trim().toLowerCase();
    const filtered = logs.filter((e) => matchesLogFilter(e, activeLogFilter, q)).slice().reverse();
    const prevScroll = elConsoleBody.scrollTop;
    elConsoleBody.innerHTML = filtered
      .map((e) => {
        const rawLvl = (e.level || "INFO").toUpperCase();
        const cssLvl = rawLvl === "WARDEN" || rawLvl === "ALERT" || rawLvl === "EMP" ? "THREAT" : rawLvl;
        const tsShort = escapeHtml(e.iso_time || "");
        const src = escapeHtml(e.unit_id || "HIVE");
        const phase = e.phase ? `(${escapeHtml(e.phase)}) ` : "";
        const summary = escapeHtml(e.message || "");
        const meta = escapeHtml(formatLogDetails(e.details));
        return `
          <div class="log-line lvl-${cssLvl}" data-uid="${src}" title="Click to lock Chase-Cam onto ${src}">
            <span class="log-ts">${tsShort}</span>
            <span class="log-lvl lvl-tag-${cssLvl}">${escapeHtml(rawLvl)}</span>
            <span class="log-src">[${src}]</span>
            <span class="log-msg">${phase}${summary} <span class="log-meta">${meta}</span></span>
          </div>
        `;
      })
      .join("");
    elConsoleBody.scrollTop = prevScroll;
  }

  function setTextIfChanged(el, val) {
    if (!el) return;
    const s = String(val);
    if (el.textContent !== s) el.textContent = s;
  }

  function applySnapshot(snap) {
    latestSnapshot = snap;
    engine.syncSnapshot(snap);

    if (snap.theme && snap.theme.id) {
      if (document.documentElement.getAttribute("data-theme") !== snap.theme.id) {
        document.documentElement.setAttribute("data-theme", snap.theme.id);
      }
      if (elThemeSelect.value !== snap.theme.id && document.activeElement !== elThemeSelect) {
        elThemeSelect.value = snap.theme.id;
      }
      setTextIfChanged(elFooterTheme, `Atmosphere: ${snap.theme.label} (${snap.theme.bg0} / ${snap.theme.accent})`);
    }

    const m = snap.metrics || {};
    const bc = m.by_caste || {};
    setTextIfChanged(elUnits, `${m.total_units || 0}/${m.max_units || 64}`);
    setTextIfChanged(elHrv, bc.harvester || 0);
    setTextIfChanged(elWrd, bc.warden || 0);
    setTextIfChanged(elSan, bc.sanitizer || 0);
    setTextIfChanged(elTrp, bc.tripwire || 0);
    setTextIfChanged(elWarrants, m.warrants_minted || 0);
    setTextIfChanged(elThreats, m.security_events || 0);

    if (elTierSelect && m.default_tier && document.activeElement !== elTierSelect && elTierSelect.value !== m.default_tier) {
      elTierSelect.value = m.default_tier;
    }

    if (snap.emp && snap.emp.tripped) {
      elEmpBanner.classList.remove("hidden");
      elBeacon.classList.add("emp-active");
      setTextIfChanged(elEmpReason, `Reason: ${snap.emp.reason || "Software emergency stop"}`);
    } else {
      elEmpBanner.classList.add("hidden");
      elBeacon.classList.remove("emp-active");
    }

    if (snap.castes && engine && typeof engine.updateCasteProfiles === "function") {
      engine.updateCasteProfiles(snap.castes);
      syncCasteTabs(snap.castes);
    }

    renderTacticalBanner();
    renderRoster(false);
    renderInspector(false);
    renderReceipts(false);
    renderTelemetryConsole(false);
  }

  let lastKnownCasteIds = "";
  function syncCasteTabs(castes) {
    if (!castes || !castes.length) return;
    const sig = castes.map((c) => c.caste_id).sort().join(",");
    if (sig === lastKnownCasteIds) return;
    lastKnownCasteIds = sig;
    const container = document.querySelector(".caste-tabs");
    if (!container) return;
    const existing = new Set(
      Array.from(container.querySelectorAll(".caste-tab")).map((b) => b.getAttribute("data-caste"))
    );
    for (const c of castes) {
      if (!existing.has(c.caste_id)) {
        const btn = document.createElement("button");
        btn.className = "caste-tab";
        btn.setAttribute("data-caste", c.caste_id);
        btn.textContent = (c.code_prefix || c.caste_id.slice(0, 3)).toUpperCase();
        btn.title = `${c.title || c.caste_id} (${c.single_purpose || ""})`;
        container.appendChild(btn);
      }
    }
  }

  // Connect 30 Hz WebSocket
  function connectWebSocket() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws/telemetry`);
    ws.onopen = () => {
      ws.send(JSON.stringify({ op: "hello", token: sessionToken() }));
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.op === "world_snapshot" && msg.data) {
          applySnapshot(msg.data);
        }
      } catch (_e) {}
    };
    ws.onclose = () => {
      setTimeout(connectWebSocket, 1200);
    };
  }
  connectWebSocket();

  // Caste Filter Tabs (event delegation handles dynamically added castes)
  const elCasteTabs = document.querySelector(".caste-tabs");
  if (elCasteTabs) {
    elCasteTabs.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".caste-tab");
      if (!btn) return;
      document.querySelectorAll(".caste-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      activeCasteFilter = btn.getAttribute("data-caste") || "all";
      const lbl = document.getElementById("roster-filter-label");
      if (lbl) lbl.textContent = activeCasteFilter.toUpperCase();
      renderRoster(true);
    });
  }


  // Swarm Spawner (+ / -)
  const elBtnSpawn = document.getElementById("btn-spawn-unit");
  const elBtnRetire = document.getElementById("btn-retire-unit");

  if (elBtnSpawn) {
    elBtnSpawn.addEventListener("click", () => {
      const targetCaste = activeCasteFilter === "all" ? "harvester" : activeCasteFilter;
      fetch("/api/overseer/scale", {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ caste: targetCaste, delta: 1 }),
      });
    });
  }
  if (elBtnRetire) {
    elBtnRetire.addEventListener("click", () => {
      const targetCaste = activeCasteFilter === "all" ? "harvester" : activeCasteFilter;
      fetch("/api/overseer/scale", {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ caste: targetCaste, delta: -1 }),
      });
    });
  }
  // Telemetry Log Filter Buttons, Search Box, Pause Toggle & Open Folder Buttons
  document.querySelectorAll(".log-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".log-filter").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      activeLogFilter = btn.getAttribute("data-filter") || "all";
      renderTelemetryConsole(true);
    });
  });

  if (elLogSearch) {
    elLogSearch.addEventListener("input", () => {
      logSearchQuery = elLogSearch.value || "";
      renderTelemetryConsole(true);
    });
  }

  if (elBtnLogPause) {
    elBtnLogPause.addEventListener("click", () => {
      isLogPaused = !isLogPaused;
      elBtnLogPause.classList.toggle("active", isLogPaused);
      elBtnLogPause.textContent = isLogPaused ? "▶ RESUME" : "⏸ PAUSE";
      if (elConsoleLiveDot) {
        elConsoleLiveDot.classList.toggle("paused", isLogPaused);
      }
      if (!isLogPaused) {
        renderTelemetryConsole(true);
      }
    });
  }

  const elBtnOpenHarvests = document.getElementById("btn-open-harvests");
  const elBtnOpenQuarantine = document.getElementById("btn-open-quarantine");
  const elBtnOpenLogs = document.getElementById("btn-open-logs");
  if (elBtnOpenHarvests) elBtnOpenHarvests.addEventListener("click", () => openFolderInExplorer("harvest"));
  if (elBtnOpenQuarantine) elBtnOpenQuarantine.addEventListener("click", () => openFolderInExplorer("quarantine"));
  if (elBtnOpenLogs) elBtnOpenLogs.addEventListener("click", () => openFolderInExplorer("logs"));

  function clearLockAndResetCamera() {
    engine.selectedId = null;
    engine.selectedKind = null;
    setCameraAndSave("orbit");
    renderInspector(true);
    renderRoster(true);
    renderReceipts(true);
  }

  document.getElementById("btn-unselect").addEventListener("click", clearLockAndResetCamera);

  elThemeSelect.addEventListener("change", () => {
    const theme = elThemeSelect.value;
    try {
      localStorage.setItem("sentinel_theme_id", theme);
    } catch (_e) {}
    fetch("/api/overseer/theme", {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ theme }),
    });
  });

  elCamSelect.addEventListener("change", () => {
    setCameraAndSave(elCamSelect.value);
  });

  async function sendMission(url, payload) {
    const feedback = document.getElementById("mission-feedback");
    if (feedback) feedback.textContent = "Submitting mission...";
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "Mission rejected");
      if (feedback) feedback.textContent = "Mission accepted. Live progress appears above.";
    } catch (error) {
      if (feedback) feedback.textContent = error.message || "Mission request failed";
    }
  }

  document.getElementById("btn-demo-wave").addEventListener("click", () => {
    const scenario = elScenarioSelect ? elScenarioSelect.value : "live_research_swarm";
    const qInput = document.getElementById("live-query-input");
    const query = qInput ? qInput.value : "";
    sendMission("/api/overseer/scenario", { scenario, query });
  });

  const elLiveMode = document.getElementById("live-mode-select");
  const elLiveQuery = document.getElementById("live-query-input");
  const elBtnLiveDispatch = document.getElementById("btn-live-dispatch");

  function triggerLiveMission() {
    const mode = elLiveMode ? elLiveMode.value : "multi";
    const query = elLiveQuery ? elLiveQuery.value : "";
    sendMission("/api/overseer/mission", { mode, query });
  }

  if (elBtnLiveDispatch) {
    elBtnLiveDispatch.addEventListener("click", triggerLiveMission);
  }
  if (elLiveQuery) {
    elLiveQuery.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        triggerLiveMission();
      }
    });
  }

  document.getElementById("btn-emp-halt").addEventListener("click", () => {
    engine.triggerEmpShockwave();
    fetch("/api/overseer/emp", {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ reason: "Overseer emergency stop" }),
    });
  });

  document.getElementById("btn-emp-restore").addEventListener("click", () => {
    fetch("/api/overseer/emp", {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ restore: true }),
    });
  });

  // Tactical Keyboard Shortcuts (1-4 Camera, Tab Cycle Sentinel, Esc Clear/Close, F11 Fullscreen)
  window.addEventListener("keydown", (ev) => {
    const tag = (ev.target && ev.target.tagName ? ev.target.tagName : "").toUpperCase();
    const isInput = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

    if (ev.key === "Escape") {
      if (elModal && !elModal.classList.contains("hidden")) {
        ev.preventDefault();
        closeDossierModal();
        return;
      }
      if (isInput) {
        ev.target.blur();
        return;
      }
      clearLockAndResetCamera();
      return;
    }

    if (isInput) return;

    if (ev.key === "1") {
      setCameraAndSave("orbit");
    } else if (ev.key === "2") {
      setCameraAndSave("top");
    } else if (ev.key === "3") {
      setCameraAndSave("core");
    } else if (ev.key === "4") {
      setCameraAndSave("chase");
    } else if (ev.key === "Tab") {
      ev.preventDefault();
      if (!latestSnapshot || !latestSnapshot.units || !latestSnapshot.units.length) return;
      const units = latestSnapshot.units.filter(
        (u) => activeCasteFilter === "all" || u.caste === activeCasteFilter
      );
      if (!units.length) return;
      const curIdx = units.findIndex((u) => u.unit_id === engine.selectedId);
      const step = ev.shiftKey ? -1 : 1;
      const nextIdx = (curIdx + step + units.length) % units.length;
      engine.selectedId = units[nextIdx].unit_id;
      engine.selectedKind = "unit";
      setCameraAndSave("chase");
      renderInspector(true);
      renderRoster(true);
    }
  });
})();
