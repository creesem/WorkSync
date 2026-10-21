"use strict";

const TOKEN = window.__GUI_TOKEN__ || "";
const TOKEN_HEADER = "X-Gui-Token";
const DEFAULT_SECTION = "command-center";

// Ticket 18: the override kinds in the order the detail pane offers them, with the label a
// button uses and the label a My Priorities row shows once the override is active. The row
// indicator never claims a refused override was applied: it says "<action> refused" instead.
const overrideKinds = ["pin", "focus_today", "defer", "not_relevant", "always_prioritize"];
const overrideActionLabels = {
  pin: "Pin",
  focus_today: "Focus today",
  defer: "Defer",
  not_relevant: "Not relevant",
  always_prioritize: "Always prioritize",
};
const overrideIndicators = {
  pin: "Pinned",
  focus_today: "Focus today",
  defer: "Deferred",
  not_relevant: "Not relevant",
  always_prioritize: "Always prioritized",
};

const state = {
  triage: [],
  queueTab: "triage",
  duplicates: [],
  clarification: [],
  krisp: [],
  identity: [],
  detailKey: null,
  // CC-03: the layout profile the Command Center route returned, and the source of truth
  // for the "Me", hide/show, and reorder controls.
  profile: null,
};

const view = document.getElementById("view");
const equivalent = document.getElementById("equivalent");
const vaultName = document.getElementById("vault-name");
const writeResult = document.getElementById("write-result");
const captureInput = document.getElementById("capture-input");
const captureSubmit = document.getElementById("capture-submit");
const captureStatus = document.getElementById("capture-status");
const detail = document.getElementById("detail");
const layoutBar = document.getElementById("layout-bar");
const layoutSections = document.getElementById("layout-sections");
const meSelect = document.getElementById("me-select");

// Ticket 11: the vault name for canonical links is read once from /api/settings and cached,
// so opening a detail pane never blocks on a second settings read.
const vaultNameOnce = api("/api/settings")
  .then((data) => data.vault_name || "")
  .catch(() => "");

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
  });
}

async function api(path) {
  const response = await fetch(path, { headers: { [TOKEN_HEADER]: TOKEN } });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.message || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function postAction(name, payload) {
  const response = await fetch(`/api/action/${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { [TOKEN_HEADER]: TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.message || `${response.status} ${response.statusText}`);
  }
  return data;
}

function showWriteResult(result, isError) {
  if (isError) {
    writeResult.innerHTML = `<div class="write-error">${escapeHtml(result.error)}</div>`;
    return;
  }
  const changes = (result.changes || [])
    .map(
      (change) =>
        `<li>${escapeHtml(change.kind)} ${escapeHtml(change.path)}${
          change.zone ? ` <span class="tag">${escapeHtml(change.zone)}</span>` : ""
        }</li>`
    )
    .join("");
  writeResult.innerHTML = `<div class="write-ok">
    <p>${escapeHtml(result.action)} — committed ${escapeHtml(String(result.committed))}${
      result.reviewer ? ` by ${escapeHtml(result.reviewer)}` : ""
    }</p>
    ${changes ? `<ul>${changes}</ul>` : ""}
    ${result.equivalent_cli ? `<code>${escapeHtml(result.equivalent_cli)}</code>` : ""}
  </div>`;
}

let captureStatusTimer = null;
let captureInFlight = false;

function showCaptureStatus(message, isError) {
  captureStatus.textContent = message;
  captureStatus.classList.toggle("error", Boolean(isError));
  if (captureStatusTimer) clearTimeout(captureStatusTimer);
  if (!isError) {
    captureStatusTimer = setTimeout(() => {
      captureStatus.textContent = "";
    }, 4000);
  }
}

async function submitCapture() {
  // Ticket 12: Enter and the button both land here, so a single guard keeps one capture in
  // flight; a second Enter would otherwise race the first and overwrite its status text.
  if (captureInFlight) return;
  const text = captureInput.value.trim();
  if (!text) {
    showCaptureStatus("Captured text must not be empty.", true);
    return;
  }
  captureInFlight = true;
  captureSubmit.disabled = true;
  try {
    const result = await postAction("capture", { text });
    captureInput.value = "";
    // Ticket 12: recapturing text that was already decided returns that proposal rather than
    // a fresh pending one, so report the status the queue actually holds.
    const status = (result.proposal && result.proposal.status) || "pending";
    showCaptureStatus(status === "pending" ? "Captured" : `Already captured (${status})`, false);
  } catch (error) {
    showCaptureStatus(String(error.message || error), true);
  } finally {
    captureInFlight = false;
    captureSubmit.disabled = false;
  }
}

// Ticket 11: the on-demand detail pane and the canonical obsidian:// link.

function quoteForUrl(value) {
  // Reproduces html/links.py's urllib.parse.quote(str(value), safe="/"): "/" stays literal
  // and "!'()*" are percent-encoded, which bare encodeURIComponent would leave alone. Keeps
  // the frontend's link byte-identical to note_url without importing the html package.
  return String(value ?? "")
    .split("/")
    .map((segment) =>
      encodeURIComponent(segment).replace(
        /[!'()*]/g,
        (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`
      )
    )
    .join("/");
}

function noteUrl(name, path) {
  // Mirrors html/links.py::note_url: normalize "\" to "/", strip a trailing .md.
  const file = String(path || "")
    .replace(/\\/g, "/")
    .replace(/\.md$/i, "");
  return `obsidian://open?vault=${quoteForUrl(name || "")}&file=${quoteForUrl(file)}`;
}

