"use strict";
// Règle : jamais d'innerHTML avec du contenu de mail ou d'IA. Tout passe par h() / textContent.

const $view = document.getElementById("view");
const $title = document.getElementById("title");
const $back = document.getElementById("back");
const $syncState = document.getElementById("sync-state");

const state = {
  status: null,
  category: "",
  accountId: "",
  q: "",
  summary: null,
};

const CAT_LABELS = {
  important: "Important",
  notifications: "Notifications",
  newsletters: "Newsletters",
  promotions: "Promotions",
  factures: "Factures",
  autres: "Autres",
  non_trie: "Non trié",
};

// --- utilitaires --------------------------------------------------------------
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: { "X-Beseder": "1" } };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const r = await fetch(path, init);
  let data = null;
  try { data = await r.json(); } catch { /* vide */ }
  if (!r.ok) throw new Error((data && data.detail) || `Erreur ${r.status}`);
  return data;
}

let toastTimer;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3500);
}

function fmtDate(iso) {
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString())
    return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  if (now - d < 6 * 864e5) return d.toLocaleDateString("fr-FR", { weekday: "short" });
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

function busy(btn, label) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
  return () => { btn.disabled = false; btn.textContent = old; };
}

function setHeader(title, showBack) {
  $title.textContent = title;
  $back.hidden = !showBack;
}

async function refreshStatus() {
  try {
    state.status = await api("/api/status");
    $syncState.textContent = state.status.syncing ? "sync…" : "";
  } catch (e) {
    toast(e.message);
  }
  return state.status;
}

// --- navigation ---------------------------------------------------------------
function go(hash) { location.hash = hash; }
window.addEventListener("hashchange", route);
$back.addEventListener("click", () => history.length > 1 ? history.back() : go("#/"));
document.getElementById("settings").addEventListener("click", () => go("#/reglages"));
document.getElementById("sync").addEventListener("click", async () => {
  try {
    const r = await api("/api/sync", { method: "POST" });
    toast(r.started ? "Synchronisation lancée" : "Synchronisation déjà en cours");
    $syncState.textContent = "sync…";
    setTimeout(() => route(), 4000);
  } catch (e) { toast(e.message); }
});

async function route() {
  const hash = location.hash || "#/";
  const m = hash.match(/^#\/m\/(\d+)$/);
  window.scrollTo(0, 0);
  if (m) return viewMessage(Number(m[1]));
  if (hash === "#/reglages") return viewSettings();
  return viewInbox();
}

// --- boîte de réception -------------------------------------------------------
async function viewInbox() {
  setHeader("Beseder", false);
  const st = await refreshStatus();
  if (!st) return;
  $view.replaceChildren();

  if (st.accounts.length === 0) {
    $view.append(h("div", { class: "card" },
      h("h2", {}, "Bienvenue 👋"),
      h("p", {}, "Ajoute tes boîtes mail et configure une IA dans les réglages."),
      h("button", { class: "btn primary", onclick: () => go("#/reglages") }, "Ouvrir les réglages")));
    return;
  }

  // Boutons IA
  const summaryBtn = h("button", { class: "btn primary", onclick: () => runSummary(summaryBtn) }, "✨ Résumer les non lus");
  const triageToggle = h("input", { type: "checkbox", checked: st.auto_triage, onchange: async (e) => {
    try {
      await api("/api/settings/triage", { method: "PUT", body: { auto: e.target.checked } });
      toast(e.target.checked ? "Tri automatique activé" : "Tri automatique désactivé");
      if (e.target.checked) setTimeout(() => route(), 5000);
    } catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
  } });
  $view.append(h("div", { class: "actions" },
    summaryBtn,
    h("label", { class: "switch" }, triageToggle, h("span", { class: "track" }), "Tri auto")));

  if (!st.ai_configured)
    $view.append(h("p", { class: "note" }, "Aucune IA configurée : le résumé et le tri ne marcheront pas. ",
      h("a", { href: "#/reglages" }, "Configurer")));
  if (st.triage_error) $view.append(h("p", { class: "error" }, "Tri : " + st.triage_error));
  for (const a of st.accounts)
    if (a.last_error) $view.append(h("p", { class: "error" }, `${a.name} : ${a.last_error}`));

  const summaryBox = h("div", { id: "summary" });
  $view.append(summaryBox);
  if (state.summary) renderSummary(summaryBox, state.summary);

  // Catégories
  const counts = st.unread_by_category || {};
  const chip = (key, label) => h("button", {
    class: "chip" + (state.category === key ? " active" : ""),
    onclick: () => { state.category = key; viewInbox(); },
  }, label, counts[key] ? h("span", { class: "count" }, counts[key]) : null);
  const totalUnread = Object.values(counts).reduce((a, b) => a + b, 0);
  $view.append(h("div", { class: "chips" },
    h("button", { class: "chip" + (state.category === "" ? " active" : ""),
      onclick: () => { state.category = ""; viewInbox(); } },
      "Tout", totalUnread ? h("span", { class: "count" }, totalUnread) : null),
    Object.keys(st.categories).map((k) => chip(k, CAT_LABELS[k] || k)),
    counts.non_trie ? chip("non_trie", CAT_LABELS.non_trie) : null));

  // Filtres
  const search = h("input", { type: "search", placeholder: "Rechercher", value: state.q, class: "grow" });
  let t;
  search.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { state.q = search.value; loadList(); }, 300); });
  const accSel = h("select", { onchange: (e) => { state.accountId = e.target.value; loadList(); } },
    h("option", { value: "" }, "Toutes les boîtes"),
    st.accounts.map((a) => h("option", { value: String(a.id) }, a.name)));
  accSel.value = state.accountId;
  $view.append(h("div", { class: "filters" }, search, accSel));

  const list = h("div", { class: "list", id: "list" });
  $view.append(list);
  await loadList();
}

