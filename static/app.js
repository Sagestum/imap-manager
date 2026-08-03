"use strict";

const state = { accounts: [], actions: [], rules: [] };
let currentSourceFolders = [];
let currentDestFolders = [];

const el = (id) => document.getElementById(id);
const accountForm = el("account-form");
const actionForm = el("action-form");
const exceptionForm = el("exception-form");
const mappingForm = el("mapping-form");
const catchallForm = el("catchall-form");

const EXCEPTION_FIELDS = ["from", "subject", "header"];
const isExceptionField = (field) => EXCEPTION_FIELDS.includes(field);

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
  return Object.fromEntries(new FormData(form).entries());
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
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

function accountsWithFolders() {
  return state.accounts.filter((a) => (a.source_folders || []).length);
}

function actionsWithFolders() {
  return state.actions.filter((a) => (a.dest_folders || []).length);
}

function populateSelect(select, items, placeholder) {
  const current = select.value;
  select.innerHTML = `<option value="">${placeholder}</option>`;
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.name;
    select.appendChild(opt);
  }
  select.value = current;
}

function updateDependentFolderSelect(parentSelect, folderSelect, getItems, getFolders) {
  const current = folderSelect.value;
  const item = getItems().find((i) => i.id === parentSelect.value);
  folderSelect.innerHTML = '<option value="">Ordner waehlen ...</option>';
  for (const folder of (item ? getFolders(item) : []) || []) {
    const opt = document.createElement("option");
    opt.value = folder;
    opt.textContent = folder;
    folderSelect.appendChild(opt);
  }
  folderSelect.value = current;
}

function resetDependentFolderSelect(select) {
  select.innerHTML = '<option value="">Ordner waehlen ...</option>';
}

function resetForm(form, name) {
  form.reset();
  const idField = form.querySelector('[name="id"]');
  if (idField) idField.value = "";

  if (name === "account") {
    currentSourceFolders = [];
    renderSourceFolderChips();
    el("source-folder-select").style.display = "none";
    el("source-folder-select").innerHTML = "";
    el("btn-add-source-folder").style.display = "none";
    updateAccountFolderFieldVisibility();
  }
  if (name === "action") {
    currentDestFolders = [];
    renderDestFolderChips();
    el("dest-folder-select").style.display = "none";
    el("dest-folder-select").innerHTML = "";
    el("btn-add-dest-folder").style.display = "none";
  }
  if (name === "exception") {
    updateExceptionFormVisibility();
    resetDependentFolderSelect(exceptionForm.querySelector('[name="dest_folder"]'));
  }
  if (name === "mapping") {
    resetDependentFolderSelect(mappingForm.querySelector('[name="source_folder"]'));
    resetDependentFolderSelect(mappingForm.querySelector('[name="dest_folder"]'));
  }
}

// ---------- Load & render ----------

async function loadAll() {
  const config = await api("/api/config");
  state.accounts = config.accounts;
  state.actions = config.actions;
  state.rules = config.rules;
  renderAccounts();
  renderActions();
  renderExceptions();
  renderMappings();
  renderCatchall();
  refreshPreview();
}