function detailField(label, value) {
  if (value === undefined || value === null || value === "") return "";
  return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd>`;
}

// Ticket 18: the detail pane's override controls. The requested kind is marked active; a
// refused override still carries its requested kind on the row, so the refusal is stated by
// the My Priorities banner rather than a misleading "Deferred" chip.
function overrideButtons(activeKind) {
  const buttons = overrideKinds.map((kind) => {
    const active = kind === activeKind;
    return `<button type="button" class="${active ? "active" : ""}" data-override-kind="${kind}"
      aria-pressed="${active}">${escapeHtml(overrideActionLabels[kind])}</button>`;
  });
  buttons.push('<button type="button" class="override-clear" data-clear-override="1">Clear</button>');
  return buttons.join("");
}

// Ticket 11: a selection can await the cached vault name, and a section change closes the
// pane in that window; this counter lets the stale selection notice it lost and bail.
let detailGeneration = 0;

async function selectItem(node) {
  const item = node.dataset;
  const key = `${item.path || ""}\u0000${item.label || ""}`;
  if (!detail.hidden && state.detailKey === key) {
    closeDetail();
    return;
  }
  const generation = ++detailGeneration;
  const name = await vaultNameOnce;
  if (generation !== detailGeneration) return;
  const url = item.path ? noteUrl(name, item.path) : "";
  detail.innerHTML = `
    <div class="detail-head">
      <h2>${escapeHtml(item.label || item.path || "(untitled)")}</h2>
      <button type="button" id="detail-close" aria-label="Close detail" title="Close">&times;</button>
    </div>
    <dl class="detail-fields">
      ${detailField("Kind", item.kind)}
      ${detailField("Status", item.status)}
      ${detailField("Priority", item.priority)}
      ${detailField("Path", item.path)}
    </dl>
    ${item.reason ? `<p class="detail-reason">${escapeHtml(item.reason)}</p>` : ""}
    ${
      item.entityId
        ? `<div class="detail-overrides">
      <p class="detail-label">Override</p>
      <div class="override-actions">${overrideButtons(item.overrideKind || "")}</div>
    </div>`
        : ""
    }
    ${
      url
        ? `<a class="note-link" id="detail-link" href="${escapeHtml(url)}">Open in Obsidian</a>`
        : `<p class="muted">No canonical note for this item.</p>`
    }`;
  state.detailKey = key;
  detail.dataset.entityId = item.entityId || "";
  detail.hidden = false;
}

function closeDetail() {
  detailGeneration += 1;
  detail.hidden = true;
  detail.innerHTML = "";
  detail.dataset.entityId = "";
  state.detailKey = null;
}

function markOverrideButtons(kind) {
  for (const button of detail.querySelectorAll("[data-override-kind]")) {
    const active = button.dataset.overrideKind === kind;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

async function saveOverride(kind) {
  const targetId = detail.dataset.entityId;
  if (!targetId) return;
  try {
    const result = await postAction("save-override", { target_id: targetId, kind });
    showWriteResult(result, false);
    markOverrideButtons(kind);
    if (current === "command-center") await refreshCommandCenter();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

async function clearOverride() {
  const targetId = detail.dataset.entityId;
  if (!targetId) return;
  try {
    const result = await postAction("clear-override", { target_id: targetId });
    showWriteResult(result, false);
    markOverrideButtons("");
    if (current === "command-center") await refreshCommandCenter();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

// F1: clearing from the Command Center's Overrides strip. The strip is not a section row, so
// the target id travels on the button rather than on the detail pane.
async function clearOverrideTarget(targetId) {
  if (!targetId) return;
  try {
    const result = await postAction("clear-override", { target_id: targetId });
    showWriteResult(result, false);
    if (current === "command-center") await refreshCommandCenter();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

function bareName(value) {
  return String(value || "").replace(/\[\[|\]\]/g, "").trim();
}

function proposalCard(proposal) {
  const fields = proposal.fields || {};
  const owners = (fields.owners || []).map(bareName).join(", ");
  const confidence = typeof proposal.confidence === "number" ? proposal.confidence : 0;
  const low = confidence < 0.5;
  const checked = proposal.status === "pending" && !low ? "checked" : "";
  const provenance = (proposal.provenance || []).map(escapeHtml).join(" · ");
  const field = (key, label, value) =>
    `<label class="field"><span>${escapeHtml(label)}</span>
      <input data-field="${key}" value="${escapeHtml(value || "")}" /></label>`;
  return `<div class="proposal row${low ? " low" : ""}" data-id="${escapeHtml(proposal.id)}" data-action="${escapeHtml(
    proposal.action
  )}">
    <label class="pick"><input type="checkbox" class="pick-box" ${checked} /></label>
    <div class="proposal-body">
      <div class="proposal-head">
        <span class="tag">${escapeHtml(proposal.action)}</span>
        <span class="conf">${escapeHtml(confidence.toFixed(2))}</span>
        ${low ? '<span class="low-flag">low confidence</span>' : ""}
        <span class="path">${escapeHtml(proposal.source_path)}</span>
      </div>
      <div class="proposal-fields">
        ${field("title", "Title", fields.title)}
        ${field("owners", "Owner", owners)}
        ${field("project", "Project", bareName(fields.project))}
        ${field("priority", "Priority", fields.priority)}
        ${field("due", "Due", fields.due)}
      </div>
      <div class="provenance">${provenance}</div>
      <button type="button" class="dismiss" data-dismiss="${escapeHtml(proposal.id)}">Dismiss</button>
    </div>
  </div>`;
}

function collectSelection() {
  const ids = [];
  const actions = [];
  const overrides = {};
  for (const node of document.querySelectorAll(".proposal")) {
    const box = node.querySelector(".pick-box");
    if (!box || !box.checked) continue;
    const id = node.dataset.id;
    ids.push(id);
    actions.push(node.dataset.action);
    const fields = {};
    for (const input of node.querySelectorAll("input[data-field]")) {
      const key = input.dataset.field;
      const value = input.value.trim();
      if (value) fields[key] = value;
    }
    overrides[id] = fields;
  }
  return { ids, actions, overrides };
}

async function applyTriage() {
  const selected = collectSelection();
  if (!selected.ids.length) {
    showWriteResult({ error: "Select at least one proposal." }, true);
    return;
  }
  const reason = window.prompt("Reason for this triage batch?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  const needsConfirm = selected.actions.some((action) => action === "merge" || action === "drop");
  if (needsConfirm && !window.confirm("This batch includes merge/drop proposals. Apply?")) return;
  try {
    const result = await postAction("ingest-apply", {
      reason: reason.trim(),
      ids: selected.ids,
      overrides: selected.overrides,
      confirmed: needsConfirm,
    });
    showWriteResult(result, false);
    await show("triage");
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

async function dismissProposal(id) {
  const reason = window.prompt("Reason for dismissing this proposal?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  try {
    const result = await postAction("ingest-dismiss", { id, reason: reason.trim() });
    showWriteResult(result, false);
    await show("triage");
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

function duplicateCard(proposal) {
  const fields = proposal.fields || {};
  const confidence = typeof proposal.confidence === "number" ? proposal.confidence : 0;
  const rejected = proposal.status === "dismissed";
  const checked = proposal.status === "pending" ? "checked" : "";
  const evidence = (proposal.provenance || []).map(escapeHtml).join(" · ");
  return `<div class="proposal row${rejected ? " low" : ""}" data-id="${escapeHtml(proposal.id)}" data-action="merge">
    <label class="pick"><input type="checkbox" class="pick-box" ${checked} /></label>
    <div class="proposal-body">
      <div class="proposal-head">
        <span class="tag">${escapeHtml(proposal.status)}</span>
        <span class="conf">${escapeHtml(confidence.toFixed(2))}</span>
        <span class="path">${escapeHtml(proposal.target_path || "")}</span>
      </div>
      <div class="proposal-fields">
        <div><strong>Keep</strong> ${escapeHtml(fields.canonical_title || proposal.target_path || "")}</div>
        <div><strong>Merge / redirect</strong> ${escapeHtml(
          fields.duplicate_title || proposal.source_path || ""
        )}</div>
      </div>
      <div class="provenance">${evidence}</div>
      <label class="field"><span>Keep</span>
        <select data-canonical>
          <option value="${escapeHtml(proposal.target_path || "")}">${escapeHtml(
            fields.canonical_title || proposal.target_path || ""
          )}</option>
          <option value="${escapeHtml(proposal.source_path || "")}">${escapeHtml(
            fields.duplicate_title || proposal.source_path || ""
          )}</option>
        </select>
      </label>
      <label class="field"><span>Resolution</span>
        <select data-resolution>
          <option value="merge">merge</option>
          <option value="redirect">redirect</option>
        </select>
      </label>
      <button type="button" class="dismiss" data-dismiss-duplicate="${escapeHtml(
        proposal.id
      )}">Reject / keep both</button>
    </div>
  </div>`;
}

async function dismissDuplicate(id) {
  const reason = window.prompt("Reason for keeping both notes?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  try {
    const result = await postAction("duplicates-dismiss", { id, reason: reason.trim() });
    showWriteResult(result, false);
    await renderQueue();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

const queueTabs = [
  { id: "triage", label: "Triage" },
  { id: "duplicates", label: "Duplicates" },
  { id: "clarification", label: "Clarification" },
  { id: "krisp", label: "Krisp" },
  { id: "identity", label: "Identity" },
];

function queueBar() {
  return `<div class="tabs">${queueTabs
    .map(
      (tab) =>
        `<button type="button" class="tab${state.queueTab === tab.id ? " active" : ""}" data-queue-tab="${tab.id}">${escapeHtml(
          tab.label
        )}</button>`
    )
    .join("")}</div>`;
}

async function renderQueue() {
  const bar = queueBar();
  if (state.queueTab === "duplicates") {
    await renderDuplicatesTab(bar);
    return;
  }
  if (state.queueTab === "clarification") {
    await renderClarificationTab(bar);
    return;
  }
  if (state.queueTab === "krisp") {
    await renderKrispTab(bar);
    return;
  }
  if (state.queueTab === "identity") {
    await renderIdentityTab(bar);
    return;
  }
  await renderTriageTab(bar);
}

async function renderIdentityTab(bar) {
  const data = await postAction("identity-scan", {});
  equivalent.textContent = data.equivalent_cli;
  state.identity = data.proposals || [];
  const rows = state.identity.map(identityCard).join("");
  view.innerHTML = heading("Review", "Person identity") + bar + (rows || empty("No duplicate people."));
  for (const button of document.querySelectorAll("[data-merge-identity]")) {
    button.addEventListener("click", () => mergeIdentity(button.dataset.mergeIdentity));
  }
  for (const button of document.querySelectorAll("[data-dismiss-identity]")) {
    button.addEventListener("click", () => dismissIdentity(button.dataset.dismissIdentity));
  }
}

function identityCard(proposal) {
  const reasons = (proposal.provenance || []).map(escapeHtml).join(" · ");
  return `<div class="proposal row" data-id="${escapeHtml(proposal.id)}">
    <div class="proposal-body">
      <div class="proposal-head">
        <span class="tag">${escapeHtml(proposal.status)}</span>
        <span class="path">${escapeHtml(proposal.source_path)} &rarr; ${escapeHtml(proposal.target_path || "")}</span>
      </div>
      <div class="proposal-fields">
        <div><strong>Why</strong> ${escapeHtml(reasons)}</div>
      </div>
      <button type="button" class="apply" data-merge-identity="${escapeHtml(proposal.id)}">Merge</button>
      <button type="button" class="dismiss" data-dismiss-identity="${escapeHtml(proposal.id)}">Dismiss</button>
    </div>
  </div>`;
}

async function mergeIdentity(id) {
  const reason = window.prompt("Reason for merging these person records?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  if (!window.confirm("This merges person notes, rewrites references, and cannot be undone. Apply?")) return;
  try {
    const result = await postAction("identity-apply", { id, reason: reason.trim(), confirmed: true });
    showWriteResult(result, false);
    await renderQueue();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

async function dismissIdentity(id) {
  const reason = window.prompt("Reason for dismissing this pair?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  try {
    const result = await postAction("identity-dismiss", { id, reason: reason.trim() });
    showWriteResult(result, false);
    await renderQueue();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

async function renderTriageTab(bar) {
  const data = await postAction("ingest-scan", {});
  equivalent.textContent = data.equivalent_cli;
  state.triage = data.proposals || [];
  const rows = state.triage.map(proposalCard).join("");
  view.innerHTML =
    heading("Triage queue", "") +
    bar +
    `<div class="triage-actions"><button type="button" id="apply-triage">Apply selected</button></div>` +
    (rows || empty("Nothing to triage."));
  const apply = document.getElementById("apply-triage");
  apply.addEventListener("click", applyTriage);
}

async function renderDuplicatesTab(bar) {
  const data = await postAction("duplicates-scan", {});
  equivalent.textContent = data.equivalent_cli;
  state.duplicates = data.proposals || [];
  const rows = state.duplicates.map(duplicateCard).join("");
  view.innerHTML =
    heading("Review", "Duplicate pairs") +
    bar +
    `<div class="triage-actions"><button type="button" id="apply-duplicates">Apply selected</button></div>` +
    (rows || empty("No duplicate pairs."));
  document.getElementById("apply-duplicates").addEventListener("click", applyDuplicates);
}

function collectDuplicateSelection() {
  const ids = [];
  const overrides = {};
  for (const node of document.querySelectorAll(".proposal[data-id]")) {
    const box = node.querySelector(".pick-box");
    if (!box || !box.checked) continue;
    const id = node.dataset.id;
    ids.push(id);
    const select = node.querySelector("select[data-resolution]");
    overrides[id] = { resolution: select ? select.value : "merge" };
    const canonical = node.querySelector("select[data-canonical]");
    if (canonical && canonical.value) overrides[id].canonical = canonical.value;
  }
  return { ids, overrides };
}

async function applyDuplicates() {
  const selected = collectDuplicateSelection();
  if (!selected.ids.length) {
    showWriteResult({ error: "Select at least one pair." }, true);
    return;
  }
  const reason = window.prompt("Reason for this duplicate-resolution batch?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  if (!window.confirm("This batch merges/redirects notes and cannot be undone. Apply?")) return;
  try {
    const result = await postAction("duplicates-apply", {
      reason: reason.trim(),
      ids: selected.ids,
      overrides: selected.overrides,
      confirmed: true,
    });
    showWriteResult(result, false);
    await renderQueue();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

function clarifyCard(proposal) {
  const fields = proposal.fields || {};
  const reasons = (proposal.provenance || []).map(escapeHtml).join(" · ");
  const checked = proposal.status === "pending" ? "checked" : "";
  return `<div class="proposal row" data-id="${escapeHtml(proposal.id)}">
    <label class="pick"><input type="checkbox" class="pick-box" ${checked} /></label>
    <div class="proposal-body">
      <div class="proposal-head">
        <span class="tag">${escapeHtml(proposal.status)}</span>
        <span class="path">${escapeHtml(proposal.source_path)}</span>
      </div>
      <div class="proposal-fields">
        <div><strong>Why</strong> ${escapeHtml(fields.reasons || reasons)}</div>
        ${fields.matches ? `<div class="meta"><strong>Nearby</strong> ${escapeHtml(fields.matches)}</div>` : ""}
      </div>
      <label class="field"><span>Resolution</span>
        <select data-resolution>
          <option value="keep">keep</option>
          <option value="archive">archive</option>
          <option value="reclassify">waiting-on</option>
          <option value="merge">merge</option>
        </select>
      </label>
      <div class="proposal-fields">
        <input data-field="canonical" placeholder="merge target path" />
        <input data-field="project" placeholder="project" />
        <input data-field="owner" placeholder="owner" />
        <input data-field="dependency" placeholder="waiting on" />
        <input data-field="next_review" placeholder="next review YYYY-MM-DD" />
      </div>
      <button type="button" class="dismiss" data-dismiss-clarification="${escapeHtml(
        proposal.id
      )}">Dismiss</button>
    </div>
  </div>`;
}

function collectClarifySelection() {
  const ids = [];
  const overrides = {};
  for (const node of document.querySelectorAll(".proposal[data-id]")) {
    const box = node.querySelector(".pick-box");
    if (!box || !box.checked) continue;
    const id = node.dataset.id;
    ids.push(id);
    const select = node.querySelector("select[data-resolution]");
    const entry = { resolution: select ? select.value : "keep" };
    for (const input of node.querySelectorAll("input[data-field]")) {
      const value = input.value.trim();
      if (value) entry[input.dataset.field] = value;
    }
    overrides[id] = entry;
  }
  return { ids, overrides };
}

async function applyClarification() {
  const selected = collectClarifySelection();
  if (!selected.ids.length) {
    showWriteResult({ error: "Select at least one item." }, true);
    return;
  }
  const reason = window.prompt("Reason for this clarification batch?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  const normal = selected.ids.every((id) => selected.overrides[id].resolution === "keep");
  if (!normal && !window.confirm("This batch changes ownership or merges/archives notes and cannot be undone. Apply?"))
    return;
  try {
    const result = await postAction("clarification-apply", {
      reason: reason.trim(),
      ids: selected.ids,
      overrides: selected.overrides,
      confirmed: !normal,
    });
    showWriteResult(result, false);
    await renderQueue();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

async function dismissClarification(id) {
  const reason = window.prompt("Reason for dismissing this item?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  try {
    const result = await postAction("clarification-dismiss", { id, reason: reason.trim() });
    showWriteResult(result, false);
    await renderQueue();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

async function renderClarificationTab(bar) {
  const data = await postAction("clarification-scan", {});
  equivalent.textContent = data.equivalent_cli;
  state.clarification = data.proposals || [];
  const rows = state.clarification.map(clarifyCard).join("");
  view.innerHTML =
    heading("Review", "Clarification queue") +
    bar +
    `<div class="triage-actions"><button type="button" id="apply-clarification">Apply selected</button></div>` +
    (rows || empty("Nothing needs clarification."));
  document.getElementById("apply-clarification").addEventListener("click", applyClarification);
}

function krispCard(proposal) {
  const fields = proposal.fields || {};
  const confidence = typeof proposal.confidence === "number" ? proposal.confidence : 0;
  const checked = proposal.status === "pending" ? "checked" : "";
  const provenance = (proposal.provenance || []).map(escapeHtml).join(" · ");
  const attendees = (fields.attendees || []).map(bareName).join(", ");
  const projects = (fields.projects || []).map(bareName).join(", ");
  const field = (key, label, value) =>
    `<label class="field"><span>${escapeHtml(label)}</span>
      <input data-field="${key}" value="${escapeHtml(value || "")}" /></label>`;
  return `<div class="proposal row" data-id="${escapeHtml(proposal.id)}" data-action="meeting">
    <label class="pick"><input type="checkbox" class="pick-box" ${checked} /></label>
    <div class="proposal-body">
      <div class="proposal-head">
        <span class="tag">meeting</span>
        <span class="conf">${escapeHtml(confidence.toFixed(2))}</span>
        <span class="path">${escapeHtml(proposal.source_path)}</span>
      </div>
      <div class="proposal-fields">
        ${field("title", "Title", fields.title)}
        ${field("date", "Date", fields.date)}
        ${field("attendees", "Attendees", attendees)}
        ${field("projects", "Projects", projects)}
      </div>
      <div class="provenance">${provenance}</div>
      <button type="button" class="dismiss" data-dismiss-krisp="${escapeHtml(proposal.id)}">Dismiss</button>
    </div>
  </div>`;
}

function collectKrispSelection() {
  const ids = [];
  const overrides = {};
  for (const node of document.querySelectorAll(".proposal[data-action='meeting']")) {
    const box = node.querySelector(".pick-box");
    if (!box || !box.checked) continue;
    const id = node.dataset.id;
    ids.push(id);
    const fields = {};
    for (const input of node.querySelectorAll("input[data-field]")) {
      const value = input.value.trim();
      if (value) fields[input.dataset.field] = value;
    }
    overrides[id] = fields;
  }
  return { ids, overrides };
}

function showKrispSummary(result) {
  const summary = result.summary || {};
  writeResult.innerHTML = `<div class="write-ok">
    <p>Pulled ${(summary.pulled || []).length}, skipped ${(summary.skipped || []).length}, failed ${
      (summary.failed || []).length
    }</p>
    ${result.equivalent_cli ? `<code>${escapeHtml(result.equivalent_cli)}</code>` : ""}
  </div>`;
}

async function pullKrisp() {
  const button = document.getElementById("krisp-pull");
  if (button) button.disabled = true;
  try {
    const result = await postAction("krisp-pull", {});
    showKrispSummary(result);
    await renderKrispTab(queueBar());
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
    if (button) button.disabled = false;
  }
}

async function applyKrisp() {
  const selected = collectKrispSelection();
  if (!selected.ids.length) {
    showWriteResult({ error: "Select at least one meeting." }, true);
    return;
  }
  const reason = window.prompt("Reason for promoting these meetings?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  try {
    const result = await postAction("ingest-apply", {
      reason: reason.trim(),
      ids: selected.ids,
      overrides: selected.overrides,
    });
    showWriteResult(result, false);
    await renderKrispTab(queueBar());
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

async function dismissKrisp(id) {
  const reason = window.prompt("Reason for dismissing this meeting?", "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  try {
    const result = await postAction("ingest-dismiss", { id, reason: reason.trim() });
    showWriteResult(result, false);
    await renderKrispTab(queueBar());
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

async function renderKrispTab(bar) {
  const status = await postAction("krisp-status", {});
  const scan = await postAction("ingest-scan", {});
  equivalent.textContent = scan.equivalent_cli;
  state.krisp = (scan.proposals || []).filter((proposal) => proposal.action === "meeting");
  const rows = state.krisp.map(krispCard).join("");
  const sync = status.sync || {};
  const failed = (sync.failed || []).length;
  const last = sync.last_success_at ? `last pull ${sync.last_success_at}` : "never pulled";
  view.innerHTML =
    heading("Review", "Krisp meetings") +
    bar +
    `<div class="krisp-bar">
      <span class="muted">${escapeHtml(last)} · window ${escapeHtml(String(status.since_days))} days${
        failed ? ` · ${failed} failed` : ""
      }</span>
      <button type="button" id="krisp-pull">Pull transcripts</button>
    </div>` +
    `<div class="triage-actions"><button type="button" id="apply-krisp">Apply selected</button></div>` +
    (rows || empty("No meeting candidates."));
  document.getElementById("krisp-pull").addEventListener("click", pullKrisp);
  document.getElementById("apply-krisp").addEventListener("click", applyKrisp);
}

async function completeAction(path, title) {
  const reason = window.prompt(`Reason for completing "${title}"?`, "");
  if (reason === null) return;
  if (!reason.trim()) {
    showWriteResult({ error: "A human-readable reason is required." }, true);
    return;
  }
  try {
    const result = await postAction("complete-action", { path, reason: reason.trim() });
    showWriteResult(result, false);
    await show(current);
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
  }
}

function empty(message) {
  return `<div class="empty">${escapeHtml(message || "Nothing here.")}</div>`;
}

function row(state, tag, title, reason, meta, target, extra) {
  const attrs = target
    ? ` data-target="${escapeHtml(target.kind)}" data-name="${escapeHtml(target.name)}" tabindex="0" role="button"`
    : "";
  return `<div class="row ${escapeHtml(state)}"${attrs}>
    <div class="who">${escapeHtml(title)}</div>
    <div class="what"><span class="tag">${escapeHtml(tag)}</span>${escapeHtml(reason)}</div>
    <div class="meta">${escapeHtml(meta || "")}${extra || ""}</div>
  </div>`;
}

function heading(title, subtitle) {
  return `<h1>${escapeHtml(title)}</h1><p class="subtitle">${escapeHtml(subtitle)}</p>`;
}

function attentionRows(items) {
  if (!items || !items.length) return empty("No attention items.");
  return items
    .map((item) => {
      const extra =
        item.entity_type === "action" && item.path
          ? ` <button type="button" class="complete" data-complete="${escapeHtml(item.path)}" data-title="${escapeHtml(
              item.title
            )}">Complete</button>`
          : "";
      return row(item.kind, item.kind, item.title, item.reason, item.path, null, extra);
    })
    .join("");
}

