"use strict";

const state = { accounts: [], actions: [], rules: [] };

const el = (id) => document.getElementById(id);
const accountForm = el("account-form");
const actionForm = el("action-form");
const ruleForm = el("rule-form");

// ---------- Helpers ----------

function toast(message, type = "info") {
  const box = el("toast");
  const node = document.createElement("div");
  node.className = `toast-msg ${type}`;
  node.textContent = message;
  box.appendChild(node);
  setTimeout(() => node.remove(), 4000);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.description || body.message || message;
    } catch (_) { /* ignore */ }
    throw new Error(message);
  }
  if (res.status === 204) return null;
  return res.json();
}

function formToObject(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  return data;
}

function resetForm(form, name) {
  form.reset();
  form.querySelector('[name="id"]').value = "";
  form.dataset.editing = "";
  if (name === "rule") updateRuleFormVisibility();
  if (name === "action") {
    const select = el("folder-select");
    select.style.display = "none";
    select.innerHTML = "";
  }
}

// ---------- Load & render ----------

async function loadAll() {
  state.accounts = [];
  state.actions = [];
  state.rules = [];
  const config = await api("/api/config");
  Object.assign(state, config);
  renderAccounts();
  renderActions();
  renderRules();
  refreshPreview();
}

function renderAccounts() {
  const tbody = document.querySelector("#accounts-table tbody");
  tbody.innerHTML = "";
  for (const acc of state.accounts) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(acc.name)}</td>
      <td>${acc.type}</td>
      <td>${escapeHtml(acc.server)}</td>
      <td>${acc.port}</td>
      <td>${escapeHtml(acc.user)}</td>
      <td></td>`;
    const actionsTd = tr.querySelector("td:last-child");
    actionsTd.appendChild(makeButton("Bearbeiten", () => editAccount(acc)));
    actionsTd.appendChild(makeButton("Loeschen", () => deleteAccount(acc), true));
    tbody.appendChild(tr);
  }
}

function renderActions() {
  const tbody = document.querySelector("#actions-table tbody");
  tbody.innerHTML = "";
  for (const act of state.actions) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(act.name)}</td>
      <td>${act.type}</td>
      <td>${escapeHtml(act.server)}</td>
      <td>${act.port}</td>
      <td>${escapeHtml(act.user)}</td>
      <td>${escapeHtml(act.folder)}</td>
      <td></td>`;
    const actionsTd = tr.querySelector("td:last-child");
    actionsTd.appendChild(makeButton("Bearbeiten", () => editAction(act)));
    actionsTd.appendChild(makeButton("Loeschen", () => deleteAction(act), true));
    tbody.appendChild(tr);
  }

  const select = ruleForm.querySelector('[name="action_id"]');
  const current = select.value;
  select.innerHTML = '<option value="">Ziel-Action waehlen ...</option>';
  for (const act of state.actions) {
    const opt = document.createElement("option");
    opt.value = act.id;
    opt.textContent = act.name;
    select.appendChild(opt);
  }
  select.value = current;
}

function ruleLabel(rule) {
  const action = state.actions.find((a) => a.id === rule.action_id);
  const actionName = action ? action.name : "?";
  if (rule.field === "all") {
    return `<strong>Catch-All</strong> &rarr; <code>${escapeHtml(actionName)}</code>`;
  }
  const fieldLabel = { from: "From", subject: "Subject", header: rule.header_name }[rule.field];
  const matchLabel = { contains: "enthaelt", exact: "exakt", regex: "regex" }[rule.match_type];
  return `<code>${escapeHtml(fieldLabel)}</code> ${matchLabel} <code>${escapeHtml(rule.value)}</code> &rarr; <code>${escapeHtml(actionName)}</code>`;
}

function renderRules() {
  const list = el("rules-list");
  list.innerHTML = "";
  state.rules.forEach((rule, idx) => {
    const li = document.createElement("li");
    li.className = "rule-item" + (rule.field === "all" ? " catchall" : "");
    li.draggable = true;
    li.dataset.id = rule.id;

    const handle = document.createElement("span");
    handle.className = "drag-handle";
    handle.textContent = "☰";

    const body = document.createElement("span");
    body.className = "rule-body";
    body.innerHTML = ruleLabel(rule);

    const actionsSpan = document.createElement("span");
    actionsSpan.className = "rule-actions";
    actionsSpan.appendChild(makeIconButton("↑", () => moveRule(idx, -1), idx === 0));
    actionsSpan.appendChild(makeIconButton("↓", () => moveRule(idx, 1), idx === state.rules.length - 1));
    actionsSpan.appendChild(makeButton("Bearbeiten", () => editRule(rule)));
    actionsSpan.appendChild(makeButton("Loeschen", () => deleteRule(rule), true));

    li.appendChild(handle);
    li.appendChild(body);
    li.appendChild(actionsSpan);
    list.appendChild(li);
  });
  attachDragHandlers();
}

