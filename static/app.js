"use strict";

const state = { accounts: [], actions: [], rules: [], filters: [] };
let currentSourceFolders = [];
let currentDestFolders = [];

const el = (id) => document.getElementById(id);
const accountForm = el("account-form");
const actionForm = el("action-form");
const mappingForm = el("mapping-form");
const catchallForm = el("catchall-form");
const filterForm = el("filter-form");

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
  if (name === "mapping") {
    resetDependentFolderSelect(mappingForm.querySelector('[name="source_folder"]'));
    resetDependentFolderSelect(mappingForm.querySelector('[name="dest_folder"]'));
  }
  if (name === "filter") {
    resetDependentFolderSelect(filterForm.querySelector('[name="watch_folder"]'));
    resetDependentFolderSelect(filterForm.querySelector('[name="target_folder"]'));
  }
}

// ---------- Load & render ----------

async function loadAll() {
  const config = await api("/api/config");
  state.accounts = config.accounts;
  state.actions = config.actions;
  state.rules = config.rules;
  state.filters = config.filters;
  renderAccounts();
  renderActions();
  renderMappings();
  renderCatchall();
  renderFilters();
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

  for (const form of [mappingForm, catchallForm]) {
    const destSelect = form.querySelector('[name="dest_action_id"]');
    populateSelect(destSelect, actionsWithFolders(), "Ziel-Server waehlen ...");
    updateDependentFolderSelect(
      destSelect, form.querySelector('[name="dest_folder"]'),
      actionsWithFolders, (a) => a.dest_folders,
    );
  }

  const filterDestSelect = filterForm.querySelector('[name="dest_action_id"]');
  populateSelect(filterDestSelect, actionsWithFolders(), "Ziel-Server waehlen ...");
  updateDependentFolderSelect(
    filterDestSelect, filterForm.querySelector('[name="watch_folder"]'),
    actionsWithFolders, (a) => a.dest_folders,
  );
  updateDependentFolderSelect(
    filterDestSelect, filterForm.querySelector('[name="target_folder"]'),
    actionsWithFolders, (a) => a.dest_folders,
  );
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

// ---------- Filter (Post-Sync) ----------

filterForm.querySelector('[name="dest_action_id"]').addEventListener("change", (e) => {
  updateDependentFolderSelect(
    e.target, filterForm.querySelector('[name="watch_folder"]'),
    actionsWithFolders, (a) => a.dest_folders,
  );
  updateDependentFolderSelect(
    e.target, filterForm.querySelector('[name="target_folder"]'),
    actionsWithFolders, (a) => a.dest_folders,
  );
});

filterForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formToObject(filterForm);
  const id = data.id;
  try {
    if (id) {
      await api(`/api/filters/${id}`, { method: "PUT", body: JSON.stringify(data) });
      toast("Filter aktualisiert.", "success");
    } else {
      await api("/api/filters", { method: "POST", body: JSON.stringify(data) });
      toast("Filter angelegt.", "success");
    }
    resetForm(filterForm, "filter");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
});