async function healthBanner() {
  try {
    const data = await api("/api/health");
    if (!data.issues || !data.issues.length) return "";
    const items = data.issues
      .slice(0, 20)
      .map((issue) =>
        row(
          issue.severity === "error" ? "blocked" : "review_due",
          issue.severity,
          issue.rule || "issue",
          issue.message,
          issue.path
        )
      )
      .join("");
    return `<div class="issues"><p class="subtitle">Data health: ${data.errors} error(s), ${data.warnings} warning(s)</p>${items}</div>`;
  } catch (error) {
    return "";
  }
}

function projectCard(review) {
  const project = review.project || {};
  const lines = [heading(project.title || "(project)", project.status || "")];
  const blockers = review.blockers || [];
  lines.push(`<p class="subtitle">blockers: ${blockers.length}</p>`);
  lines.push(attentionRows(review.attention));
  return lines.join("");
}

const commandCenterTitles = {
  needs_attention: "Needs Attention",
  my_priorities: "My Priorities",
  since_last_check: "Since Last Check",
};

const commandCenterUnavailable = {
  no_checkpoint: "No checkpoint yet — nothing to compare against.",
  source_unavailable: "Source unavailable.",
};

function commandCenterItem(item, refusedEntityIds) {
  const label = item.label || item.title || item.entity_id || item.path || "(untitled)";
  const kind = item.entity_type || item.kind || "";
  const priority = item.priority === undefined || item.priority === null ? "" : `priority ${item.priority}`;
  const meta = [priority, item.path || ""].filter(Boolean).join(" · ");
  // Ticket 18: a per-row indicator names the request, or says it was refused; the banner
  // below the section carries the safety evidence that refused it.
  const overrideKind = item.override_kind || "";
  let overrideChip = "";
  if (overrideKind) {
    const refused = refusedEntityIds && refusedEntityIds.has(item.entity_id);
    const text = refused
      ? `${overrideActionLabels[overrideKind] || overrideKind} refused`
      : overrideIndicators[overrideKind] || overrideKind;
    overrideChip = `<span class="cc-override${refused ? " refused" : ""}">${escapeHtml(text)}</span>`;
  }
  // Ticket 11: every Command Center row is selectable and carries its fields so the detail
  // pane can render without another request (state is front-end only). Ticket 18 adds the
  // entity id and requested override so the pane can save and clear one.
  const attrs = [
    "data-cc-item",
    'role="button"',
    'tabindex="0"',
    `data-entity-id="${escapeHtml(item.entity_id || "")}"`,
    `data-override-kind="${escapeHtml(overrideKind)}"`,
    `data-path="${escapeHtml(item.path || "")}"`,
    `data-label="${escapeHtml(label)}"`,
    `data-kind="${escapeHtml(kind)}"`,
    `data-status="${escapeHtml(item.status || "")}"`,
    `data-priority="${escapeHtml(item.priority === undefined || item.priority === null ? "" : String(item.priority))}"`,
    `data-reason="${escapeHtml(item.reason || "")}"`,
  ].join(" ");
  return `<div class="row cc-row ${escapeHtml(item.status || "")}" ${attrs}>
    <div class="who">${escapeHtml(label)}</div>
    <div class="what">${kind ? `<span class="tag">${escapeHtml(kind)}</span>` : ""}${escapeHtml(
      item.reason || ""
    )}${overrideChip}</div>
    <div class="meta">${escapeHtml(meta)}</div>
  </div>`;
}