function renderAccounts() {
  const tbody = document.querySelector("#accounts-table tbody");
  tbody.innerHTML = "";
  for (const acc of state.accounts) {
    const folders = acc.source_folders || [];
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(acc.name)}</td>
      <td>${acc.type}</td>
      <td>${escapeHtml(acc.server)}</td>
      <td>${acc.port}</td>
      <td>${escapeHtml(acc.user)}</td>
      <td>${folders.length ? escapeHtml(folders.join(", ")) : "<em>(Standard)</em>"}</td>
      <td></td>`;
    const actionsTd = tr.querySelector("td:last-child");
    actionsTd.appendChild(makeButton("Bearbeiten", () => editAccount(acc)));
    actionsTd.appendChild(makeButton("Loeschen", () => deleteAccount(acc), true));
    tbody.appendChild(tr);
  }

  const mappingAccountSelect = mappingForm.querySelector('[name="source_account_id"]');
  populateSelect(mappingAccountSelect, accountsWithFolders(), "Quell-Konto waehlen ...");
  updateDependentFolderSelect(
    mappingAccountSelect, mappingForm.querySelector('[name="source_folder"]'),
    accountsWithFolders, (a) => a.source_folders,
  );
}

function renderActions() {
  const tbody = document.querySelector("#actions-table tbody");
  tbody.innerHTML = "";
  for (const act of state.actions) {
    const folders = act.dest_folders || [];
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(act.name)}</td>
      <td>${act.type}</td>
      <td>${escapeHtml(act.server)}</td>
      <td>${act.port}</td>
      <td>${escapeHtml(act.user)}</td>
      <td>${folders.length ? escapeHtml(folders.join(", ")) : "<em>(keine)</em>"}</td>
      <td></td>`;
    const actionsTd = tr.querySelector("td:last-child");
    actionsTd.appendChild(makeButton("Bearbeiten", () => editAction(act)));
    actionsTd.appendChild(makeButton("Loeschen", () => deleteAction(act), true));
    tbody.appendChild(tr);
  }

  for (const form of [exceptionForm, mappingForm, catchallForm]) {
    const destSelect = form.querySelector('[name="dest_action_id"]');
    populateSelect(destSelect, actionsWithFolders(), "Ziel-Server waehlen ...");
    updateDependentFolderSelect(
      destSelect, form.querySelector('[name="dest_folder"]'),
      actionsWithFolders, (a) => a.dest_folders,
    );
  }
}

// ---------- Quell-Konten CRUD ----------

accountForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formToObject(accountForm);
  data.source_folders = currentSourceFolders;
  const id = data.id;
  try {
    if (id) {
      await api(`/api/accounts/${id}`, { method: "PUT", body: JSON.stringify(data) });
      toast("Konto aktualisiert.", "success");
    } else {
      await api("/api/accounts", { method: "POST", body: JSON.stringify(data) });
      toast("Konto angelegt.", "success");
    }
    resetForm(accountForm, "account");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
});

function updateAccountFolderFieldVisibility() {
  const type = accountForm.querySelector('[name="type"]').value;
  const isImap = type === "imap" || type === "imaps";
  el("account-folder-field").style.display = isImap ? "" : "none";
  if (!isImap && currentSourceFolders.length) {
    currentSourceFolders = [];
    renderSourceFolderChips();
  }
}

accountForm.querySelector('[name="type"]').addEventListener("change", updateAccountFolderFieldVisibility);

function renderChips(containerId, items, onRemove) {
  const box = el(containerId);
  box.innerHTML = "";
  for (const item of items) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = item;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.addEventListener("click", () => onRemove(item));
    chip.appendChild(remove);
    box.appendChild(chip);
  }
}

function renderSourceFolderChips() {
  renderChips("source-folders-chips", currentSourceFolders, (folder) => {
    currentSourceFolders = currentSourceFolders.filter((f) => f !== folder);
    renderSourceFolderChips();
  });
}

function renderDestFolderChips() {
  renderChips("dest-folders-chips", currentDestFolders, (folder) => {
    currentDestFolders = currentDestFolders.filter((f) => f !== folder);
    renderDestFolderChips();
  });
}

async function fetchFolders(data) {
  if (!data.server || !data.user || !data.pass || !data.port) {
    toast("Bitte zuerst Server, Port, Benutzer und Passwort ausfuellen.", "error");
    return null;
  }
  return api("/api/imap/folders", {
    method: "POST",
    body: JSON.stringify({
      type: data.type, server: data.server, port: data.port,
      user: data.user, pass: data.pass,
    }),
  });
}

el("btn-load-source-folders").addEventListener("click", async () => {
  const btn = el("btn-load-source-folders");
  const select = el("source-folder-select");
  btn.disabled = true;
  btn.textContent = "Lade ...";
  try {
    const res = await fetchFolders(formToObject(accountForm));
    if (!res) return;
    select.innerHTML = "";
    for (const folder of res.folders) {
      if (folder.flags.includes("\\Noselect")) continue;
      const opt = document.createElement("option");
      opt.value = folder.name;
      opt.textContent = folder.name;
      select.appendChild(opt);
    }
    select.style.display = "";
    el("btn-add-source-folder").style.display = "";
    toast(`${res.folders.length} Ordner gefunden.`, "success");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Ordner laden";
  }
});