async function loadList(before) {
  const list = document.getElementById("list");
  if (!list) return;
  const params = new URLSearchParams();
  if (state.category) params.set("category", state.category);
  if (state.accountId) params.set("account_id", state.accountId);
  if (state.q) params.set("q", state.q);
  if (before) params.set("before", before);
  let rows;
  try { rows = await api("/api/messages?" + params); } catch (e) { toast(e.message); return; }
  if (!before) list.replaceChildren();
  document.getElementById("more")?.remove();
  if (!before && rows.length === 0) {
    list.append(h("div", { class: "empty" }, state.status?.syncing ? "Synchronisation en cours…" : "Aucun mail ici."));
    return;
  }
  for (const r of rows) {
    list.append(h("div", { class: "item" + (r.seen ? "" : " unread"), onclick: () => go(`#/m/${r.id}`) },
      h("div", { class: "line1" },
        h("span", { class: "from" }, r.from_name || r.from_addr),
        h("span", { class: "muted small" }, fmtDate(r.date))),
      h("div", { class: "subject" },
        r.category ? h("span", { class: "tag" }, CAT_LABELS[r.category] || r.category) : null,
        r.subject || "(sans objet)"),
      h("div", { class: "snippet" }, r.snippet)));
  }
  if (rows.length === 50) {
    const more = h("button", { class: "btn", id: "more", style: "margin:12px auto;display:block",
      onclick: () => loadList(rows[rows.length - 1].date) }, "Plus de mails");
    list.after(more);
  }
}

async function runSummary(btn) {
  const done = busy(btn, "Résumé en cours…");
  try {
    const body = state.accountId ? { account_id: Number(state.accountId) } : {};
    state.summary = await api("/api/summary", { method: "POST", body });
    renderSummary(document.getElementById("summary"), state.summary);
  } catch (e) { toast(e.message); }
  finally { done(); }
}

function renderSummary(box, s) {
  box.replaceChildren(h("div", { class: "card summary" },
    h("div", { class: "row" },
      h("h2", { class: "grow" }, `Résumé de ${s.count} non lu${s.count > 1 ? "s" : ""}`),
      h("button", { class: "icon-btn", "aria-label": "Fermer", onclick: () => { state.summary = null; box.replaceChildren(); } }, "×")),
    h("p", { class: "overview" }, s.overview),
    s.items.map((it) => h("div", { class: "sitem", onclick: () => go(`#/m/${it.id}`) },
      h("div", {}, h("span", { class: "prio " + it.priority }, it.priority), h("b", {}, it.from_name), " — ", it.subject),
      h("div", { class: "muted small" }, it.summary)))));
}