// Ticket 18: a refused override still carries its requested kind on the row, but the ranker
// kept it at its safety band. The banner is the one place that says so plainly.
function commandCenterConflicts(conflicts) {
  const rows = conflicts
    .map((conflict) => {
      const action = overrideActionLabels[conflict.kind] || conflict.kind || "Override";
      const evidence = conflict.evidence || "a safety floor";
      const target = conflict.entity_id ? ` <span class="muted">${escapeHtml(conflict.entity_id)}</span>` : "";
      return `<li>${escapeHtml(`${action} refused: ${evidence}`)}${target}</li>`;
    })
    .join("");
  return `<div class="cc-conflicts" role="alert">
    <strong>Override refused.</strong> The work record stays at its safety band.
    <ul>${rows}</ul>
  </div>`;
}

function commandCenterBlock(section) {
  const title = commandCenterTitles[section.section_id] || section.section_id || "Section";
  const sectionState = section.state || "";
  const items = section.items || [];
  const conflicts = section.conflicts || [];
  const refusedEntityIds = new Set(conflicts.map((conflict) => conflict.entity_id));
  const count =
    section.total_count === undefined || section.total_count === null ? items.length : section.total_count;
  let body;
  if (sectionState === "unavailable") {
    body = `<div class="empty">${escapeHtml(
      commandCenterUnavailable[section.error_state] || "Unavailable right now."
    )}</div>`;
  } else if (sectionState === "empty") {
    body = empty("Nothing here.");
  } else {
    body = items.map((item) => commandCenterItem(item, refusedEntityIds)).join("") || empty("Nothing here.");
  }
  return `<section class="cc-section" data-section-id="${escapeHtml(section.section_id || "")}">
    <div class="cc-head">
      <h2>${escapeHtml(title)}</h2>
      <span class="cc-count">${escapeHtml(String(count))}</span>
      <span class="cc-state ${escapeHtml(sectionState)}">${escapeHtml(sectionState || "unknown")}</span>
    </div>
    ${conflicts.length ? commandCenterConflicts(conflicts) : ""}
    ${body}
  </section>`;
}

