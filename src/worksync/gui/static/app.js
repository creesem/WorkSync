"use strict";

const TOKEN = window.__GUI_TOKEN__ || "";
const TOKEN_HEADER = "X-Gui-Token";

const state = { triage: [] };

const view = document.getElementById("view");
const equivalent = document.getElementById("equivalent");
const vaultName = document.getElementById("vault-name");
const writeResult = document.getElementById("write-result");

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

const sections = {
  async today() {
    const data = await api("/api/today");
    equivalent.textContent = data.equivalent_cli;
    view.innerHTML =
      heading("Today", `${data.attention.length} attention item(s)`) +
      (await healthBanner()) +
      attentionRows(data.attention);
  },

  async triage() {
    const data = await postAction("ingest-scan", {});
    equivalent.textContent = data.equivalent_cli;
    state.triage = data.proposals || [];
    const rows = state.triage.map(proposalCard).join("");
    view.innerHTML =
      heading("Triage", `${state.triage.length} proposal(s)`) +
      `<div class="triage-actions"><button type="button" id="apply-triage">Apply selected</button></div>` +
      (rows || empty("Nothing to triage."));
    const apply = document.getElementById("apply-triage");
    apply.addEventListener("click", applyTriage);
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

let current = "today";

async function show(name) {
  current = name;
  for (const button of document.querySelectorAll(".nav button")) {
    button.classList.toggle("active", button.dataset.section === name);
  }
  try {
    await sections[name]();
  } catch (error) {
    view.innerHTML = heading("Error", "") + empty(String(error.message || error));
  }
}

document.getElementById("nav").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-section]");
  if (button) show(button.dataset.section);
});

view.addEventListener("click", (event) => {
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
  const node = event.target.closest("[data-target]");
  if (!node) return;
  const { target: kind, name } = node.dataset;
  if (kind === "project") showProject(name);
  if (kind === "person") showPerson(name);
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

show(current);