// --- lecture d'un mail --------------------------------------------------------
function emailFrame(html, allowImages) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; img-src data: ${allowImages ? "https: http:" : ""}; font-src data:`;
  const doc = `<!doctype html><html><head><meta charset="utf-8">` +
    `<meta http-equiv="Content-Security-Policy" content="${csp}">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1"><base target="_blank">` +
    `<style>body{margin:12px;font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;color:#16161d;word-wrap:break-word}` +
    `img{max-width:100%;height:auto}table{max-width:100%}</style></head><body>${html}</body></html>`;
  // Pas de allow-scripts : aucun script ne peut tourner, même si le nettoyage ratait quelque chose.
  const frame = h("iframe", { sandbox: "allow-same-origin allow-popups allow-popups-to-escape-sandbox", title: "Contenu du mail" });
  frame.srcdoc = doc;
  frame.addEventListener("load", () => {
    try { frame.style.height = frame.contentDocument.documentElement.scrollHeight + 4 + "px"; } catch { /* ignore */ }
  });
  return frame;
}

async function viewMessage(id) {
  setHeader("", true);
  let m;
  try { m = await api(`/api/messages/${id}`); } catch (e) { toast(e.message); return; }
  if (!state.status) await refreshStatus();
  $title.textContent = m.account_name;
  if (!m.seen) api(`/api/messages/${id}/read`, { method: "POST" }).catch(() => {});

  const catSel = h("select", {},
    h("option", { value: "" }, "— catégorie —"),
    Object.keys(state.status.categories).map((k) => h("option", { value: k }, CAT_LABELS[k] || k)));
  catSel.value = m.category || "";
  const remember = h("input", { type: "checkbox" });
  catSel.addEventListener("change", async () => {
    if (!catSel.value) return;
    try {
      await api(`/api/messages/${id}/category`, { method: "POST", body: { category: catSel.value, remember_sender: remember.checked } });
      toast(remember.checked ? `Règle enregistrée pour ${m.from_addr}` : "Catégorie modifiée");
    } catch (e) { toast(e.message); }
  });

  const bodyBox = h("div", { class: "msg-body" });
  let images = false;
  const imgBtn = h("button", { class: "btn small", onclick: () => {
    images = !images;
    imgBtn.textContent = images ? "Bloquer les images" : "Afficher les images";
    renderBody();
  } }, "Afficher les images");
  function renderBody() {
    bodyBox.replaceChildren(m.body_html ? emailFrame(m.body_html, images) : h("pre", { class: "msg-text" }, m.body_text || m.snippet));
  }
  renderBody();

  const draftBox = h("div");
  $view.replaceChildren(...[
    h("div", { class: "card msg-head" },
      h("h2", {}, m.subject || "(sans objet)"),
      h("div", { class: "meta" }, h("b", {}, m.from_name || m.from_addr), m.from_name ? ` <${m.from_addr}>` : ""),
      h("div", { class: "meta" }, "À : ", m.to_addrs || "—"),
      m.cc_addrs ? h("div", { class: "meta" }, "Cc : ", m.cc_addrs) : null,
      h("div", { class: "meta" }, new Date(m.date).toLocaleString("fr-FR")),
      h("div", { class: "row", style: "margin-top:10px" },
        catSel,
        h("label", { class: "small muted row" }, remember, "toujours pour cet expéditeur"))),
    m.body_html ? h("div", { class: "row", style: "margin-bottom:8px" }, imgBtn,
      h("span", { class: "muted small" }, "Images bloquées par défaut (pixels de suivi).")) : null,
    bodyBox,
    h("div", { class: "actions" },
      h("button", { class: "btn primary", onclick: () => openDraft(m, draftBox) }, "✍️ Rédiger une réponse avec l'IA")),
    draftBox,
  ].filter(Boolean));
}

function openDraft(m, box) {
  const instr = h("input", { type: "text", placeholder: "Consignes (optionnel) : ex. « accepte, propose mardi »" });
  const genBtn = h("button", { class: "btn primary" }, "Générer");
  const out = h("div");
  genBtn.addEventListener("click", async () => {
    const done = busy(genBtn, "Rédaction…");
    try {
      const d = await api(`/api/messages/${m.id}/draft`, { method: "POST", body: { instructions: instr.value } });
      renderDraft(m, d, out);
    } catch (e) { toast(e.message); }
    finally { done(); }
  });
  box.replaceChildren(h("div", { class: "card" },
    h("h2", {}, "Brouillon de réponse"),
    h("div", { class: "row" }, h("div", { class: "grow" }, instr), genBtn),
    out));
  instr.focus();
}