function renderCommandCenter(sections, overrides) {
  const blocks = (sections || []).map(commandCenterBlock).join("");
  view.innerHTML =
    heading("Command Center", "Needs attention, your priorities, and what changed since your last check") +
    commandCenterOverrides(overrides) +
    (blocks || empty("No sections."));
}

// F1: the always-reachable Overrides strip. A not_relevant override drops its row from every
// section, so this list is the one place it can still be seen and cleared. It renders only
// when something is active, and each row carries the target id its Clear button posts.
function commandCenterOverrides(overrides) {
  if (!overrides || !overrides.length) return "";
  const rows = overrides
    .map((override) => {
      const targetId = override.target_id || "";
      const label = override.label || targetId || "(untitled)";
      const kind = override.kind || "";
      const name = overrideActionLabels[kind] || kind;
      const reason = override.reason ? ` <span class="muted">${escapeHtml(override.reason)}</span>` : "";
      return `<div class="cc-override-row">
        <div class="who">${escapeHtml(label)}</div>
        <div class="what"><span class="cc-override">${escapeHtml(name)}</span>${reason}</div>
        <button type="button" data-clear-override-target="${escapeHtml(targetId)}"
          aria-label="Clear ${escapeHtml(name)} for ${escapeHtml(label)}">Clear</button>
      </div>`;
    })
    .join("");
  return `<section class="cc-overrides" aria-label="Overrides">
    <div class="cc-head">
      <h2>Overrides</h2>
      <span class="cc-count">${escapeHtml(String(overrides.length))}</span>
    </div>
    ${rows}
  </section>`;
}