function renderFilters() {
  const tbody = document.querySelector("#filters-table tbody");
  tbody.innerHTML = "";
  for (const flt of state.filters) {
    const destAction = state.actions.find((a) => a.id === flt.dest_action_id);
    const headerLabel = flt.header === "subject" ? "Betreff" : "Absender";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${destAction ? escapeHtml(destAction.name) : "?"} / ${escapeHtml(flt.watch_folder || "?")}</td>
      <td>${headerLabel} enthaelt &quot;${escapeHtml(flt.match || "")}&quot;</td>
      <td class="arrow">&rarr;</td>
      <td>${escapeHtml(flt.target_folder || "?")}</td>
      <td></td>`;
    const actionsTd = tr.querySelector("td:last-child");
    actionsTd.appendChild(makeButton("Bearbeiten", () => editFilter(flt)));
    actionsTd.appendChild(makeButton("Loeschen", () => deleteFilter(flt), true));
    tbody.appendChild(tr);
  }
}

function editFilter(flt) {
  filterForm.querySelector('[name="id"]').value = flt.id;
  const destSelect = filterForm.querySelector('[name="dest_action_id"]');
  destSelect.value = flt.dest_action_id;
  updateDependentFolderSelect(destSelect, filterForm.querySelector('[name="watch_folder"]'), actionsWithFolders, (a) => a.dest_folders);
  filterForm.querySelector('[name="watch_folder"]').value = flt.watch_folder || "";
  updateDependentFolderSelect(destSelect, filterForm.querySelector('[name="target_folder"]'), actionsWithFolders, (a) => a.dest_folders);
  filterForm.querySelector('[name="target_folder"]').value = flt.target_folder || "";
  filterForm.querySelector('[name="header"]').value = flt.header;
  filterForm.querySelector('[name="match"]').value = flt.match;
  filterForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function deleteFilter(flt) {
  if (!confirm("Wirklich loeschen?")) return;
  try {
    await api(`/api/filters/${flt.id}`, { method: "DELETE" });
    toast("Geloescht.", "success");
    await loadAll();
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---------- Cancel-Buttons ----------

document.querySelectorAll("[data-cancel]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const name = btn.dataset.cancel;
    const forms = { account: accountForm, action: actionForm, mapping: mappingForm, filter: filterForm };
    resetForm(forms[name], name);
  });
});

// ---------- Sync ----------

el("btn-run-now").addEventListener("click", async () => {
  const btn = el("btn-run-now");
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "Wird ausgefuehrt ...";
  try {
    const res = await api("/api/run-now", { method: "POST" });
    toast(`Gespeichert (${res.mappings} Zuordnung(en)), Runner wird ausgeloest.`, "success");
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

// ---------- Statistik ----------
//
// Liniendiagramm (Nachrichten pro Konto und Tag), reines Vanilla-SVG ohne Chart-Library, passend
// zum Rest der App. Farb-Slots und Kontrast-Vorgaben stammen aus der dataviz-Skill-Palette,
// validiert gegen --card-bg als Chart-Oberflaeche (siehe Kommentar in style.css).

const STATS_SVG_NS = "http://www.w3.org/2000/svg";
const STATS_COLOR_VARS = [
  "--series-1", "--series-2", "--series-3", "--series-4",
  "--series-5", "--series-6", "--series-7",
];
const STATS_OTHER_COLOR = "var(--text-dim)";
const STATS_MAX_SLOTS = STATS_COLOR_VARS.length;

let statsChartState = null; // { hidden: Set<string> } - welche Legenden-Eintraege ausgeblendet sind
let statsShowTable = false;

function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  const norm = value / magnitude;
  const niceNorm = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return niceNorm * magnitude;
}

function formatDayLabel(iso) {
  const [, m, d] = iso.split("-");
  return `${d}.${m}.`;
}

// Baut die (ggf. auf STATS_MAX_SLOTS zusammengefaltete) Serienliste, sortiert aufsteigend nach
// Gesamtsumme, damit beim Zeichnen die aktivsten Postfaecher zuletzt (also oben) liegen. Mehr als
// STATS_MAX_SLOTS Konten werden zu einer "Andere"-Sammelserie zusammengefasst statt weitere,
// nicht mehr unterscheidbare Farben zu erzeugen.
function buildStatsSeries(days, accounts, series, totals) {
  const sorted = [...accounts].sort((a, b) => (totals[b] || 0) - (totals[a] || 0));
  const shown = sorted.slice(0, STATS_MAX_SLOTS);
  const overflow = sorted.slice(STATS_MAX_SLOTS);

  const result = shown.map((name, i) => ({
    name,
    color: `var(${STATS_COLOR_VARS[i]})`,
    values: series[name],
    total: totals[name] || 0,
  }));

  if (overflow.length) {
    const combined = new Array(days.length).fill(0);
    let overflowTotal = 0;
    for (const name of overflow) {
      series[name].forEach((v, i) => { combined[i] += v; });
      overflowTotal += totals[name] || 0;
    }
    result.push({
      name: `Andere (${overflow.length} Konten)`,
      color: STATS_OTHER_COLOR,
      values: combined,
      total: overflowTotal,
    });
  }

  return result.sort((a, b) => a.total - b.total);
}

function renderStatsChart(days, seriesList) {
  const wrap = el("stats-chart");
  wrap.innerHTML = "";

  const W = 900, H = 300;
  const margin = { top: 12, right: 14, bottom: 26, left: 42 };
  const plotW = W - margin.left - margin.right;
  const plotH = H - margin.top - margin.bottom;

  const maxVal = niceMax(Math.max(1, ...seriesList.flatMap((s) => s.values)));
  const tickCount = 4;
  const yTicks = Array.from({ length: tickCount + 1 }, (_, i) => Math.round((maxVal / tickCount) * i));

  const xAt = (i) => margin.left + (days.length > 1 ? (i / (days.length - 1)) * plotW : plotW / 2);
  const yAt = (v) => margin.top + plotH - (v / maxVal) * plotH;

  const svg = document.createElementNS(STATS_SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Nachrichten pro Postfach und Tag - Werte auch als Tabelle verfuegbar");

  for (const t of yTicks) {
    const y = yAt(t);
    const line = document.createElementNS(STATS_SVG_NS, "line");
    line.setAttribute("class", "stats-gridline");
    line.setAttribute("x1", margin.left); line.setAttribute("x2", W - margin.right);
    line.setAttribute("y1", y); line.setAttribute("y2", y);
    svg.appendChild(line);

    const label = document.createElementNS(STATS_SVG_NS, "text");
    label.setAttribute("x", margin.left - 8); label.setAttribute("y", y + 3);
    label.setAttribute("text-anchor", "end");
    label.textContent = String(t);
    svg.appendChild(label);
  }

  const axisLine = document.createElementNS(STATS_SVG_NS, "line");
  axisLine.setAttribute("class", "stats-axis");
  axisLine.setAttribute("x1", margin.left); axisLine.setAttribute("x2", W - margin.right);
  axisLine.setAttribute("y1", margin.top + plotH); axisLine.setAttribute("y2", margin.top + plotH);
  svg.appendChild(axisLine);

  const targetTicks = 7;
  const step = Math.max(1, Math.ceil(days.length / targetTicks));
  for (let i = 0; i < days.length; i += step) {
    const label = document.createElementNS(STATS_SVG_NS, "text");
    label.setAttribute("x", xAt(i)); label.setAttribute("y", margin.top + plotH + 16);
    label.setAttribute("text-anchor", "middle");
    label.textContent = formatDayLabel(days[i]);
    svg.appendChild(label);
  }
  if ((days.length - 1) % step !== 0) {
    const label = document.createElementNS(STATS_SVG_NS, "text");
    label.setAttribute("x", xAt(days.length - 1)); label.setAttribute("y", margin.top + plotH + 16);
    label.setAttribute("text-anchor", "middle");
    label.textContent = formatDayLabel(days[days.length - 1]);
    svg.appendChild(label);
  }

  for (const s of seriesList) {
    const points = s.values.map((v, i) => `${xAt(i)},${yAt(v)}`).join(" ");
    const line = document.createElementNS(STATS_SVG_NS, "polyline");
    line.setAttribute("class", "stats-line");
    line.setAttribute("points", points);
    line.setAttribute("stroke", s.color);
    svg.appendChild(line);
    s._pathEl = line;

    const lastVal = s.values[s.values.length - 1];
    const dot = document.createElementNS(STATS_SVG_NS, "circle");
    dot.setAttribute("class", "stats-end-dot");
    dot.setAttribute("cx", xAt(days.length - 1)); dot.setAttribute("cy", yAt(lastVal)); dot.setAttribute("r", 4);
    dot.setAttribute("fill", s.color);
    svg.appendChild(dot);
    s._dotEl = dot;
  }

  const crosshairLine = document.createElementNS(STATS_SVG_NS, "line");
  crosshairLine.setAttribute("class", "stats-crosshair-line");
  crosshairLine.setAttribute("y1", margin.top); crosshairLine.setAttribute("y2", margin.top + plotH);
  svg.appendChild(crosshairLine);

  const crosshairDots = seriesList.map((s) => {
    const dot = document.createElementNS(STATS_SVG_NS, "circle");
    dot.setAttribute("class", "stats-crosshair-dot");
    dot.setAttribute("r", 4);
    dot.setAttribute("fill", s.color);
    svg.appendChild(dot);
    return dot;
  });

  const hitArea = document.createElementNS(STATS_SVG_NS, "rect");
  hitArea.setAttribute("class", "stats-hit-area");
  hitArea.setAttribute("x", margin.left); hitArea.setAttribute("y", margin.top);
  hitArea.setAttribute("width", plotW); hitArea.setAttribute("height", plotH);
  hitArea.setAttribute("tabindex", "0");
  hitArea.setAttribute("role", "slider");
  hitArea.setAttribute("aria-label", "Tag auswaehlen (Pfeiltasten zum Navigieren)");
  svg.appendChild(hitArea);

  const tooltip = el("stats-tooltip");

  function showAt(index) {
    index = Math.max(0, Math.min(days.length - 1, index));
    hitArea.dataset.index = index;
    const x = xAt(index);
    crosshairLine.setAttribute("x1", x); crosshairLine.setAttribute("x2", x);
    crosshairLine.style.opacity = 1;

    tooltip.textContent = "";
    const dateEl = document.createElement("div");
    dateEl.className = "stats-tooltip-date";
    dateEl.textContent = days[index];
    tooltip.appendChild(dateEl);

    seriesList.forEach((s, i) => {
      const dot = crosshairDots[i];
      const v = s.values[index];
      const isHidden = statsChartState.hidden.has(s.name);
      dot.setAttribute("cx", x); dot.setAttribute("cy", yAt(v));
      dot.style.opacity = isHidden ? 0 : 1;
      if (isHidden) return;

      const row = document.createElement("div");
      row.className = "stats-tooltip-row";
      const key = document.createElement("span");
      key.className = "stats-tooltip-key";
      key.style.background = s.color;
      const name = document.createElement("span");
      name.className = "stats-tooltip-name";
      name.textContent = s.name;
      const val = document.createElement("span");
      val.className = "stats-tooltip-value";
      val.textContent = String(v);
      row.appendChild(key); row.appendChild(name); row.appendChild(val);
      tooltip.appendChild(row);
    });

    const wrapRect = el("stats-chart-wrap").getBoundingClientRect();
    const svgRect = svg.getBoundingClientRect();
    const scale = svgRect.width / W;
    const px = svgRect.left - wrapRect.left + x * scale;
    const py = svgRect.top - wrapRect.top + margin.top * scale;
    const tooltipWidth = tooltip.offsetWidth || 160;
    const left = Math.min(px + 12, Math.max(0, wrapRect.width - tooltipWidth - 4));
    tooltip.style.transform = `translate(${left}px, ${py}px)`;
    tooltip.classList.add("is-visible");
  }

  function hide() {
    crosshairLine.style.opacity = 0;
    crosshairDots.forEach((d) => { d.style.opacity = 0; });
    tooltip.classList.remove("is-visible");
  }

  function indexFromPointer(evt) {
    const rect = svg.getBoundingClientRect();
    const relX = ((evt.clientX - rect.left) / rect.width) * W;
    const ratio = plotW > 0 ? (relX - margin.left) / plotW : 0;
    return Math.round(ratio * (days.length - 1));
  }

  hitArea.addEventListener("pointermove", (evt) => showAt(indexFromPointer(evt)));
  hitArea.addEventListener("pointerleave", hide);
  hitArea.addEventListener("focus", () => showAt(days.length - 1));
  hitArea.addEventListener("blur", hide);
  hitArea.addEventListener("keydown", (evt) => {
    const current = Number(hitArea.dataset.index ?? days.length - 1);
    let next = current;
    if (evt.key === "ArrowLeft") next = current - 1;
    else if (evt.key === "ArrowRight") next = current + 1;
    else if (evt.key === "Home") next = 0;
    else if (evt.key === "End") next = days.length - 1;
    else return;
    evt.preventDefault();
    showAt(next);
  });

  wrap.appendChild(svg);
}

function renderStatsLegend(seriesList) {
  const box = el("stats-legend");
  box.innerHTML = "";
  // Bei genau einer Serie sagt schon der Kartentitel, was gezeigt wird - eine Legende mit einem
  // Eintrag wuerde nur den Titel wiederholen.
  if (seriesList.length <= 1) return;

  const byTotalDesc = [...seriesList].sort((a, b) => b.total - a.total);
  for (const s of byTotalDesc) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "stats-legend-item";
    btn.setAttribute("aria-pressed", "true");

    const swatch = document.createElementNS(STATS_SVG_NS, "svg");
    swatch.setAttribute("width", "16"); swatch.setAttribute("height", "10");
    const swatchLine = document.createElementNS(STATS_SVG_NS, "line");
    swatchLine.setAttribute("x1", "0"); swatchLine.setAttribute("x2", "16");
    swatchLine.setAttribute("y1", "5"); swatchLine.setAttribute("y2", "5");
    swatchLine.setAttribute("stroke", s.color);
    swatchLine.setAttribute("stroke-width", "2");
    swatchLine.setAttribute("stroke-linecap", "round");
    swatch.appendChild(swatchLine);

    const label = document.createElement("span");
    label.textContent = `${s.name} (${s.total})`;

    btn.appendChild(swatch);
    btn.appendChild(label);
    btn.addEventListener("click", () => {
      const hidden = statsChartState.hidden;
      if (hidden.has(s.name)) hidden.delete(s.name); else hidden.add(s.name);
      const isHidden = hidden.has(s.name);
      btn.classList.toggle("is-dimmed", isHidden);
      btn.setAttribute("aria-pressed", String(!isHidden));
      s._pathEl.classList.toggle("is-dimmed", isHidden);
      s._dotEl.classList.toggle("is-dimmed", isHidden);
    });

    box.appendChild(btn);
  }
}

// Vollstaendige Tages-fuer-Tages-Tabelle - das barrierefreie Gegenstueck zum Chart, unabhaengig
// vom Hover/Tastatur-Zugriff auf die Kurve erreichbar. Zeigt alle Konten, nicht die auf
// STATS_MAX_SLOTS zusammengefaltete Chart-Serie.
function renderStatsTable(days, accounts, series) {
  const box = el("stats-table-wrap");
  box.innerHTML = "";
  const table = document.createElement("table");

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  const dateHeader = document.createElement("th");
  dateHeader.textContent = "Datum";
  headRow.appendChild(dateHeader);
  for (const name of accounts) {
    const th = document.createElement("th");
    th.textContent = name;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (let i = 0; i < days.length; i++) {
    const tr = document.createElement("tr");
    const dateCell = document.createElement("td");
    dateCell.textContent = days[i];
    tr.appendChild(dateCell);
    for (const name of accounts) {
      const td = document.createElement("td");
      td.textContent = String(series[name][i]);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  box.appendChild(table);
}

function renderStatsTotals(accounts, totals, deletedTotals) {
  const tbody = el("stats-totals-body");
  tbody.innerHTML = "";
  const sorted = [...accounts].sort((a, b) => (totals[b] || 0) - (totals[a] || 0));
  for (const name of sorted) {
    const tr = document.createElement("tr");
    const nameTd = document.createElement("td"); nameTd.textContent = name;
    const totalTd = document.createElement("td"); totalTd.textContent = String(totals[name] || 0);
    const delTd = document.createElement("td"); delTd.textContent = String(deletedTotals[name] || 0);
    tr.appendChild(nameTd); tr.appendChild(totalTd); tr.appendChild(delTd);
    tbody.appendChild(tr);
  }
}

async function loadStats() {
  const btn = el("btn-load-stats");
  btn.disabled = true;
  try {
    const days = Number(el("stats-range").value);
    const res = await api(`/api/stats/daily?days=${days}`);
    renderStatsTotals(res.accounts, res.totals, res.deleted_totals);

    const empty = el("stats-empty");
    const chartWrap = el("stats-chart-wrap");
    const toggleBtn = el("btn-toggle-stats-table");

    if (!res.accounts.length) {
      empty.style.display = "";
      chartWrap.style.display = "none";
      toggleBtn.style.display = "none";
      el("stats-table-wrap").style.display = "none";
      statsChartState = null;
      return;
    }

    empty.style.display = "none";
    chartWrap.style.display = "";
    toggleBtn.style.display = "";

    statsChartState = { hidden: new Set() };
    const seriesList = buildStatsSeries(res.days, res.accounts, res.series, res.totals);
    renderStatsChart(res.days, seriesList);
    renderStatsLegend(seriesList);
    renderStatsTable(res.days, res.accounts, res.series);

    statsShowTable = false;
    el("stats-table-wrap").style.display = "none";
    toggleBtn.textContent = "Als Tabelle anzeigen";
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

el("btn-load-stats").addEventListener("click", loadStats);
el("stats-range").addEventListener("change", loadStats);
el("btn-toggle-stats-table").addEventListener("click", () => {
  statsShowTable = !statsShowTable;
  el("stats-chart-wrap").style.display = statsShowTable ? "none" : "";
  el("stats-table-wrap").style.display = statsShowTable ? "" : "none";
  el("btn-toggle-stats-table").textContent = statsShowTable ? "Als Chart anzeigen" : "Als Tabelle anzeigen";
});

api("/api/version")
  .then((res) => { el("app-version").textContent = `Version: ${res.version}`; })
  .catch(() => { /* Versionsanzeige ist rein informativ, kein Fehler-Toast noetig */ });

loadAll();