function renderDraft(m, d, out) {
  const ta = h("textarea", {}, d.body);
  ta.value = d.body;
  const addr = (d.to.match(/<([^>]+)>/) || [null, d.to])[1].trim();
  const subject = /^re\s?:/i.test(d.subject) ? d.subject : `Re: ${d.subject}`;
  const saveBtn = h("button", { class: "btn primary" }, "Enregistrer dans Brouillons");
  saveBtn.addEventListener("click", async () => {
    const done = busy(saveBtn, "Enregistrement…");
    try {
      const r = await api(`/api/messages/${m.id}/draft/save`, { method: "POST", body: { body: ta.value } });
      toast(`Brouillon enregistré dans « ${r.folder} ». Envoie-le depuis ta boîte mail.`);
    } catch (e) { toast(e.message); }
    finally { done(); }
  });
  out.replaceChildren(
    h("p", { class: "note" }, "Destinataire : ", d.to, ". Relis avant d'envoyer : rien n'est envoyé automatiquement."),
    ta,
    h("div", { class: "row", style: "margin-top:8px" },
      saveBtn,
      h("button", { class: "btn", onclick: async () => {
        try { await navigator.clipboard.writeText(ta.value); toast("Copié"); } catch { toast("Copie impossible"); }
      } }, "Copier"),
      h("a", { class: "btn", href: "#", onclick: (e) => {
        e.preventDefault();
        location.href = `mailto:${encodeURIComponent(addr)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(ta.value)}`;
      } }, "Ouvrir dans Mail")));
}

// --- réglages -----------------------------------------------------------------
async function viewSettings() {
  setHeader("Réglages", true);
  let ai, accounts, rules, outlook;
  try {
    [ai, accounts, rules, outlook] = await Promise.all([
      api("/api/settings/ai"), api("/api/accounts"), api("/api/rules"), api("/api/settings/outlook"),
    ]);
  } catch (e) { toast(e.message); return; }
  $view.replaceChildren(
    accountsCard(accounts, outlook),
    aiCard(ai),
    profileCard(ai.my_name),
    rulesCard(rules),
  );
}

function field(label, input, hint) {
  return h("label", { class: "field" }, h("span", {}, label), input, hint ? h("div", { class: "muted small" }, hint) : null);
}