// CC-03: the layout toolbar. The route returns the profile and already renders the sections
// in its order with hidden ones dropped, so the toolbar only edits the profile and re-reads
// the route; it never re-sorts the DOM itself.

let layoutInFlight = false;
let meOptionsLoaded = false;
let peoplePromise = null;

function peopleOnce() {
  // The "Me" options are stable person ids; /api/team is the one read that carries them,
  // and it is fetched at most once per page load. A person without a person_id cannot be
  // an owner, so they are left out of the picker.
  if (!peoplePromise) {
    peoplePromise = api("/api/team")
      .then((data) => (data.workloads || []).map((workload) => workload.person || {}))
      .catch(() => []);
  }
  return peoplePromise;
}

function layoutRow(sectionId, index, total) {
  const title = commandCenterTitles[sectionId] || sectionId;
  const visible = state.profile.visibility[sectionId] !== false;
  const up = index === 0 ? " disabled" : "";
  const down = index === total - 1 ? " disabled" : "";
  return `<div class="layout-row">
    <span class="layout-title">${escapeHtml(title)}</span>
    <button type="button" data-layout-visibility="${escapeHtml(sectionId)}" aria-pressed="${visible}"
      title="${visible ? "Hide" : "Show"} ${escapeHtml(title)}">${visible ? "Hide" : "Show"}</button>
    <button type="button" data-layout-move="up" data-layout-id="${escapeHtml(sectionId)}"
      aria-label="Move ${escapeHtml(title)} up"${up}>&uarr;</button>
    <button type="button" data-layout-move="down" data-layout-id="${escapeHtml(sectionId)}"
      aria-label="Move ${escapeHtml(title)} down"${down}>&darr;</button>
  </div>`;
}