el("btn-add-source-folder").addEventListener("click", () => {
  const folder = el("source-folder-select").value;
  if (folder && !currentSourceFolders.includes(folder)) {
    currentSourceFolders.push(folder);
    renderSourceFolderChips();
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
  currentSourceFolders = [...(acc.source_folders || [])];
  renderSourceFolderChips();
  updateAccountFolderFieldVisibility();
  accountForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function deleteAccount(acc) {
  if (!confirm(`Konto "${acc.name}" wirklich loeschen?`)) return;
  try {
    await api(`/api/accounts/${acc.id}`, { method: "DELETE" });
    toast("Konto geloescht.", "success");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---------- Ziel-Server CRUD ----------

actionForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formToObject(actionForm);
  data.dest_folders = currentDestFolders;
  const id = data.id;
  try {
    if (id) {
      await api(`/api/actions/${id}`, { method: "PUT", body: JSON.stringify(data) });
      toast("Ziel-Server aktualisiert.", "success");
    } else {
      await api("/api/actions", { method: "POST", body: JSON.stringify(data) });
      toast("Ziel-Server angelegt.", "success");
    }
    resetForm(actionForm, "action");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
});

el("btn-load-dest-folders").addEventListener("click", async () => {
  const btn = el("btn-load-dest-folders");
  const select = el("dest-folder-select");
  btn.disabled = true;
  btn.textContent = "Lade ...";
  try {
    const res = await fetchFolders(formToObject(actionForm));
    if (!res) return;
    select.innerHTML = "";
    for (const folder of res.folders) {
      if (folder.flags.includes("\\Noselect")) continue;
      const opt = document.createElement("option");
      opt.value = folder.name;
      opt.textContent = folder.name;
      select.appendChild(opt);
    }
    select.style.display = "";
    el("btn-add-dest-folder").style.display = "";
    toast(`${res.folders.length} Ordner gefunden.`, "success");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Ordner laden";
  }
});

el("btn-add-dest-folder").addEventListener("click", () => {
  const folder = el("dest-folder-select").value;
  if (folder && !currentDestFolders.includes(folder)) {
    currentDestFolders.push(folder);
    renderDestFolderChips();
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
  currentDestFolders = [...(act.dest_folders || [])];
  renderDestFolderChips();
  actionForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function deleteAction(act) {
  if (!confirm(`Ziel-Server "${act.name}" wirklich loeschen?`)) return;
  try {
    await api(`/api/actions/${act.id}`, { method: "DELETE" });
    toast("Ziel-Server geloescht.", "success");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---------- Regeln: gemeinsames Loeschen ----------

async function deleteRule(rule) {
  if (!confirm("Wirklich loeschen?")) return;
  try {
    await api(`/api/rules/${rule.id}`, { method: "DELETE" });
    toast("Geloescht.", "success");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---------- Ausnahmeregeln ----------

function updateExceptionFormVisibility() {
  const field = exceptionForm.querySelector('[name="field"]').value;
  const headerInput = exceptionForm.querySelector('[name="header_name"]');
  headerInput.style.display = field === "header" ? "" : "none";
  headerInput.required = field === "header";
}

exceptionForm.querySelector('[name="field"]').addEventListener("change", updateExceptionFormVisibility);
updateExceptionFormVisibility();

exceptionForm.querySelector('[name="dest_action_id"]').addEventListener("change", (e) => {
  updateDependentFolderSelect(
    e.target, exceptionForm.querySelector('[name="dest_folder"]'),
    actionsWithFolders, (a) => a.dest_folders,
  );
});

exceptionForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formToObject(exceptionForm);
  const id = data.id;
  try {
    if (id) {
      await api(`/api/rules/${id}`, { method: "PUT", body: JSON.stringify(data) });
      toast("Ausnahmeregel aktualisiert.", "success");
    } else {
      await api("/api/rules", { method: "POST", body: JSON.stringify(data) });
      toast("Ausnahmeregel angelegt.", "success");
    }
    resetForm(exceptionForm, "exception");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
});

function exceptionDestLabel(rule) {
  const action = state.actions.find((a) => a.id === rule.dest_action_id);
  return `${action ? escapeHtml(action.name) : "?"} / ${escapeHtml(rule.dest_folder || "?")}`;
}

function exceptionLabel(rule) {
  const fieldLabel = { from: "From", subject: "Subject", header: rule.header_name }[rule.field];
  const matchLabel = { contains: "enthaelt", exact: "exakt", regex: "regex" }[rule.match_type];
  return `<code>${escapeHtml(fieldLabel)}</code> ${matchLabel} <code>${escapeHtml(rule.value)}</code> &rarr; <code>${exceptionDestLabel(rule)}</code>`;
}

function getExceptions() {
  return state.rules.filter((r) => isExceptionField(r.field));
}

function setExceptionOrder(newExceptions) {
  const others = state.rules.filter((r) => !isExceptionField(r.field));
  state.rules = [...newExceptions, ...others];
}

function renderExceptions() {
  const list = el("exceptions-list");
  list.innerHTML = "";
  const exceptions = getExceptions();
  exceptions.forEach((rule, idx) => {
    const li = document.createElement("li");
    li.className = "rule-item";
    li.draggable = true;
    li.dataset.id = rule.id;

    const handle = document.createElement("span");
    handle.className = "drag-handle";
    handle.textContent = "☰";

    const body = document.createElement("span");
    body.className = "rule-body";
    body.innerHTML = exceptionLabel(rule);

    const actionsSpan = document.createElement("span");
    actionsSpan.className = "rule-actions";
    actionsSpan.appendChild(makeIconButton("↑", () => moveException(idx, -1), idx === 0));
    actionsSpan.appendChild(makeIconButton("↓", () => moveException(idx, 1), idx === exceptions.length - 1));
    actionsSpan.appendChild(makeButton("Bearbeiten", () => editException(rule)));
    actionsSpan.appendChild(makeButton("Loeschen", () => deleteRule(rule), true));

    li.appendChild(handle);
    li.appendChild(body);
    li.appendChild(actionsSpan);
    list.appendChild(li);
  });
  attachExceptionDragHandlers();
}

async function persistExceptionOrder(newExceptionIds) {
  const others = state.rules.filter((r) => !isExceptionField(r.field)).map((r) => r.id);
  const order = [...newExceptionIds, ...others];
  try {
    await api("/api/rules/reorder", { method: "POST", body: JSON.stringify({ order }) });
    await refreshPreview();
  } catch (err) {
    toast(err.message, "error");
    await loadAll();
  }
}

function moveException(idx, delta) {
  const exceptions = getExceptions();
  const target = idx + delta;
  if (target < 0 || target >= exceptions.length) return;
  const [item] = exceptions.splice(idx, 1);
  exceptions.splice(target, 0, item);
  setExceptionOrder(exceptions);
  renderExceptions();
  persistExceptionOrder(exceptions.map((r) => r.id));
}

let dragExceptionId = null;

function attachExceptionDragHandlers() {
  document.querySelectorAll("#exceptions-list .rule-item").forEach((item) => {
    item.addEventListener("dragstart", () => {
      dragExceptionId = item.dataset.id;
      item.classList.add("dragging");
    });
    item.addEventListener("dragend", () => {
      item.classList.remove("dragging");
      dragExceptionId = null;
    });
    item.addEventListener("dragover", (e) => e.preventDefault());
    item.addEventListener("drop", (e) => {
      e.preventDefault();
      const targetId = item.dataset.id;
      if (!dragExceptionId || dragExceptionId === targetId) return;
      const exceptions = getExceptions();
      const fromIdx = exceptions.findIndex((r) => r.id === dragExceptionId);
      const toIdx = exceptions.findIndex((r) => r.id === targetId);
      const [moved] = exceptions.splice(fromIdx, 1);
      exceptions.splice(toIdx, 0, moved);
      setExceptionOrder(exceptions);
      renderExceptions();
      persistExceptionOrder(exceptions.map((r) => r.id));
    });
  });
}

function editException(rule) {
  exceptionForm.querySelector('[name="id"]').value = rule.id;
  exceptionForm.querySelector('[name="field"]').value = rule.field;
  exceptionForm.querySelector('[name="header_name"]').value = rule.header_name || "";
  exceptionForm.querySelector('[name="match_type"]').value = rule.match_type || "contains";
  exceptionForm.querySelector('[name="value"]').value = rule.value || "";
  const destSelect = exceptionForm.querySelector('[name="dest_action_id"]');
  destSelect.value = rule.dest_action_id;
  updateDependentFolderSelect(destSelect, exceptionForm.querySelector('[name="dest_folder"]'), actionsWithFolders, (a) => a.dest_folders);
  exceptionForm.querySelector('[name="dest_folder"]').value = rule.dest_folder || "";
  updateExceptionFormVisibility();
  exceptionForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ---------- Ordner-Zuordnungen ----------

mappingForm.querySelector('[name="source_account_id"]').addEventListener("change", (e) => {
  updateDependentFolderSelect(
    e.target, mappingForm.querySelector('[name="source_folder"]'),
    accountsWithFolders, (a) => a.source_folders,
  );
});

mappingForm.querySelector('[name="dest_action_id"]').addEventListener("change", (e) => {
  updateDependentFolderSelect(
    e.target, mappingForm.querySelector('[name="dest_folder"]'),
    actionsWithFolders, (a) => a.dest_folders,
  );
});

mappingForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formToObject(mappingForm);
  data.field = "source";
  const id = data.id;
  try {
    if (id) {
      await api(`/api/rules/${id}`, { method: "PUT", body: JSON.stringify(data) });
      toast("Zuordnung aktualisiert.", "success");
    } else {
      await api("/api/rules", { method: "POST", body: JSON.stringify(data) });
      toast("Zuordnung angelegt.", "success");
    }
    resetForm(mappingForm, "mapping");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
});

function renderMappings() {
  const tbody = document.querySelector("#mappings-table tbody");
  tbody.innerHTML = "";
  const mappings = state.rules.filter((r) => r.field === "source");
  for (const rule of mappings) {
    const sourceAccount = state.accounts.find((a) => a.id === rule.source_account_id);
    const destAction = state.actions.find((a) => a.id === rule.dest_action_id);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${sourceAccount ? escapeHtml(sourceAccount.name) : "?"} / ${escapeHtml(rule.source_folder || "?")}</td>
      <td class="arrow">&rarr;</td>
      <td>${destAction ? escapeHtml(destAction.name) : "?"} / ${escapeHtml(rule.dest_folder || "?")}</td>
      <td></td>`;
    const actionsTd = tr.querySelector("td:last-child");
    actionsTd.appendChild(makeButton("Bearbeiten", () => editMapping(rule)));
    actionsTd.appendChild(makeButton("Loeschen", () => deleteRule(rule), true));
    tbody.appendChild(tr);
  }
}

function editMapping(rule) {
  mappingForm.querySelector('[name="id"]').value = rule.id;
  const sourceSelect = mappingForm.querySelector('[name="source_account_id"]');
  sourceSelect.value = rule.source_account_id;
  updateDependentFolderSelect(sourceSelect, mappingForm.querySelector('[name="source_folder"]'), accountsWithFolders, (a) => a.source_folders);
  mappingForm.querySelector('[name="source_folder"]').value = rule.source_folder || "";

  const destSelect = mappingForm.querySelector('[name="dest_action_id"]');
  destSelect.value = rule.dest_action_id;
  updateDependentFolderSelect(destSelect, mappingForm.querySelector('[name="dest_folder"]'), actionsWithFolders, (a) => a.dest_folders);
  mappingForm.querySelector('[name="dest_folder"]').value = rule.dest_folder || "";

  mappingForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ---------- Catch-All ----------

catchallForm.querySelector('[name="dest_action_id"]').addEventListener("change", (e) => {
  updateDependentFolderSelect(
    e.target, catchallForm.querySelector('[name="dest_folder"]'),
    actionsWithFolders, (a) => a.dest_folders,
  );
});

catchallForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formToObject(catchallForm);
  data.field = "all";
  const id = data.id;
  try {
    if (id) {
      await api(`/api/rules/${id}`, { method: "PUT", body: JSON.stringify(data) });
    } else {
      await api("/api/rules", { method: "POST", body: JSON.stringify(data) });
    }
    toast("Catch-All gespeichert.", "success");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
});

function editCatchall(rule) {
  catchallForm.querySelector('[name="id"]').value = rule.id;
  const destSelect = catchallForm.querySelector('[name="dest_action_id"]');
  destSelect.value = rule.dest_action_id;
  updateDependentFolderSelect(destSelect, catchallForm.querySelector('[name="dest_folder"]'), actionsWithFolders, (a) => a.dest_folders);
  catchallForm.querySelector('[name="dest_folder"]').value = rule.dest_folder || "";
  catchallForm.style.display = "";
  catchallForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderCatchall() {
  const display = el("catchall-display");
  const catchall = state.rules.find((r) => r.field === "all");
  display.innerHTML = "";
  if (catchall) {
    const action = state.actions.find((a) => a.id === catchall.dest_action_id);
    const p = document.createElement("p");
    p.innerHTML = `Alle uebrigen Mails &rarr; <code>${action ? escapeHtml(action.name) : "?"} / ${escapeHtml(catchall.dest_folder || "?")}</code>`;
    display.appendChild(p);
    display.appendChild(makeButton("Bearbeiten", () => editCatchall(catchall)));
    display.appendChild(makeButton("Entfernen", () => deleteRule(catchall), true));
    catchallForm.style.display = "none";
  } else {
    catchallForm.reset();
    catchallForm.style.display = "";
  }
}

// ---------- Cancel-Buttons ----------

document.querySelectorAll("[data-cancel]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const name = btn.dataset.cancel;
    const forms = { account: accountForm, action: actionForm, exception: exceptionForm, mapping: mappingForm };
    resetForm(forms[name], name);
  });
});

// ---------- Vorschau / Export ----------

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

el("btn-run-now").addEventListener("click", async () => {
  const btn = el("btn-run-now");
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "Wird ausgefuehrt ...";
  try {
    const res = await api("/api/run-now", { method: "POST" });
    toast(`Gespeichert unter ${res.saved_to}, fdm-runner wird ausloesen.`, "success");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
});

// ---------- Verlauf ----------

function renderHistory(folders) {
  const box = el("history-results");
  box.innerHTML = "";
  if (!folders.length) {
    box.innerHTML = '<p class="hint">Keine Ziel-Ordner mit zugeordneten Regeln gefunden.</p>';
    return;
  }
  for (const group of folders) {
    const section = document.createElement("div");
    section.className = "history-group";

    const title = document.createElement("h3");
    title.innerHTML = `<code>${escapeHtml(group.action_name)} / ${escapeHtml(group.folder)}</code>`;
    section.appendChild(title);

    const rulesLine = document.createElement("p");
    rulesLine.className = "hint";
    rulesLine.textContent = "Regel(n): " + group.rules.join(" · ");
    section.appendChild(rulesLine);

    if (group.error) {
      const err = document.createElement("div");
      err.className = "warning-item";
      err.textContent = group.error;
      section.appendChild(err);
    } else if (!group.messages.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "Keine Mails in diesem Ordner gefunden.";
      section.appendChild(empty);
    } else {
      const table = document.createElement("table");
      table.innerHTML = "<thead><tr><th>Datum</th><th>Von</th><th>Betreff</th></tr></thead>";
      const tbody = document.createElement("tbody");
      for (const msg of group.messages) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${escapeHtml(msg.date)}</td><td>${escapeHtml(msg.from)}</td><td>${escapeHtml(msg.subject)}</td>`;
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      section.appendChild(table);
    }
    box.appendChild(section);
  }
}

el("btn-load-history").addEventListener("click", async () => {
  const btn = el("btn-load-history");
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "Lade ...";
  try {
    const res = await api("/api/history");
    renderHistory(res.folders);
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
});

api("/api/version")
  .then((res) => { el("app-version").textContent = `Version: ${res.version}`; })
  .catch(() => { /* Versionsanzeige ist rein informativ, kein Fehler-Toast noetig */ });

loadAll();