function accountsCard(accounts, outlook) {
  const list = accounts.map((a) => h("div", { class: "row", style: "padding:8px 0;border-top:1px solid var(--border)" },
    h("div", { class: "grow" },
      h("div", {}, h("b", {}, a.name), " ", h("span", { class: "tag" }, a.kind)),
      h("div", { class: "muted small" }, a.email, a.last_sync ? ` · sync ${fmtDate(a.last_sync)}` : ""),
      a.last_error ? h("div", { class: "error" }, a.last_error) : null),
    h("button", { class: "btn danger", onclick: async () => {
      if (!confirm(`Retirer ${a.email} de Beseder ? (Rien n'est supprimé dans ta boîte.)`)) return;
      try { await api(`/api/accounts/${a.id}`, { method: "DELETE" }); viewSettings(); } catch (e) { toast(e.message); }
    } }, "Retirer")));

  const form = h("div");
  const kind = h("select", {},
    h("option", { value: "gmail" }, "Gmail"),
    h("option", { value: "icloud" }, "iCloud"),
    h("option", { value: "outlook" }, "Outlook / Hotmail"),
    h("option", { value: "imap" }, "Autre (IMAP)"));
  kind.addEventListener("change", () => renderForm());

  function renderForm() {
    const k = kind.value;
    const email = h("input", { type: "email", autocomplete: "off", placeholder: "toi@exemple.com" });
    const name = h("input", { type: "text", placeholder: "Perso, Pro…" });
    const err = h("div", { class: "error" });
    if (k === "outlook") {
      const clientId = h("input", { type: "text", value: outlook.client_id, placeholder: "xxxxxxxx-xxxx-…" });
      const btn = h("button", { class: "btn primary" }, "Se connecter avec Microsoft");
      const flowBox = h("div");
      btn.addEventListener("click", async () => {
        err.textContent = "";
        try {
          const f = await api("/api/accounts/outlook/start", { method: "POST",
            body: { email: email.value, name: name.value, client_id: clientId.value } });
          flowBox.replaceChildren(h("div", { class: "note" },
            "Ouvre ", h("a", { href: f.verification_uri, target: "_blank", rel: "noopener" }, f.verification_uri),
            " et saisis ce code :", h("div", { class: "code" }, f.user_code), "En attente de validation…"));
          pollOutlook(f.flow_id, f.interval, flowBox);
        } catch (e) { err.textContent = e.message; }
      });
      form.replaceChildren(
        field("Adresse", email), field("Nom affiché", name),
        field("Client ID Azure", clientId, "Une seule fois : crée une « App registration » gratuite sur portal.azure.com (voir README)."),
        btn, err, flowBox);
      return;
    }
    const pwd = h("input", { type: "password", autocomplete: "off" });
    const host = h("input", { type: "text", placeholder: "imap.exemple.com" });
    const port = h("input", { type: "number", value: "993" });
    const user = h("input", { type: "text", placeholder: "(par défaut : l'adresse)" });
    const hints = {
      gmail: ["Mot de passe d'application Gmail : myaccount.google.com/apppasswords (validation en 2 étapes requise).", "https://myaccount.google.com/apppasswords"],
      icloud: ["Mot de passe pour app iCloud : account.apple.com > Connexion et sécurité > Mots de passe pour app.", "https://account.apple.com"],
      imap: ["Mot de passe de la boîte (ou mot de passe d'application si ton fournisseur en propose).", null],
    }[k];
    const btn = h("button", { class: "btn primary" }, "Ajouter");
    btn.addEventListener("click", async () => {
      err.textContent = "";
      const done = busy(btn, "Test de connexion…");
      try {
        await api("/api/accounts", { method: "POST", body: {
          kind: k, email: email.value, name: name.value, password: pwd.value,
          host: host.value, port: Number(port.value) || 993, username: user.value } });
        toast("Compte ajouté, synchronisation lancée");
        viewSettings();
      } catch (e) { err.textContent = e.message; }
      finally { done(); }
    });
    form.replaceChildren(...[
      field("Adresse", email), field("Nom affiché", name),
      k === "imap" && field("Serveur IMAP", host),
      k === "imap" && field("Port", port),
      k === "imap" && field("Identifiant", user),
      field("Mot de passe d'application", pwd, hints[1] ? h("a", { href: hints[1], target: "_blank", rel: "noopener" }, hints[0]) : hints[0]),
      btn, err].filter(Boolean));
  }
  renderForm();

  return h("div", { class: "card" },
    h("h2", {}, "Boîtes mail"),
    accounts.length ? list : h("p", { class: "muted" }, "Aucune boîte pour l'instant."),
    h("h3", {}, "Ajouter une boîte"),
    field("Fournisseur", kind),
    form);
}

async function pollOutlook(flowId, interval, box) {
  for (;;) {
    await new Promise((r) => setTimeout(r, Math.max(interval, 3) * 1000));
    if (!document.body.contains(box)) return;
    let r;
    try { r = await api("/api/accounts/outlook/poll", { method: "POST", body: { flow_id: flowId } }); }
    catch (e) { box.replaceChildren(h("div", { class: "error" }, e.message)); return; }
    if (r.status === "done") { toast("Compte Outlook ajouté"); viewSettings(); return; }
    if (r.status === "error") { box.replaceChildren(h("div", { class: "error" }, r.message)); return; }
  }
}