function renderLayoutBar() {
  if (!state.profile) {
    layoutBar.hidden = true;
    return;
  }
  const order = state.profile.section_order || [];
  layoutSections.innerHTML = order.map((sectionId, index) => layoutRow(sectionId, index, order.length)).join("");
  meSelect.value = state.profile.owner_id || "";
  layoutBar.hidden = false;
}

async function fillMeOptions() {
  const people = await peopleOnce();
  const current = (state.profile && state.profile.owner_id) || "";
  const seen = new Set([""]);
  const options = ['<option value="">(nobody)</option>'];
  for (const person of people) {
    const id = person.person_id;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    options.push(`<option value="${escapeHtml(id)}">${escapeHtml(person.title || id)}</option>`);
  }
  // A stored owner who is no longer on the team stays selectable, so the picker never
  // silently reports a different "Me" than the profile holds.
  if (current && !seen.has(current)) {
    options.push(`<option value="${escapeHtml(current)}">${escapeHtml(current)}</option>`);
  }
  meSelect.innerHTML = options.join("");
  meSelect.value = current;
}

async function refreshCommandCenter() {
  const data = await api("/api/command-center");
  equivalent.textContent = data.equivalent_cli;
  state.profile = data.profile || null;
  renderLayoutBar();
  renderCommandCenter(data.sections, data.overrides);
  if (!meOptionsLoaded) {
    meOptionsLoaded = true;
    fillMeOptions();
  }
}

function layoutPayload(profile, changes) {
  return {
    section_order: profile.section_order,
    visibility: profile.visibility,
    owner_id: profile.owner_id,
    ...changes,
  };
}

async function saveLayout(payload) {
  // One save in flight at a time: a second click would build its payload from the same
  // cached profile and silently drop the first change.
  if (layoutInFlight) return;
  layoutInFlight = true;
  try {
    const result = await postAction("save-layout-profile", payload);
    state.profile = result.profile;
    showWriteResult(result, false);
    // The user may have navigated away while the save was in flight; only the Command
    // Center should have its sections re-read.
    if (current === "command-center") await refreshCommandCenter();
  } catch (error) {
    showWriteResult({ error: String(error.message || error) }, true);
    // The toolbar was left showing the attempted change; snap it back to the stored profile.
    renderLayoutBar();
  } finally {
    layoutInFlight = false;
  }
}

function toggleSection(sectionId) {
  if (!state.profile) return;
  const visibility = { ...state.profile.visibility, [sectionId]: !state.profile.visibility[sectionId] };
  saveLayout(layoutPayload(state.profile, { visibility }));
}

function moveSection(sectionId, direction) {
  if (!state.profile) return;
  const order = [...state.profile.section_order];
  const index = order.indexOf(sectionId);
  const target = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || target < 0 || target >= order.length) return;
  [order[index], order[target]] = [order[target], order[index]];
  saveLayout(layoutPayload(state.profile, { section_order: order }));
}

function setOwner(ownerId) {
  if (!state.profile) return;
  saveLayout(layoutPayload(state.profile, { owner_id: ownerId || null }));
}

function resetLayout() {
  saveLayout({ reset: true });
}