function makeButton(label, handler, danger = false) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = label;
  btn.className = danger ? "danger" : "secondary";
  btn.style.marginLeft = "0.3rem";
  btn.addEventListener("click", handler);
  return btn;
}

function makeIconButton(label, handler, disabled = false) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = label;
  btn.className = "icon-btn";
  btn.disabled = disabled;
  btn.addEventListener("click", handler);
  return btn;
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ---------- Accounts CRUD ----------

accountForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formToObject(accountForm);
  const id = data.id;
  try {
    if (id) {
      await api(`/api/accounts/${id}`, { method: "PUT", body: JSON.stringify(data) });
      toast("Account aktualisiert.", "success");
    } else {
      await api("/api/accounts", { method: "POST", body: JSON.stringify(data) });
      toast("Account angelegt.", "success");
    }
    resetForm(accountForm);
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
});

function editAccount(acc) {
  accountForm.querySelector('[name="id"]').value = acc.id;
  accountForm.querySelector('[name="name"]').value = acc.name;
  accountForm.querySelector('[name="type"]').value = acc.type;
  accountForm.querySelector('[name="server"]').value = acc.server;
  accountForm.querySelector('[name="port"]').value = acc.port;
  accountForm.querySelector('[name="user"]').value = acc.user;
  accountForm.querySelector('[name="pass"]').value = acc.pass;
  accountForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function deleteAccount(acc) {
  if (!confirm(`Account "${acc.name}" wirklich loeschen?`)) return;
  try {
    await api(`/api/accounts/${acc.id}`, { method: "DELETE" });
    toast("Account geloescht.", "success");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---------- Actions CRUD ----------

actionForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formToObject(actionForm);
  const id = data.id;
  try {
    if (id) {
      await api(`/api/actions/${id}`, { method: "PUT", body: JSON.stringify(data) });
      toast("Action aktualisiert.", "success");
    } else {
      await api("/api/actions", { method: "POST", body: JSON.stringify(data) });
      toast("Action angelegt.", "success");
    }
    resetForm(actionForm, "action");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
});

el("btn-load-folders").addEventListener("click", async () => {
  const data = formToObject(actionForm);
  if (!data.server || !data.user || !data.pass || !data.port) {
    toast("Bitte zuerst Server, Port, Benutzer und Passwort ausfuellen.", "error");
    return;
  }
  const btn = el("btn-load-folders");
  const select = el("folder-select");
  btn.disabled = true;
  btn.textContent = "Lade ...";
  try {
    const res = await api("/api/imap/folders", {
      method: "POST",
      body: JSON.stringify({
        type: data.type, server: data.server, port: data.port,
        user: data.user, pass: data.pass,
      }),
    });
    select.innerHTML = '<option value="">Ordner waehlen ...</option>';
    for (const folder of res.folders) {
      if (folder.flags.includes("\\Noselect")) continue;
      const opt = document.createElement("option");
      opt.value = folder.name;
      opt.textContent = folder.name;
      select.appendChild(opt);
    }
    select.style.display = "";
    toast(`${res.folders.length} Ordner gefunden.`, "success");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Ordner laden";
  }
});

el("folder-select").addEventListener("change", (e) => {
  if (e.target.value) {
    actionForm.querySelector('[name="folder"]').value = e.target.value;
  }
});

function editAction(act) {
  actionForm.querySelector('[name="id"]').value = act.id;
  actionForm.querySelector('[name="name"]').value = act.name;
  actionForm.querySelector('[name="type"]').value = act.type;
  actionForm.querySelector('[name="server"]').value = act.server;
  actionForm.querySelector('[name="port"]').value = act.port;
  actionForm.querySelector('[name="user"]').value = act.user;
  actionForm.querySelector('[name="pass"]').value = act.pass;
  actionForm.querySelector('[name="folder"]').value = act.folder;
  actionForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function deleteAction(act) {
  if (!confirm(`Action "${act.name}" wirklich loeschen?`)) return;
  try {
    await api(`/api/actions/${act.id}`, { method: "DELETE" });
    toast("Action geloescht.", "success");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---------- Rules CRUD ----------

function updateRuleFormVisibility() {
  const field = ruleForm.querySelector('[name="field"]').value;
  const headerInput = ruleForm.querySelector('[name="header_name"]');
  const matchSelect = ruleForm.querySelector('[name="match_type"]');
  const valueInput = ruleForm.querySelector('[name="value"]');

  headerInput.style.display = field === "header" ? "" : "none";
  headerInput.required = field === "header";

  const isCatchAll = field === "all";
  matchSelect.style.display = isCatchAll ? "none" : "";
  valueInput.style.display = isCatchAll ? "none" : "";
  valueInput.required = !isCatchAll;
}

ruleForm.querySelector('[name="field"]').addEventListener("change", updateRuleFormVisibility);
updateRuleFormVisibility();

ruleForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formToObject(ruleForm);
  const id = data.id;
  try {
    if (id) {
      await api(`/api/rules/${id}`, { method: "PUT", body: JSON.stringify(data) });
      toast("Regel aktualisiert.", "success");
    } else {
      await api("/api/rules", { method: "POST", body: JSON.stringify(data) });
      toast("Regel angelegt.", "success");
    }
    resetForm(ruleForm, "rule");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
});

function editRule(rule) {
  ruleForm.querySelector('[name="id"]').value = rule.id;
  ruleForm.querySelector('[name="field"]').value = rule.field;
  ruleForm.querySelector('[name="header_name"]').value = rule.header_name || "";
  ruleForm.querySelector('[name="match_type"]').value = rule.match_type || "contains";
  ruleForm.querySelector('[name="value"]').value = rule.value || "";
  ruleForm.querySelector('[name="action_id"]').value = rule.action_id;
  updateRuleFormVisibility();
  ruleForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function deleteRule(rule) {
  if (!confirm("Regel wirklich loeschen?")) return;
  try {
    await api(`/api/rules/${rule.id}`, { method: "DELETE" });
    toast("Regel geloescht.", "success");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function persistRuleOrder() {
  const order = state.rules.map((r) => r.id);
  try {
    await api("/api/rules/reorder", { method: "POST", body: JSON.stringify({ order }) });
    await refreshPreview();
  } catch (err) {
    toast(err.message, "error");
    await loadAll();
  }
}

function moveRule(idx, delta) {
  const target = idx + delta;
  if (target < 0 || target >= state.rules.length) return;
  const [item] = state.rules.splice(idx, 1);
  state.rules.splice(target, 0, item);
  renderRules();
  persistRuleOrder();
}

// ---------- Drag & drop reordering ----------

let dragSourceId = null;

function attachDragHandlers() {
  const items = document.querySelectorAll(".rule-item");
  items.forEach((item) => {
    item.addEventListener("dragstart", () => {
      dragSourceId = item.dataset.id;
      item.classList.add("dragging");
    });
    item.addEventListener("dragend", () => {
      item.classList.remove("dragging");
      dragSourceId = null;
    });
    item.addEventListener("dragover", (e) => {
      e.preventDefault();
    });
    item.addEventListener("drop", (e) => {
      e.preventDefault();
      const targetId = item.dataset.id;
      if (!dragSourceId || dragSourceId === targetId) return;
      const fromIdx = state.rules.findIndex((r) => r.id === dragSourceId);
      const toIdx = state.rules.findIndex((r) => r.id === targetId);
      const [moved] = state.rules.splice(fromIdx, 1);
      state.rules.splice(toIdx, 0, moved);
      renderRules();
      persistRuleOrder();
    });
  });
}

// ---------- Cancel buttons ----------

document.querySelectorAll("[data-cancel]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const name = btn.dataset.cancel;
    resetForm({ account: accountForm, action: actionForm, rule: ruleForm }[name], name);
  });
});

// ---------- Preview / Export ----------

async function refreshPreview() {
  try {
    const { conf, warnings } = await api("/api/preview");
    el("preview").textContent = conf;
    const warningsBox = el("warnings");
    warningsBox.innerHTML = "";
    for (const w of warnings) {
      const div = document.createElement("div");
      div.className = "warning-item";
      div.textContent = w;
      warningsBox.appendChild(div);
    }
  } catch (err) {
    toast(err.message, "error");
  }
}

el("btn-refresh-preview").addEventListener("click", refreshPreview);

el("btn-download").addEventListener("click", () => {
  window.location.href = "/api/download";
});

async function saveToDisk(target) {
  if (target === "/etc/fdm.conf") {
    if (!confirm("Wirklich unter /etc/fdm.conf speichern? Dies erfordert entsprechende Schreibrechte.")) return;
  }
  try {
    const res = await api("/api/save", { method: "POST", body: JSON.stringify({ target }) });
    toast(`Gespeichert: ${res.saved_to}`, "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

el("btn-save-export").addEventListener("click", () => saveToDisk("export"));
el("btn-save-home").addEventListener("click", () => saveToDisk("~/.fdm.conf"));
el("btn-save-etc").addEventListener("click", () => saveToDisk("/etc/fdm.conf"));

loadAll();