function aiCard(ai) {
  const preset = h("select", {}, Object.entries(ai.presets).map(([k, p]) => h("option", { value: k }, p.label)));
  preset.value = ai.preset || "openrouter";
  const baseUrl = h("input", { type: "url", value: ai.base_url });
  const apiKey = h("input", { type: "password", autocomplete: "off", placeholder: ai.has_key ? "•••••• (enregistrée, laisse vide pour garder)" : "" });
  const dl = h("datalist", { id: "models" });
  const model = h("input", { type: "text", value: ai.model, list: "models", placeholder: "nom du modèle" });
  const modelFast = h("input", { type: "text", value: ai.model_fast, list: "models", placeholder: "(optionnel) modèle rapide pour le tri" });
  const command = h("input", { type: "text", value: ai.command || "claude" });
  const note = h("p", { class: "note" });
  const err = h("div", { class: "error" });
  const urlField = field("URL de l'API", baseUrl);
  const keyField = field("Clé API", apiKey);
  const cmdField = field("Commande", command, "Chemin du binaire claude sur le Pi.");

  function sync(initial) {
    const p = ai.presets[preset.value];
    note.textContent = p.note || "";
    note.hidden = !p.note;
    const isCli = p.kind === "claude_cli";
    urlField.hidden = p.kind !== "openai_compat";
    keyField.hidden = isCli || (!p.needs_key && preset.value !== "custom");
    cmdField.hidden = !isCli;
    if (!initial || !ai.preset) {
      baseUrl.value = p.base_url || "";
      if (!initial) { model.value = p.model || ""; modelFast.value = p.model_fast || ""; }
      else if (!ai.model) { model.value = p.model || ""; modelFast.value = p.model_fast || ""; }
    }
  }
  preset.addEventListener("change", () => sync(false));
  sync(true);

  const form = () => ({ preset: preset.value, base_url: baseUrl.value, model: model.value,
    model_fast: modelFast.value, api_key: apiKey.value, command: command.value });

  const listBtn = h("button", { class: "btn" }, "Lister les modèles");
  listBtn.addEventListener("click", async () => {
    const done = busy(listBtn, "Chargement…");
    try {
      const r = await api("/api/settings/ai/models", { method: "POST", body: form() });
      dl.replaceChildren(...r.models.map((m) => h("option", { value: m })));
      toast(`${r.models.length} modèles trouvés. Tape dans le champ pour filtrer (ex. « free »).`);
    } catch (e) { err.textContent = e.message; }
    finally { done(); }
  });
  const saveBtn = h("button", { class: "btn primary" }, "Enregistrer");
  saveBtn.addEventListener("click", async () => {
    err.textContent = "";
    try { await api("/api/settings/ai", { method: "PUT", body: form() }); toast("IA enregistrée"); apiKey.value = ""; }
    catch (e) { err.textContent = e.message; }
  });
  const testBtn = h("button", { class: "btn" }, "Tester");
  testBtn.addEventListener("click", async () => {
    err.textContent = "";
    const done = busy(testBtn, "Test…");
    try {
      await api("/api/settings/ai", { method: "PUT", body: form() });
      apiKey.value = "";
      const r = await api("/api/settings/ai/test", { method: "POST" });
      toast(`L'IA répond : « ${r.reply} »`);
    } catch (e) { err.textContent = e.message; }
    finally { done(); }
  });

  return h("div", { class: "card" },
    h("h2", {}, "Intelligence artificielle"),
    h("p", { class: "muted small" }, "L'IA ne peut ni envoyer ni supprimer de mails : elle lit, trie, résume et propose des brouillons quand tu cliques."),
    field("Fournisseur", preset), note, urlField, keyField, cmdField,
    field("Modèle (résumés et brouillons)", model), field("Modèle rapide (tri)", modelFast), dl,
    h("div", { class: "row" }, listBtn, saveBtn, testBtn), err);
}

function profileCard(myName) {
  const name = h("input", { type: "text", value: myName, placeholder: "Prénom Nom" });
  return h("div", { class: "card" },
    h("h2", {}, "Profil"),
    field("Ton nom (pour signer les brouillons)", name),
    h("button", { class: "btn", onclick: async () => {
      try { await api("/api/settings/profile", { method: "PUT", body: { name: name.value } }); toast("Enregistré"); }
      catch (e) { toast(e.message); }
    } }, "Enregistrer"));
}

function rulesCard(rules) {
  return h("div", { class: "card" },
    h("h2", {}, "Règles de tri par expéditeur"),
    h("p", { class: "muted small" }, "Créées quand tu changes la catégorie d'un mail avec « toujours pour cet expéditeur ». Elles passent avant l'IA."),
    rules.length ? rules.map((r) => h("div", { class: "row", style: "padding:6px 0;border-top:1px solid var(--border)" },
      h("span", { class: "grow small" }, r.addr, " → ", h("b", {}, CAT_LABELS[r.category] || r.category)),
      h("button", { class: "btn danger", onclick: async () => {
        try { await api(`/api/rules/${encodeURIComponent(r.addr)}`, { method: "DELETE" }); viewSettings(); } catch (e) { toast(e.message); }
      } }, "Supprimer"))) : h("p", { class: "muted" }, "Aucune règle."));
}

// --- démarrage ----------------------------------------------------------------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
setInterval(async () => {
  if ((location.hash || "#/") === "#/" && document.visibilityState === "visible") {
    const before = state.status?.syncing;
    await refreshStatus();
    if (before && !state.status?.syncing) viewInbox();
  }
}, 15000);
route();