const sections = {
  "command-center": async () => {
    await refreshCommandCenter();
  },

  async today() {
    const data = await api("/api/today");
    equivalent.textContent = data.equivalent_cli;
    view.innerHTML =
      heading("Today", `${data.attention.length} attention item(s)`) +
      (await healthBanner()) +
      attentionRows(data.attention);
  },

  async triage() {
    await renderQueue();
  },

  async review() {
    const data = await api("/api/review");
    equivalent.textContent = data.equivalent_cli;
    const body = data.projects.map((review) => projectCard(review)).join("");
    view.innerHTML = heading("Review", `${data.projects.length} active project(s)`) + (body || empty("No projects."));
  },

  async projects() {
    const data = await api("/api/projects");
    equivalent.textContent = data.equivalent_cli;
    const body = data.projects
      .map((item) =>
        row(
          item.status,
          item.status || "-",
          item.name,
          item.registered_repo || "no registered repo",
          item.project_id || "",
          { kind: "project", name: item.name }
        )
      )
      .join("");
    view.innerHTML = heading("Projects", `${data.projects.length} registered`) + (body || empty("No projects."));
  },

  async team() {
    const data = await api("/api/team");
    equivalent.textContent = data.equivalent_cli;
    const body = data.workloads
      .map((workload) =>
        row(
          "",
          (workload.attention || []).length + " attention",
          workload.person.title,
          `${(workload.actions || []).length} action(s), ${(workload.tickets || []).length} ticket(s)`,
          ((workload.projects || []).length || 0) + " project(s)",
          { kind: "person", name: workload.person.title }
        )
      )
      .join("");
    view.innerHTML = heading("Team", `${data.workloads.length} active person(s)`) + (body || empty("No people."));
  },

  async tickets() {
    const data = await api("/api/tickets");
    equivalent.textContent = data.equivalent_cli;
    const body = data.tickets
      .map((ticket) => {
        const reasons = (ticket.attention || []).map((item) => item.reason).join("; ");
        return row(ticket.status, ticket.status || "-", ticket.title, reasons || "no attention", ticket.path);
      })
      .join("");
    view.innerHTML = heading("Tickets", `${data.tickets.length} ticket(s)`) + (body || empty("No tickets."));
  },

  async search() {
    view.innerHTML = `${heading("Search", "Evidence with provenance")}
      <form class="searchbar" id="search-form">
        <input type="search" id="search-q" placeholder="Search the project evidence" aria-label="Search query" />
        <button type="submit">Search</button>
      </form>
      <div id="search-results">${empty("Enter a query.")}</div>`;
    equivalent.textContent = 'worksync search "<query>"';
    const form = document.getElementById("search-form");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = document.getElementById("search-q").value.trim();
      if (!query) return;
      const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
      equivalent.textContent = data.equivalent_cli;
      const results = data.result.results || [];
      const body = results
        .map((item) =>
          row(
            "",
            item.association.tier || "?",
            item.path,
            item.snippet || "",
            item.stale ? "stale" : (item.association.method || "")
          )
        )
        .join("");
      document.getElementById("search-results").innerHTML = body || empty("No matches.");
    });
  },

  async settings() {
    const data = await api("/api/settings");
    equivalent.textContent = data.equivalent_cli;
    vaultName.textContent = data.vault_name || "";
    const fields = [
      ["Vault", data.vault_path],
      ["Runtime root", data.runtime_root],
      ["Index", data.index_present ? data.index_path : `${data.index_path} (not built)`],
      ["Projects", String(data.project_count)],
      ["Stale context", data.stale_context_projects.length ? data.stale_context_projects.join(", ") : "none"],
      ["Errors", String(data.errors)],
      ["Warnings", String(data.warnings)],
      ["Port", String(data.ui_port)],
      ["Reviewer", data.reviewer || "(unset)"],
    ];
    view.innerHTML =
      heading("Settings", "Read-only configuration") +
      `<dl class="settings">${fields
        .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`)
        .join("")}</dl>` +
      `<form class="reviewer" id="reviewer-form">
        <label>Current reviewer
          <input type="text" id="reviewer-name" value="${escapeHtml(data.reviewer || "")}" placeholder="Your name" />
        </label>
        <button type="submit">Set reviewer</button>
      </form>` +
      (await healthBanner());
    const form = document.getElementById("reviewer-form");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = document.getElementById("reviewer-name").value.trim();
      if (!name) return;
      try {
        const result = await postAction("set-reviewer", { reviewer: name });
        showWriteResult(result, false);
        await show("settings");
      } catch (error) {
        showWriteResult({ error: String(error.message || error) }, true);
      }
    });
  },
};

function activeSection() {
  const button = document.querySelector(".rail button[data-section].active");
  return button ? button.dataset.section : DEFAULT_SECTION;
}

let current = activeSection();

async function show(name) {
  current = name;
  // A section change retires the selection context, so the on-demand pane closes with it.
  closeDetail();
  // The layout toolbar belongs to the Command Center; renderLayoutBar re-shows it there.
  layoutBar.hidden = name !== "command-center";
  for (const button of document.querySelectorAll(".rail button[data-section]")) {
    button.classList.toggle("active", button.dataset.section === name);
  }
  try {
    await sections[name]();
  } catch (error) {
    view.innerHTML = heading("Error", "") + empty(String(error.message || error));
  }
}

function navigate(name) {
  if (name === current) return;
  history.pushState({ section: name }, "");
  show(name);
}

document.getElementById("rail").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-section]");
  if (button) navigate(button.dataset.section);
});

// CC-03: the layout toolbar edits the cached profile and saves it through the action; a
// successful save re-reads the route, so the sections below reflect the new layout.
layoutBar.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-layout-visibility]");
  if (toggle) {
    toggleSection(toggle.dataset.layoutVisibility);
    return;
  }
  const move = event.target.closest("[data-layout-move]");
  if (move) {
    moveSection(move.dataset.layoutId, move.dataset.layoutMove);
    return;
  }
  if (event.target.closest("#layout-reset")) resetLayout();
});

meSelect.addEventListener("change", () => setOwner(meSelect.value));

document.getElementById("back").addEventListener("click", () => history.back());
document.getElementById("forward").addEventListener("click", () => history.forward());

captureSubmit.addEventListener("click", submitCapture);
captureInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    submitCapture();
  }
});

window.addEventListener("popstate", (event) => {
  const name = event.state && event.state.section ? event.state.section : DEFAULT_SECTION;
  show(name);
});

view.addEventListener("click", (event) => {
  const clearTarget = event.target.closest("[data-clear-override-target]");
  if (clearTarget) {
    clearOverrideTarget(clearTarget.dataset.clearOverrideTarget);
    return;
  }
  const tab = event.target.closest("[data-queue-tab]");
  if (tab) {
    state.queueTab = tab.dataset.queueTab;
    renderQueue();
    return;
  }
  const dismissDup = event.target.closest("[data-dismiss-duplicate]");
  if (dismissDup) {
    dismissDuplicate(dismissDup.dataset.dismissDuplicate);
    return;
  }
  const dismissClarify = event.target.closest("[data-dismiss-clarification]");
  if (dismissClarify) {
    dismissClarification(dismissClarify.dataset.dismissClarification);
    return;
  }
  const dismissKrispNode = event.target.closest("[data-dismiss-krisp]");
  if (dismissKrispNode) {
    dismissKrisp(dismissKrispNode.dataset.dismissKrisp);
    return;
  }
  const complete = event.target.closest("[data-complete]");
  if (complete) {
    completeAction(complete.dataset.complete, complete.dataset.title || complete.dataset.complete);
    return;
  }
  const dismiss = event.target.closest("[data-dismiss]");
  if (dismiss) {
    dismissProposal(dismiss.dataset.dismiss);
    return;
  }
  const ccItem = event.target.closest("[data-cc-item]");
  if (ccItem) {
    selectItem(ccItem);
    return;
  }
  const node = event.target.closest("[data-target]");
  if (!node) return;
  const { target: kind, name } = node.dataset;
  if (kind === "project") showProject(name);
  if (kind === "person") showPerson(name);
});

view.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const ccItem = event.target.closest("[data-cc-item]");
  if (!ccItem) return;
  event.preventDefault();
  selectItem(ccItem);
});

detail.addEventListener("click", (event) => {
  if (event.target.closest("#detail-close")) {
    closeDetail();
    return;
  }
  const overrideButton = event.target.closest("[data-override-kind]");
  if (overrideButton) {
    saveOverride(overrideButton.dataset.overrideKind);
    return;
  }
  if (event.target.closest("[data-clear-override]")) clearOverride();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !detail.hidden) closeDetail();
});

async function showProject(name) {
  const data = await api(`/api/project?name=${encodeURIComponent(name)}`);
  equivalent.textContent = data.equivalent_cli;
  view.innerHTML = data.state === "ok" ? projectCard(data.review) : heading("Not found", name) + empty("No project.");
}

async function showPerson(name) {
  const data = await api(`/api/person?name=${encodeURIComponent(name)}`);
  equivalent.textContent = data.equivalent_cli;
  if (data.state !== "ok") {
    view.innerHTML = heading("Not found", name) + empty("No person.");
    return;
  }
  const workload = data.workload;
  view.innerHTML =
    heading(workload.person.title, workload.person.role || "") + attentionRows(workload.attention);
}

history.replaceState({ section: current }, "");
show(current);
