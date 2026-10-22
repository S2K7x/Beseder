"use strict";
// Rule: never use innerHTML with message or AI content. Everything goes through h() / textContent.

// --- icons (Lucide-style strokes, built as DOM nodes) ---------------------------
const ICONS = {
  logo: [["path", "M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"],
    ["path", "m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"], ["path", "m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"]],
  inbox: [["path", "M22 12h-6l-2 3h-4l-2-3H2"],
    ["path", "M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"]],
  star: [["path", "M12 2.5l2.94 5.96 6.56.95-4.75 4.63 1.12 6.54L12 17.5l-5.87 3.08 1.12-6.54L2.5 9.41l6.56-.95z"]],
  unread: [["path", "M22 13V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v12c0 1.1.9 2 2 2h9"], ["path", "m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"],
    ["circle", 19, 17, 3]],
  sparkles: [["path", "M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.14a.5.5 0 0 1 .96 0l1.58 6.14a2 2 0 0 0 1.44 1.44l6.14 1.58a.5.5 0 0 1 0 .96l-6.14 1.58a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0z"],
    ["path", "M20 3v4"], ["path", "M22 5h-4"]],
  settings: [["path", "M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"],
    ["circle", 12, 12, 3]],
  search: [["circle", 11, 11, 8], ["path", "m21 21-4.3-4.3"]],
  refresh: [["path", "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"], ["path", "M21 3v5h-5"],
    ["path", "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"], ["path", "M8 16H3v5"]],
  arrowUpRight: [["path", "M7 7h10v10"], ["path", "M7 17 17 7"]],
  arrowUp: [["path", "m5 12 7-7 7 7"], ["path", "M12 19V5"]],
  chevronLeft: [["path", "m15 18-6-6 6-6"]],
  reply: [["path", "m9 17-5-5 5-5"], ["path", "M20 18v-2a4 4 0 0 0-4-4H4"]],
  image: [["rect", 3, 3, 18, 18, 2], ["circle", 9, 9, 2], ["path", "m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"]],
  tag: [["path", "M12.59 2.59A2 2 0 0 0 11.17 2H4a2 2 0 0 0-2 2v7.17a2 2 0 0 0 .59 1.42l8.7 8.7a2.43 2.43 0 0 0 3.42 0l6.58-6.58a2.43 2.43 0 0 0 0-3.42z"],
    ["circle", 7.5, 7.5, 0.5]],
  fileText: [["path", "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"], ["path", "M14 2v4a2 2 0 0 0 2 2h4"],
    ["path", "M10 9H8"], ["path", "M16 13H8"], ["path", "M16 17H8"]],
  copy: [["rect", 8, 8, 14, 14, 2], ["path", "M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"]],
  mailOpen: [["path", "M21.2 8.4c.5.38.8.97.8 1.6v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V10a2 2 0 0 1 .8-1.6l8-6a2 2 0 0 1 2.4 0l8 6Z"],
    ["path", "m22 10-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 10"]],
  plus: [["path", "M5 12h14"], ["path", "M12 5v14"]],
  shield: [["path", "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"]],
  bell: [["path", "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"], ["path", "M10.3 21a1.94 1.94 0 0 0 3.4 0"]],
  newspaper: [["path", "M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"],
    ["path", "M18 14h-8"], ["path", "M15 18h-5"], ["path", "M10 6h8v4h-8V6Z"]],
  megaphone: [["path", "m3 11 18-5v12L3 14v-3z"], ["path", "M11.6 16.8a3 3 0 1 1-5.8-1.6"]],
  receipt: [["path", "M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"],
    ["path", "M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"], ["path", "M12 17.5v-11"]],
  folder: [["path", "M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"]],
  help: [["circle", 12, 12, 10], ["path", "M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"], ["path", "M12 17h.01"]],
  at: [["circle", 12, 12, 4], ["path", "M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"]],
  archive: [["rect", 2, 3, 20, 5, 1], ["path", "M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"], ["path", "M10 12h4"]],
  folderMove: [["path", "M2 9V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-1"],
    ["path", "M2 13h10"], ["path", "m9 16 3-3-3-3"]],
  clock: [["circle", 12, 12, 10], ["path", "M12 6v6l4 2"]],
  bellOff: [["path", "M8.7 3A6 6 0 0 1 18 8a21.3 21.3 0 0 0 .6 5"], ["path", "M17 17H3s3-2 3-9a4.67 4.67 0 0 1 .3-1.7"],
    ["path", "M10.3 21a1.94 1.94 0 0 0 3.4 0"], ["path", "m2 2 20 20"]],
  check: [["path", "M20 6 9 17l-5-5"]],
  send: [["path", "m22 2-7 20-4-9-9-4Z"], ["path", "M22 2 11 13"]],
  paperclip: [["path", "m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"]],
};
const SVG_NS = "http://www.w3.org/2000/svg";

function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  for (const [kind, ...a] of ICONS[name] || []) {
    const el = document.createElementNS(SVG_NS, kind);
    if (kind === "path") el.setAttribute("d", a[0]);
    if (kind === "circle") { el.setAttribute("cx", a[0]); el.setAttribute("cy", a[1]); el.setAttribute("r", a[2]); }
    if (kind === "rect") {
      el.setAttribute("x", a[0]); el.setAttribute("y", a[1]); el.setAttribute("width", a[2]);
      el.setAttribute("height", a[3]); el.setAttribute("rx", a[4]);
    }
    svg.append(el);
  }
  return svg;
}

// --- helpers ------------------------------------------------------------------
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
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (id) => document.getElementById(id);
// Like el.append(), but flattens arrays and skips null/false, as h() does.
function put(el, ...children) {
  for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) el.append(c);
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
  try { data = await r.json(); } catch { /* empty body */ }
  if (!r.ok) throw new Error((data && data.detail) || `Error ${r.status}`);
  return data;
}

let toastTimer;
// action = { label, run }: adds a button (e.g. Undo) and keeps the toast a bit longer.
function toast(msg, action) {
  const t = $("toast");
  t.replaceChildren();
  put(t, h("span", {}, msg), action ? h("button", { class: "toast-action", onclick: () => {
    t.hidden = true;
    action.run();
  } }, action.label) : null);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), action ? 7000 : 3800);
}

function fmtSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// --- push notifications --------------------------------------------------------
const isIOS = () => /iPad|iPhone|iPod/.test(navigator.userAgent);
const isInstalled = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function pushHint() {
  if (pushSupported()) return null;
  if (isIOS() && !isInstalled()) return "On iPhone, notifications work once Beseder is on your Home Screen: in Safari, tap Share › Add to Home Screen, then open it from there.";
  return "This browser doesn't support notifications.";
}

async function currentPushSubscription() {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  return reg ? reg.pushManager.getSubscription() : null;
}

async function enablePush() {
  const hint = pushHint();
  if (hint) throw new Error(hint);
  if (await Notification.requestPermission() !== "granted") {
    throw new Error("Notifications are blocked for Beseder. Allow them in your browser or iPhone settings, then try again.");
  }
  const reg = await navigator.serviceWorker.ready;
  const { public_key } = await api("/api/push");
  const key = Uint8Array.from(atob(public_key.replace(/-/g, "+").replace(/_/g, "/") + "==".slice(0, (4 - public_key.length % 4) % 4)), (c) => c.charCodeAt(0));
  let sub = await reg.pushManager.getSubscription();
  if (sub) {
    // A subscription made for another server key (e.g. after a reinstall) must be renewed.
    const old = sub.options?.applicationServerKey ? new Uint8Array(sub.options.applicationServerKey) : null;
    if (old && old.join() !== key.join()) { await sub.unsubscribe(); sub = null; }
  }
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  const label = isIOS() ? "iPhone" : /Android/.test(navigator.userAgent) ? "Android" : "Computer";
  return api("/api/push/subscribe", { method: "POST", body: { subscription: sub.toJSON(), label } });
}

async function disablePush() {
  const sub = await currentPushSubscription();
  if (!sub) return;
  await api("/api/push/unsubscribe", { method: "POST", body: { endpoint: sub.endpoint } });
  await sub.unsubscribe();
}

function busy(btn, label) {
  const old = [...btn.childNodes];
  btn.disabled = true;
  if (label) btn.replaceChildren(label);
  return () => { btn.disabled = false; if (label) btn.replaceChildren(...old); };
}

const sameDay = (a, b) => a.toDateString() === b.toDateString();
function fmtWhen(iso) {
  const d = new Date(iso), now = new Date();
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (sameDay(d, now)) return `Today · ${time}`;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (sameDay(d, y)) return `Yesterday · ${time}`;
  if (now - d < 6 * 864e5) return `${d.toLocaleDateString("en-GB", { weekday: "long" })} · ${time}`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}
const fmtTime = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const fmtDay = (iso) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
function fmtAgo(iso) {
  if (!iso) return "never synced";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  const min = Math.round((Date.now() - d) / 60000);
  if (min < 1) return "synced just now";
  if (min < 60) return `synced ${min} min ago`;
  return `synced ${fmtWhen(d.toISOString()).toLowerCase()}`;
}

function initials(name, email) {
  const src = (name || email || "?").replace(/[^\p{L}\p{N} ]/gu, " ").trim();
  const parts = src.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return (parts[0] || "?").slice(0, 2).toUpperCase();
}
function hue(s) {
  let x = 0;
  for (const c of s || "") x = (x * 31 + c.charCodeAt(0)) % 360;
  return x;
}
function avatarStyle(key) {
  const hh = hue(key);
  return matchMedia("(prefers-color-scheme: dark)").matches
    ? `background:hsl(${hh} 30% 26%);color:hsl(${hh} 70% 82%)`
    : `background:hsl(${hh} 70% 91%);color:hsl(${hh} 45% 32%)`;
}
function avatar(name, email, size = "", kind = null) {
  const el = h("div", { class: `avatar ${size}`, "aria-hidden": "true", style: avatarStyle(email || name) }, initials(name, email));
  if (kind) el.append(h("span", { class: "kind", title: providerOf(kind).label }, providerOf(kind).mark));
  return el;
}
function splitName(name, email) {
  const n = (name || email || "").trim();
  const i = n.indexOf(" ");
  return i > 0 ? [n.slice(0, i), n.slice(i + 1)] : [n, ""];
}

// --- constants -------------------------------------------------------------------
const CATS = {
  important: { label: "Important", icon: "star" },
  notifications: { label: "Notifications", icon: "bell" },
  newsletters: { label: "Newsletters", icon: "newspaper" },
  promotions: { label: "Promotions", icon: "megaphone" },
  receipts: { label: "Receipts", icon: "receipt" },
  other: { label: "Other", icon: "folder" },
  untriaged: { label: "Untriaged", icon: "help" },
};
const providerOf = (kind) => (state.providers || []).find((p) => p.key === kind) || { label: kind, mark: "@" };

const state = {
  status: null,
  summary: null,
  providers: null,
  folders: {},  // account_id -> folders the user can move mail into (cached for the session)
  category: "",
  unread: false,
  accountId: "",
  q: "",
  followups: false,  // list column shows "To reply" / "Waiting for a reply"
  ask: null,         // { question, result } of the last AI search
  selectedId: null,
  view: "inbox",
};

// --- router -----------------------------------------------------------------------
const isPhone = () => matchMedia("(max-width: 860px)").matches;
function go(hash) { if (location.hash !== hash) location.hash = hash; else route(); }
window.addEventListener("hashchange", route);

async function route() {
  const hash = location.hash || "#/";
  const m = hash.match(/^#\/m\/(\d+)$/);
  state.selectedId = m ? Number(m[1]) : null;
  const views = { "#/settings": "settings", "#/brief": "brief", "#/welcome": "welcome" };
  state.view = m ? "message" : views[hash] || "inbox";
  await refreshStatus();
  // First launch: the setup assistant runs until it is finished (or skipped).
  if (state.status && !state.status.onboarded && state.view !== "welcome") return go("#/welcome");
  document.body.dataset.view = state.view;
  $("back").hidden = !(isPhone() && state.view === "message");
  if (isPhone()) window.scrollTo(0, 0);
  renderChrome();
  if (state.view === "settings" || state.view === "welcome") {
    $("settings-col").hidden = false;
    return state.view === "welcome" ? renderWelcome() : renderSettings();
  }
  $("settings-col").hidden = true;
  renderSide();
  renderReader();
  // The list is only rebuilt when the filters change, so selecting an email keeps the scroll position.
  if (!$("list-col").dataset.ready) await renderList();
  else markSelected();
}

async function refreshStatus() {
  try {
    const [st, sum, prov] = await Promise.all([api("/api/status"), state.summary ? null : api("/api/summary/last"),
      state.providers ? null : api("/api/mail/providers")]);
    state.status = st;
    if (prov) state.providers = prov;
    if (sum) state.summary = sum;
    $("sync-state").textContent = st.syncing ? "Syncing…" : "";
  } catch (e) { toast(e.message); }
  return state.status;
}

// --- chrome: rail, tabs, filters ------------------------------------------------------
function navItems() {
  const counts = state.status?.unread_by_category || {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const listView = state.view === "inbox" || state.view === "message";
  const follow = state.status?.followups || {};
  const list = (f) => () => { Object.assign(state, { category: "", unread: false, followups: false, ask: null }, f); navigateList(); };
  const plain = listView && !state.followups && !state.ask;
  return [
    { icon: "inbox", label: "Inbox", badge: total, active: plain && !state.category && !state.unread, go: list({}) },
    { icon: "star", label: "Important", badge: counts.important, active: plain && state.category === "important",
      go: list({ category: "important" }) },
    { icon: "unread", label: "Unread", active: plain && state.unread && !state.category, go: list({ unread: true }) },
    { icon: "clock", label: "Follow-ups", badge: follow.to_reply, active: listView && state.followups, go: list({ followups: true }) },
    { icon: "sparkles", label: "Brief", active: state.view === "brief", go: () => go("#/brief") },
  ];
}

function navigateList() {
  $("list-col").dataset.ready = "";
  if (isPhone() || state.view === "settings" || state.view === "brief") go("#/");
  else route();
}

function renderChrome() {
  const items = navItems();
  $("rail-nav").replaceChildren(...items.map((it) => {
    const b = h("button", { class: "round" + (it.active ? " active" : ""), title: it.label, "aria-label": it.label, onclick: it.go },
      icon(it.icon));
    if (it.badge) b.append(h("span", { class: "badge" }, it.badge > 99 ? "99+" : it.badge));
    return b;
  }));
  $("rail-settings").classList.toggle("active", state.view === "settings");

  const tabs = [items[0], items[3], items[4],
    { icon: "settings", label: "Settings", active: state.view === "settings", go: () => go("#/settings") }];
  $("tabbar").replaceChildren(...tabs.map((it) => h("a", { href: "#", class: it.active ? "active" : "",
    onclick: (e) => { e.preventDefault(); it.go(); } }, icon(it.icon), it.label,
    it.badge ? h("span", { class: "badge" }, it.badge > 99 ? "99+" : it.badge) : null)));

  const sel = $("account-filter");
  const accounts = state.status?.accounts || [];
  sel.replaceChildren(h("option", { value: "" }, "All"), ...accounts.map((a) => h("option", { value: String(a.id) }, a.name)));
  sel.value = state.accountId;
  sel.hidden = accounts.length < 2;

  const me = state.status?.my_name || "Me";
  $("me").textContent = initials(me);
  $("me").style.cssText = avatarStyle(me);
  $("me").title = me;
}

// --- list column --------------------------------------------------------------------
async function renderList(before, beforeId) {
  const col = $("list-col");
  const st = state.status;
  if (!st) return;
  if (state.followups && !before) return renderFollowups(col);
  if (state.ask && !before) return renderAsk(col);
  if (!before) {
    col.dataset.ready = "1";
    const counts = st.unread_by_category || {};
    const chip = (key, label) => h("button", {
      class: "chip" + (state.category === key ? " active" : ""),
      onclick: () => { state.category = state.category === key ? "" : key; navigateList(); },
    }, label, counts[key] ? h("span", { class: "count" }, counts[key]) : null);
    col.replaceChildren(
      miniBrief(),
      h("div", { class: "chips" },
        h("button", { class: "chip" + (!state.category ? " active" : ""), onclick: () => { state.category = ""; navigateList(); } },
          state.unread ? "All unread" : "All"),
        Object.keys(st.categories).map((k) => chip(k, CATS[k]?.label || k)),
        counts.untriaged ? chip("untriaged", CATS.untriaged.label) : null),
      h("div", { id: "cards", style: "display:flex;flex-direction:column;gap:12px" }));
  }
  if (!st.accounts.length) {
    $("cards").replaceChildren(h("div", { class: "card empty" }, h("div", { class: "big" }, icon("inbox")),
      h("p", {}, "No mailbox yet."), h("button", { class: "pill dark sm", onclick: () => go("#/settings") }, "Add a mailbox")));
    return;
  }
  const params = new URLSearchParams();
  if (state.category) params.set("category", state.category);
  if (state.accountId) params.set("account_id", state.accountId);
  if (state.unread) params.set("unread", "true");
  if (state.q) params.set("q", state.q);
  if (before) { params.set("before", before); params.set("before_id", beforeId); }
  let rows;
  try { rows = await api("/api/messages?" + params); } catch (e) { toast(e.message); return; }
  const cards = $("cards");
  $("more")?.remove();
  if (!before && rows.length === 0) {
    cards.replaceChildren(h("div", { class: "card empty" }, h("div", { class: "big" }, icon("inbox")),
      st.syncing ? "Syncing your mailboxes…" : state.q ? "No match." : "Nothing here. Enjoy the quiet."));
    return;
  }
  const prio = priorityMap();
  for (const r of rows) cards.append(mailCard(r, prio[r.id]));
  if (rows.length === 50) {
    cards.after(h("button", { class: "pill more", id: "more", onclick: () => renderList(rows[rows.length - 1].date, rows[rows.length - 1].id) }, "Load more"));
  }
  markSelected();
}

// --- follow-ups -------------------------------------------------------------------------
async function renderFollowups(col) {
  col.dataset.ready = "1";
  const st = state.status;
  const head = h("div", { class: "card list-head" }, h("h2", {}, icon("clock"), "Follow-ups"),
    h("p", { class: "muted small" }, "Emails waiting for your answer, and what you sent that hasn't been answered yet."));
  col.replaceChildren(head, h("div", { class: "card empty" }, "Loading…"));
  let f;
  try { f = await api("/api/followups"); } catch (e) { toast(e.message); return; }
  if (!state.followups) return;
  const done = (kind, id, card) => async (e) => {
    e.stopPropagation();
    try {
      await api("/api/followups/done", { method: "POST", body: { kind, id } });
      card.remove();
      toast("Done");
      refreshStatus().then(() => { renderChrome(); renderSide(); });
    } catch (err) { toast(err.message); }
  };
  const toReply = f.to_reply.map((r) => {
    const card = mailCard(r);
    card.append(h("div", { class: "card-actions" },
      h("button", { class: "pill sm", onclick: (e) => { e.stopPropagation(); go(`#/m/${r.id}`); } }, icon("reply"), "Reply"),
      h("button", { class: "pill sm", onclick: done("reply", r.id, card) }, icon("check"), "Done")));
    return card;
  });
  const waiting = f.waiting.map((w) => {
    const days = Math.max(1, Math.round((Date.now() - new Date(w.date)) / 864e5));
    const subject = /^re\s?:/i.test(w.subject) ? w.subject : `Re: ${w.subject}`;
    const card = h("article", { class: "card mail-card sent-card" },
      h("div", { class: "who" }, avatar(w.to_name, w.to_addr),
        h("div", { class: "who-name" }, h("span", {}, `To ${w.to_name || w.to_addr}`), h("span", {}, `${days} days without an answer`))),
      h("h3", {}, w.subject || "(no subject)"),
      w.snippet ? h("div", { class: "snippet" }, w.snippet) : null);
    card.append(h("div", { class: "card-actions" },
      h("a", { class: "pill sm", href: `mailto:${encodeURIComponent(w.to_addr)}?subject=${encodeURIComponent(subject)}` },
        icon("send"), "Nudge"),
      h("button", { class: "pill sm", onclick: done("waiting", w.id, card) }, icon("check"), "Done")));
    return card;
  });
  const section = (title, sub, cards, empty) => [h("div", { class: "section-title" }, title, h("span", { class: "muted" }, ` · ${sub}`)),
    cards.length ? cards : h("div", { class: "card empty small" }, empty)];
  col.replaceChildren();
  put(col, head,
    section("To reply", `${f.to_reply.length}`, toReply,
      st.ai_configured ? (st.auto_triage ? "Nothing waiting for your answer." : "Turn on auto-triage so the AI can spot emails that need an answer.")
        : "Connect an AI so it can spot emails that need an answer."),
    section("Waiting for a reply", `${f.waiting.length}`, waiting, "No one owes you an answer."));
}

// --- AI search ----------------------------------------------------------------------------
async function runAsk(question) {
  if (!question) return toast("Type a question in the search box, then tap ✨");
  const btn = $("ask");
  const done = busy(btn);
  Object.assign(state, { followups: false, ask: { question, result: null } });
  if (isPhone() && state.view !== "inbox") go("#/");
  renderList();
  try {
    const result = await api("/api/search/ask", { method: "POST",
      body: { question, account_id: state.accountId ? Number(state.accountId) : null } });
    if (state.ask?.question === question) { state.ask.result = result; renderList(); }
  } catch (e) { toast(e.message); state.ask = null; renderList(); }
  finally { done(); }
}

function renderAsk(col) {
  col.dataset.ready = "1";
  const { question, result } = state.ask;
  const close = h("button", { class: "round xs", title: "Back to the inbox", "aria-label": "Close",
    onclick: () => { state.ask = null; navigateList(); } }, icon("chevronLeft"));
  const head = h("div", { class: "card ask-card" },
    h("div", { class: "card-head" }, h("h2", {}, icon("sparkles"), "Ask your mail"), close),
    h("p", { class: "q" }, question));
  if (!result) {
    put(head, h("p", { class: "muted small" }, "Searching…"));
    return col.replaceChildren(head);
  }
  if (result.answer) put(head, h("p", { class: "overview" }, result.answer));
  put(head, h("p", { class: "muted small", style: "margin:0" }, !result.items.length ? "No email matches."
    : result.loose ? "No exact answer: here are the closest emails." : `${result.items.length} email${result.items.length === 1 ? "" : "s"} found`));
  col.replaceChildren(head, h("div", { id: "cards", style: "display:flex;flex-direction:column;gap:12px" },
    result.items.map((r) => mailCard(r))));
  markSelected();
}

function priorityMap() {
  const map = {};
  for (const it of state.summary?.items || []) map[it.id] = it.priority;
  return map;
}

function mailCard(r, priority) {
  const [first, last] = splitName(r.from_name, r.from_addr);
  return h("article", {
    class: "card mail-card" + (r.seen ? "" : " unread"), "data-id": r.id, tabindex: "0",
    onclick: () => go(`#/m/${r.id}`),
    onkeydown: (e) => { if (e.key === "Enter") go(`#/m/${r.id}`); },
  },
    h("div", { class: "who" },
      avatar(r.from_name, r.from_addr),
      h("div", { class: "who-name" }, h("span", {}, first), h("span", {}, last || r.account_name)),
      h("span", { class: "round xs", "aria-hidden": "true" }, icon("arrowUpRight"))),
    h("h3", {}, r.subject || "(no subject)"),
    h("div", { class: "when" }, fmtWhen(r.date), state.status.accounts.length > 1 && last ? ` · ${r.account_name}` : ""),
    r.snippet ? h("div", { class: "snippet" }, r.snippet) : null,
    (r.category || priority === "high") ? h("div", { class: "tags" },
      priority === "high" ? h("span", { class: "tag high" }, "High priority") : null,
      r.category ? h("span", { class: "tag" }, CATS[r.category]?.label || r.category) : null) : null);
}

function markSelected() {
  document.querySelectorAll(".mail-card").forEach((c) => c.classList.toggle("selected", Number(c.dataset.id) === state.selectedId));
}

// Medium screens hide the side column: keep the essentials at the top of the list.
function miniBrief() {
  return h("div", { class: "card mini-brief", style: "padding:12px 14px 12px 18px;align-items:center;gap:10px" },
    triageSwitch(state.status.auto_triage),
    h("span", { style: "flex:1" }),
    h("button", { class: "pill sm", onclick: () => go("#/brief") }, icon("sparkles"), "Brief"));
}

// --- reader column ------------------------------------------------------------------
function renderReader() {
  const col = $("reader-col");
  if (state.selectedId) return renderMessage(col, state.selectedId);
  col.replaceChildren(briefHome());
}

function greeting() {
  const hr = new Date().getHours();
  const part = hr < 5 ? "Good night" : hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
  const name = (state.status?.my_name || "").split(" ")[0];
  return name ? `${part}, ${name}` : part;
}

function briefHome() {
  const st = state.status;
  const s = state.summary;
  const card = h("div", { class: "card brief" });
  if (!st?.accounts.length) {
    put(card, h("p", { class: "hello" }, "Welcome to Beseder 👋"),
      h("p", { class: "overview" }, "Add your mailboxes and connect an AI. It sorts your mail, briefs you on what's unread and drafts replies when you ask. It can never send or delete anything."),
      h("div", { class: "btns" }, h("button", { class: "pill dark", onclick: () => go("#/settings") }, icon("plus"), "Get started")));
    return card;
  }
  const unread = Object.values(st.unread_by_category || {}).reduce((a, b) => a + b, 0);
  const n = st.accounts.length;
  const btn = h("button", { class: "pill dark", onclick: () => runSummary(btn) }, icon("sparkles"), s ? "Refresh brief" : "Summarize unread");
  put(card, 
    h("p", { class: "hello" }, greeting()),
    h("p", { class: "muted", style: "margin:4px 0 0" },
      `${unread} unread email${unread === 1 ? "" : "s"} across ${n} mailbox${n === 1 ? "" : "es"}.`),
    !st.ai_configured ? h("div", { class: "notice" }, "No AI connected yet. ", h("a", { href: "#/settings" }, "Set one up"),
      " to get briefs and auto-triage.") : null);
  if (s) {
    put(card, 
      h("p", { class: "overview" }, s.overview),
      h("div", { class: "small muted" }, `Brief of ${s.count} unread · ${fmtWhen(s.generated_at).toLowerCase()}`),
      s.items.map((it) => h("div", { class: "brief-item", onclick: () => go(`#/m/${it.id}`) },
        avatar(it.from_name, it.from_addr || it.from_name, "sm"),
        h("div", { class: "grow" },
          h("div", { class: "t" }, it.from_name, h("span", { class: "muted", style: "font-weight:400" }, " · ", it.subject)),
          h("div", { class: "s" }, it.summary)),
        h("span", { class: "tag" + (it.priority === "high" ? " high" : "") }, it.priority))));
  } else {
    put(card, h("p", { class: "overview muted" }, "Tap the button and your AI will read your unread emails and tell you what matters."));
  }
  put(card, h("div", { class: "btns" }, btn));
  return card;
}

async function runSummary(btn) {
  const done = btn ? busy(btn, "Reading your emails…") : null;
  const doneTop = busy($("summarize"));
  try {
    const body = state.accountId ? { account_id: Number(state.accountId) } : {};
    state.summary = await api("/api/summary", { method: "POST", body });
    toast("Your brief is ready");
    $("list-col").dataset.ready = "";
    if (isPhone()) go("#/brief");
    else if (state.view === "message" || state.view === "settings") { if (state.view === "settings") go("#/"); else { renderSide(); renderList(); } }
    else route();
  } catch (e) { toast(e.message); }
  finally { if (done) done(); doneTop(); }
}

async function renderMessage(col, id) {
  let m;
  try { m = await api(`/api/messages/${id}`); } catch (e) {
    col.replaceChildren(h("div", { class: "card empty" }, e.message));
    return;
  }
  if (state.selectedId !== id) return;
  if (!m.seen) {
    api(`/api/messages/${id}/read`, { method: "POST" }).then(() => {
      document.querySelector(`.mail-card[data-id="${id}"]`)?.classList.remove("unread");
    }).catch(() => {});
  }
  const account = state.status.accounts.find((a) => a.id === m.account_id);

  // Category picker: takes the place of the mockup's "Mark as spam" pill.
  const catSel = h("select", { "aria-label": "Category" },
    h("option", { value: "" }, "No category"),
    Object.keys(state.status.categories).map((k) => h("option", { value: k }, CATS[k]?.label || k)));
  catSel.value = m.category || "";
  catSel.addEventListener("change", async () => {
    if (!catSel.value) return;
    try {
      await api(`/api/messages/${id}/category`, { method: "POST", body: { category: catSel.value, remember_sender: false } });
      toast(`Moved to ${CATS[catSel.value].label}`);
      await refreshStatus();
      renderSide(); renderChrome();
    } catch (e) { toast(e.message); }
  });

  let images = false, plain = !m.body_html;
  const bodyBox = h("div", { class: "body" });
  const loadFull = h("button", { class: "pill sm", onclick: async () => {
    const done = busy(loadFull, "Loading the full email…");
    try { await api(`/api/messages/${id}/load-full`, { method: "POST" }); renderMessage(col, id); }
    catch (e) { toast(e.message); done(); }
  } }, "Load the full email");
  const renderBody = () => bodyBox.replaceChildren(
    m.truncated ? h("div", { class: "notice" }, "This email is large, so only its headers were imported. ", loadFull) : "",
    !plain ? emailFrame(m.body_html, images) : h("pre", { class: "text" }, m.body_text || m.snippet));
  renderBody();

  const imgBtn = h("button", { class: "round sm", title: "Show remote images (trackers are blocked by default)",
    "aria-label": "Show images", hidden: !m.body_html,
    onclick: () => { images = !images; imgBtn.classList.toggle("on", images); renderBody(); } }, icon("image"));
  const textBtn = h("button", { class: "round sm", title: "Plain text version", "aria-label": "Plain text", hidden: !m.body_html,
    onclick: () => { plain = !plain; textBtn.classList.toggle("on", plain); renderBody(); } }, icon("fileText"));
  const ruleBtn = h("button", { class: "round sm", title: "Always file this sender in this category", "aria-label": "Sender rule",
    onclick: async () => {
      if (!catSel.value) return toast("Pick a category first");
      try {
        await api(`/api/messages/${id}/category`, { method: "POST", body: { category: catSel.value, remember_sender: true } });
        toast(`Everything from ${m.from_addr} now goes to ${CATS[catSel.value].label}`);
        ruleBtn.classList.add("on");
        await refreshStatus();
        $("list-col").dataset.ready = "";
        renderSide(); renderList();
      } catch (e) { toast(e.message); }
    } }, icon("tag"));

  const composer = buildComposer(m);
  const movePicker = h("div", { class: "move-picker", hidden: true });
  const archiveBtn = h("button", { class: "round sm", title: "Archive (out of the inbox, not deleted)", "aria-label": "Archive",
    onclick: () => moveMessage(m, null, archiveBtn) }, icon("archive"));
  const moveBtn = h("button", { class: "round sm", title: "Move to a folder", "aria-label": "Move to a folder",
    onclick: async () => {
      if (!movePicker.hidden) { movePicker.hidden = true; return; }
      movePicker.hidden = false;
      movePicker.replaceChildren(h("span", { class: "small muted" }, "Loading folders…"));
      try {
        const f = state.folders[m.account_id] ||= await api(`/api/accounts/${m.account_id}/folders`);
        const sel = h("select", { "aria-label": "Folder" }, h("option", { value: "" }, "Move to…"),
          f.folders.map((name) => h("option", { value: name }, name)));
        sel.addEventListener("change", () => { if (sel.value) moveMessage(m, sel.value, moveBtn); });
        movePicker.replaceChildren(h("label", { class: "select-pill" }, icon("folderMove"), sel));
        sel.focus();
      } catch (e) { movePicker.replaceChildren(h("span", { class: "error" }, e.message)); }
    } }, icon("folderMove"));
  const files = (m.attachments || []).length ? h("div", { class: "attachments" }, m.attachments.map((a) =>
    h("a", { class: "attachment", href: `/api/messages/${m.id}/attachments/${a.idx}`, download: a.filename, title: a.filename },
      h("span", { class: "ico" }, icon("paperclip")),
      h("span", { class: "grow" }, h("span", { class: "t" }, a.filename), h("span", { class: "s" }, fmtSize(a.size)))))) : null;
  const replyBtn = h("button", { class: "pill", onclick: () => composer.draft() }, icon("reply"), "Reply with AI");
  const unsubBtn = m.unsub_url || m.unsub_mailto ? h("button", { class: "round sm",
    title: m.unsub_one_click ? "Unsubscribe in one tap" : "Unsubscribe", "aria-label": "Unsubscribe",
    onclick: () => unsubscribe(m, unsubBtn) }, icon("bellOff")) : null;

  col.replaceChildren(h("div", { class: "card reader" },
    h("div", { class: "reader-top" },
      h("label", { class: "select-pill" }, icon("tag"), catSel),
      h("span", { class: "date" }, new Date(m.date).toLocaleString("en-GB",
        { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }))),
    h("div", { class: "person" },
      avatar(m.from_name, m.from_addr, "lg", account?.kind),
      h("h2", {}, m.from_name || m.from_addr),
      h("div", { class: "sub" }, m.from_name ? `${m.from_addr} · ` : "", `to ${m.account_name}`),
      h("div", { class: "subject" }, m.subject || "(no subject)")),
    h("div", { class: "actions-row" }, replyBtn, archiveBtn, moveBtn, unsubBtn, ruleBtn, imgBtn, textBtn),
    m.needs_reply && !m.answered && !m.followup_done ? h("div", { class: "small muted reply-hint" }, icon("clock"),
      "The AI thinks this email expects an answer from you.") : null,
    movePicker,
    bodyBox,
    files,
    composer.el));
  markSelected();
}

// Archive (folder = null) or move to a folder. The card disappears, the next email opens,
// and the toast offers to undo.
async function moveMessage(m, folder, btn) {
  const done = busy(btn);
  let r;
  try {
    r = await api(`/api/messages/${m.id}/move`, { method: "POST", body: { folder } });
  } catch (e) { toast(e.message); done(); return; }
  done();
  const card = document.querySelector(`.mail-card[data-id="${m.id}"]`);
  const next = card?.nextElementSibling?.dataset?.id || card?.previousElementSibling?.dataset?.id;
  card?.remove();
  const undo = r.message_id && r.folder ? { label: "Undo", run: async () => {
    try {
      await api(`/api/accounts/${r.account_id}/restore`, { method: "POST", body: { folder: r.folder, message_id: r.message_id } });
      toast("Back in your inbox");
      setTimeout(() => { $("list-col").dataset.ready = ""; route(); }, 2500);
    } catch (e) { toast(e.message); }
  } } : null;
  toast(folder ? `Moved to ${r.folder}` : "Archived", undo);
  refreshStatus().then(() => { renderChrome(); renderSide(); });
  go(!isPhone() && next ? `#/m/${next}` : "#/");
}

// One tap when the sender supports it (RFC 8058); otherwise their page (or a pre-filled
// email in your mail app) opens. Then offers to archive everything they sent.
async function unsubscribe(m, btn) {
  const done = busy(btn);
  let r;
  try { r = await api(`/api/messages/${m.id}/unsubscribe`, { method: "POST" }); }
  catch (e) { toast(e.message); done(); return; }
  done();
  if (!r.done) {
    if (r.open.startsWith("mailto:")) location.href = r.open;
    else window.open(r.open, "_blank", "noopener,noreferrer");
  } else btn.classList.add("on");
  toast(r.done ? `Unsubscribed from ${r.sender}` : "Finish on the sender's page", { label: "Archive all from them", run: () => archiveSender(r.sender) });
}

async function archiveSender(addr) {
  let r;
  try { r = await api("/api/senders/archive", { method: "POST", body: { addr } }); } catch (e) { toast(e.message); return; }
  const undo = r.moved.some((x) => x.folder && x.message_ids.length) ? { label: "Undo", run: async () => {
    try {
      for (const x of r.moved) {
        if (x.folder && x.message_ids.length) {
          await api(`/api/accounts/${x.account_id}/restore`, { method: "POST", body: { folder: x.folder, message_ids: x.message_ids } });
        }
      }
      toast("Back in your inbox");
      setTimeout(() => { $("list-col").dataset.ready = ""; route(); }, 2500);
    } catch (e) { toast(e.message); }
  } } : null;
  toast(`${r.count} email${r.count === 1 ? "" : "s"} archived`, undo);
  $("list-col").dataset.ready = "";
  go("#/");
}

function emailFrame(html, allowImages) {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const csp = `default-src 'none'; style-src 'unsafe-inline'; img-src data: ${allowImages ? "https: http:" : ""}; font-src data:`;
  const doc = `<!doctype html><html><head><meta charset="utf-8">` +
    `<meta http-equiv="Content-Security-Policy" content="${csp}">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1"><base target="_blank">` +
    `<style>html{color-scheme:light}body{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;` +
    `color:#121216;word-wrap:break-word;${dark ? "background:#fff;padding:16px;border-radius:16px" : ""}}` +
    `img{max-width:100%;height:auto}table{max-width:100%!important}</style></head><body>${html}</body></html>`;
  // No allow-scripts: no script can run, even if sanitizing missed something.
  const frame = h("iframe", { sandbox: "allow-same-origin allow-popups allow-popups-to-escape-sandbox", title: "Email content" });
  frame.srcdoc = doc;
  const fit = () => { try { frame.style.height = frame.contentDocument.documentElement.scrollHeight + 4 + "px"; } catch { /* ignore */ } };
  frame.addEventListener("load", () => { fit(); setTimeout(fit, 400); });
  return frame;
}

// The reply box of the mockup: you write, or you tell the AI what to say and tap ✨.
// The dark arrow saves to the Drafts folder. Nothing is ever sent from here.
function buildComposer(m) {
  const ta = h("textarea", { rows: "2", placeholder: "Write a reply, or tell the AI what to say (\"accept, suggest Tuesday\") and tap ✨" });
  const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };
  ta.addEventListener("input", grow);
  const to = h("div", { class: "small muted", hidden: true });
  let lastInstructions = "";
  let lastDraft = null;

  const aiBtn = h("button", { class: "round xs", title: "Draft with AI", "aria-label": "Draft with AI" }, icon("sparkles"));
  async function draft() {
    ta.focus();
    // Unchanged draft (or empty box): regenerate with the same instructions. Otherwise the box is the new instruction.
    const instructions = ta.value === lastDraft || !ta.value.trim() ? lastInstructions : ta.value;
    const done = busy(aiBtn);
    const prev = ta.value;
    ta.value = "Writing a draft…";
    ta.disabled = true;
    try {
      const d = await api(`/api/messages/${m.id}/draft`, { method: "POST", body: { instructions } });
      lastInstructions = instructions;
      lastDraft = d.body;
      ta.value = d.body;
      to.hidden = false;
      to.textContent = `To ${d.to}. Review it: nothing is sent automatically.`;
    } catch (e) { ta.value = prev; toast(e.message); }
    finally { ta.disabled = false; done(); grow(); }
  }
  aiBtn.addEventListener("click", draft);

  const copyBtn = h("button", { class: "round xs", title: "Copy", "aria-label": "Copy", onclick: async () => {
    try { await navigator.clipboard.writeText(ta.value); toast("Copied"); } catch { toast("Cannot copy here"); }
  } }, icon("copy"));
  const mailBtn = h("button", { class: "round xs", title: "Open in your mail app", "aria-label": "Open in mail app", onclick: () => {
    const addr = ((m.reply_to_display || "").match(/<([^>]+)>/) || [null, m.reply_to_display || m.from_addr])[1].trim();
    const subject = /^re\s?:/i.test(m.subject || "") ? m.subject : `Re: ${m.subject || ""}`;
    location.href = `mailto:${encodeURIComponent(addr)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(ta.value)}`;
  } }, icon("mailOpen"));
  const saveBtn = h("button", { class: "round dark send", title: "Save to Drafts (not sent)", "aria-label": "Save to Drafts" }, icon("arrowUp"));
  saveBtn.addEventListener("click", async () => {
    if (!ta.value.trim()) return toast("Write something first, or tap ✨");
    const done = busy(saveBtn);
    try {
      const r = await api(`/api/messages/${m.id}/draft/save`, { method: "POST", body: { body: ta.value } });
      toast(`Saved in "${r.folder}". Send it from your mail app when ready.`);
    } catch (e) { toast(e.message); }
    finally { done(); }
  });

  const el = h("div", { class: "composer" }, to, ta,
    h("div", { class: "bar" }, aiBtn, copyBtn, mailBtn, h("span", { class: "hint" }, "Saved to Drafts, never sent"), saveBtn));
  return { el, draft };
}

// --- side column ----------------------------------------------------------------------
function renderSide() {
  if (!state.status) return;
  $("side-col").replaceChildren(briefWidget(), followupsWidget(), triageWidget(), mailboxesWidget());
}

function briefWidget() {
  const s = state.summary;
  const items = (s?.items || []).slice(0, 2);
  const card = h("div", { class: "card brief-widget" },
    h("div", { class: "card-head" }, h("h2", {}, icon("sparkles"), "AI brief"),
      h("button", { class: "round xs", title: "Open the brief", "aria-label": "Open the brief", onclick: () => go(isPhone() ? "#/brief" : "#/") },
        icon("arrowUpRight"))));
  if (!items.length) {
    put(card, h("p", { class: "muted small", style: "margin:0" },
      s ? s.overview : "Tap “Summarize unread” and your AI will tell you what matters."));
  } else {
    put(card, h("div", { class: "tiles" }, items.map((it) => {
      const when = it.date || s.generated_at;
      return h("div", { class: "tile", onclick: () => go(`#/m/${it.id}`) },
        h("div", { class: "row1" }, avatar(it.from_name, it.from_addr || it.from_name, "sm"),
          it.priority === "high" ? h("span", { class: "tag high" }, "High") : h("span", { class: "day" }, fmtDay(when))),
        h("div", { class: "time" }, fmtTime(when)),
        h("div", { class: "label" }, it.summary || it.subject));
    })));
  }
  put(card, h("div", { class: "card-foot" },
    h("button", { class: "link", onclick: () => go(isPhone() ? "#/brief" : "#/") }, "View full brief"),
    s ? h("span", { class: "small" }, fmtWhen(s.generated_at)) : null));
  return card;
}

function followupsWidget() {
  const f = state.status.followups || { to_reply: 0, waiting: 0 };
  const open = () => { Object.assign(state, { followups: true, category: "", unread: false, ask: null }); navigateList(); };
  const row = (ic, title, sub, n) => h("div", { class: "row-item clickable", onclick: open },
    h("span", { class: "ico" }, icon(ic)),
    h("div", { class: "grow" }, h("div", { class: "t" }, title), h("div", { class: "s" }, sub)),
    n ? h("span", { class: "tag" + (ic === "reply" ? " dark" : "") }, n) : null);
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, icon("clock"), "Follow-ups"),
      h("button", { class: "round xs", title: "Open follow-ups", "aria-label": "Open follow-ups", onclick: open }, icon("arrowUpRight"))),
    row("reply", "To reply", f.to_reply ? "People waiting for your answer" : "You're all caught up", f.to_reply),
    row("send", "Waiting for a reply", f.waiting ? "Sent, no answer after 2 days" : "No one owes you an answer", f.waiting));
}

function triageSwitch(on) {
  const input = h("input", { type: "checkbox", checked: on, onchange: async (e) => {
    try {
      await api("/api/settings/triage", { method: "PUT", body: { auto: e.target.checked } });
      toast(e.target.checked ? "Auto-triage on: new mail gets sorted for you" : "Auto-triage off");
      if (e.target.checked) {
        setTimeout(async () => { await refreshStatus(); $("list-col").dataset.ready = ""; renderSide(); renderList(); }, 4000);
      }
    } catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
  } });
  return h("label", { class: "switch", title: "Auto-triage" }, input, h("span", { class: "track" }), h("span", { class: "small" }, "Auto-triage"));
}

function triageWidget() {
  const st = state.status;
  const counts = st.unread_by_category || {};
  const keys = [...Object.keys(st.categories), ...(counts.untriaged ? ["untriaged"] : [])];
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, icon("tag"), "Categories"), triageSwitch(st.auto_triage)),
    st.triage_error ? h("div", { class: "error" }, st.triage_error) : null,
    keys.map((k) => h("div", { class: "row-item clickable", onclick: () => {
      Object.assign(state, { category: k, unread: false, followups: false, ask: null }); navigateList();
    } },
      h("span", { class: "ico" }, icon(CATS[k]?.icon || "folder")),
      h("div", { class: "grow" }, h("div", { class: "t" }, CATS[k]?.label || k),
        h("div", { class: "s" }, st.categories[k] || "Waiting for the AI")),
      counts[k] ? h("span", { class: "tag" + (k === "important" ? " dark" : "") }, `${counts[k]} unread`) : null)),
    h("div", { class: "card-foot" }, h("span", { class: "small" },
      st.auto_triage ? "New mail is sorted automatically" : "Turn on to let the AI sort new mail")));
}

function mailboxesWidget() {
  const st = state.status;
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, icon("at"), "Mailboxes"),
      h("button", { class: "round xs", title: "Add a mailbox", "aria-label": "Add a mailbox", onclick: () => go("#/settings") }, icon("plus"))),
    st.accounts.length ? st.accounts.map((a) => h("div", { class: "row-item clickable", onclick: () => {
      state.accountId = state.accountId === String(a.id) ? "" : String(a.id);
      navigateList();
    } },
      avatar(a.name, a.email, "sm"),
      h("div", { class: "grow" },
        h("div", { class: "t" }, a.name, h("span", { class: "muted", style: "font-weight:400" }, ` · ${providerOf(a.kind).label}`)),
        a.last_error ? h("div", { class: "s error" }, a.last_error) : h("div", { class: "s" }, `${a.email} · ${fmtAgo(a.last_sync)}`)),
      a.unread ? h("span", { class: "tag" + (state.accountId === String(a.id) ? " dark" : "") }, a.unread) : null))
      : h("p", { class: "muted small" }, "No mailbox yet."));
}

// --- settings -------------------------------------------------------------------------
async function renderSettings() {
  const col = $("settings-col");
  let ai, accounts, rules, outlook;
  try {
    [ai, accounts, rules, outlook] = await Promise.all([
      api("/api/settings/ai"), api("/api/accounts"), api("/api/rules"), api("/api/settings/outlook"),
    ]);
  } catch (e) { toast(e.message); return; }
  col.replaceChildren(h("div", { class: "settings-grid" },
    h("div", { style: "display:flex;flex-direction:column;gap:18px" }, accountsCard(accounts, outlook), notificationsCard(), profileCard(ai), setupCard()),
    h("div", { style: "display:flex;flex-direction:column;gap:18px" }, aiCard(ai), assistantCard(), rulesCard(rules), safetyCard())));
}

function field(label, input, hint) {
  return h("label", { class: "field" }, h("span", {}, label), input, hint ? h("div", { class: "hint" }, hint) : null);
}

// --- guided setup (shared by the welcome assistant and Settings) ----------------------
const DOCS = "https://github.com/S2K7x/Beseder/blob/HEAD/docs";

function guide(steps) {
  return h("ol", { class: "guide" }, steps.filter(Boolean).map((s) => h("li", {},
    h("div", {}, s.t),
    s.code ? h("code", { class: "cmd" }, s.code) : null,
    s.url ? h("a", { href: s.url, target: "_blank", rel: "noopener", class: "guide-link" }, s.label || "Open", icon("arrowUpRight")) : null)));
}

function choice(on, onclick, mark, title, sub, badge) {
  return h("button", { type: "button", class: "choice" + (on ? " on" : ""), onclick },
    h("span", { class: "mark" }, mark),
    h("span", { class: "grow" }, h("span", { class: "t" }, title), sub ? h("span", { class: "s" }, sub) : null),
    badge ? h("span", { class: "tag" + (badge === "Free" ? " dark" : "") }, badge) : null);
}

function providerHost(p, email) {
  const domain = (email.split("@")[1] || "").toLowerCase();
  return (p.domain_hosts || {})[domain] || p.host;
}

// Pick a provider (or just type the address: it is detected), follow the numbered steps,
// connect. Calls onAdded() once the mailbox works.
function mailboxSetup(outlook, onAdded) {
  const list = state.providers;
  const byKey = Object.fromEntries(list.map((p) => [p.key, p]));
  const popular = list.filter((p) => p.popular);
  let kind = "gmail";
  let email = "";
  let name = "";
  const picker = h("div");
  const form = h("div");

  function renderPicker() {
    const more = h("select", { "aria-label": "More providers" },
      h("option", { value: "" }, "More providers…"),
      list.filter((p) => !p.popular).map((p) => h("option", { value: p.key }, p.label)));
    if (!byKey[kind].popular) more.value = kind;
    more.addEventListener("change", () => { if (more.value) select(more.value); });
    picker.replaceChildren(
      h("div", { class: "choice-grid four" }, popular.map((p) => choice(p.key === kind, () => select(p.key), p.mark, p.label))),
      h("label", { class: "field more-providers" + (byKey[kind].popular ? "" : " on") }, more));
  }
  function select(k) { kind = k; renderPicker(); renderForm(); }

  function renderForm() {
    const p = byKey[kind];
    const emailIn = h("input", { type: "email", autocomplete: "off", value: email, placeholder: p.domains[0] ? `you@${p.domains[0]}` : "you@example.com" });
    const nameIn = h("input", { type: "text", value: name, placeholder: "Personal, Work…" });
    const err = h("div", { class: "error" });
    let host = null;
    // Typing an address switches to the matching provider (e.g. @yahoo.fr -> Yahoo).
    emailIn.addEventListener("input", () => { email = emailIn.value.trim(); });
    emailIn.addEventListener("change", () => {
      const domain = (email.split("@")[1] || "").toLowerCase();
      const match = list.find((x) => x.domains.includes(domain));
      if (match && match.key !== kind) { select(match.key); toast(`${match.label} detected`); }
      else if (host) host.value = providerHost(p, email);
    });
    nameIn.addEventListener("input", () => { name = nameIn.value; });

    if (p.auth === "oauth") {
      const clientId = h("input", { type: "text", value: outlook.client_id, placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" });
      const btn = h("button", { class: "pill dark sm" }, "Sign in with Microsoft");
      const flowBox = h("div");
      btn.addEventListener("click", async () => {
        err.textContent = "";
        try {
          const f = await api("/api/accounts/outlook/start", { method: "POST",
            body: { email: emailIn.value, name: nameIn.value, client_id: clientId.value } });
          flowBox.replaceChildren(h("div", { class: "notice" },
            "Open ", h("a", { href: f.verification_uri, target: "_blank", rel: "noopener" }, f.verification_uri),
            " and enter this code:", h("div", { class: "code" }, f.user_code), "Waiting for you to approve…"));
          pollOutlook(f.flow_id, f.interval, flowBox, onAdded);
        } catch (e) { err.textContent = e.message; }
      });
      form.replaceChildren(guide(p.steps), field("Address", emailIn), field("Name in Beseder", nameIn),
        field("Application (client) ID", clientId), h("div", { class: "btns" }, btn), err, flowBox);
      return;
    }
    const pwd = h("input", { type: "password", autocomplete: "off", placeholder: p.placeholder || "" });
    host = h("input", { type: "text", value: providerHost(p, email), placeholder: "imap.example.com" });
    const port = h("input", { type: "number", value: String(p.port) });
    const user = h("input", { type: "text", placeholder: "(defaults to the address)" });
    const server = h("details", { class: "advanced", open: kind === "imap" },
      h("summary", {}, kind === "imap" ? "Server" : "Advanced server settings"),
      field("IMAP server", host), field("Port", port, "993 = SSL, 143 = STARTTLS"), field("Username", user));
    const btn = h("button", { class: "pill dark sm" }, "Connect");
    btn.addEventListener("click", async () => {
      err.textContent = "";
      const done = busy(btn, "Checking…");
      try {
        await api("/api/accounts", { method: "POST", body: {
          kind, email: emailIn.value, name: nameIn.value, password: pwd.value,
          host: host.value.trim() === providerHost(p, emailIn.value.trim()) ? "" : host.value,
          port: Number(port.value) || 0, username: user.value } });
        toast(`${emailIn.value} connected, syncing now`);
        $("list-col").dataset.ready = "";
        email = ""; name = "";
        onAdded();
      } catch (e) { err.textContent = e.message; }
      finally { done(); }
    });
    form.replaceChildren(guide(p.steps), field("Address", emailIn), field("Name in Beseder", nameIn),
      field(p.password_label, pwd), server, h("div", { class: "btns" }, btn), err);
  }
  renderPicker();
  renderForm();
  return h("div", {}, picker, form);
}

async function pollOutlook(flowId, interval, box, onAdded) {
  for (;;) {
    await new Promise((r) => setTimeout(r, Math.max(interval, 3) * 1000));
    if (!document.body.contains(box)) return;
    let r;
    try { r = await api("/api/accounts/outlook/poll", { method: "POST", body: { flow_id: flowId } }); }
    catch (e) { box.replaceChildren(h("div", { class: "error" }, e.message)); return; }
    if (r.status === "done") { toast("Outlook connected, syncing now"); $("list-col").dataset.ready = ""; onAdded(); return; }
    if (r.status === "error") { box.replaceChildren(h("div", { class: "error" }, r.message)); return; }
  }
}

function accountsCard(accounts, outlook) {
  const list = accounts.map((a) => h("div", { class: "row-item" },
    avatar(a.name, a.email, "sm"),
    h("div", { class: "grow" },
      h("div", { class: "t" }, a.name, h("span", { class: "muted", style: "font-weight:400" }, ` · ${providerOf(a.kind).label}`)),
      a.last_error ? h("div", { class: "s error" }, a.last_error) : h("div", { class: "s" }, `${a.email} · ${fmtAgo(a.last_sync)}`)),
    h("button", { class: "pill sm", onclick: async () => {
      if (!confirm(`Remove ${a.email} from Beseder? Nothing is deleted in the mailbox itself.`)) return;
      try { await api(`/api/accounts/${a.id}`, { method: "DELETE" }); renderSettings(); } catch (e) { toast(e.message); }
    } }, "Remove")));
  return h("div", { class: "card" },
    h("h2", {}, "Mailboxes"),
    accounts.length ? list : h("p", { class: "muted small" }, "No mailbox yet. Add your first one below."),
    h("h3", { style: "font-size:15px;margin:22px 0 10px" }, "Add a mailbox"),
    mailboxSetup(outlook, renderSettings));
}

function aiSteps(key, p, inDocker) {
  const getKey = { url: p.key_url, label: "Get a key" };
  return {
    openrouter: [{ t: "Create a free OpenRouter account, then an API key.", ...getKey },
      { t: "Paste the key below and tap Load models." },
      { t: "Keep a model ending in “:free”, then tap Test & save." }],
    google: [{ t: "Sign in with Google and create an API key.", ...getKey },
      { t: "Paste it below, tap Load models, then Test & save." }],
    ollama: [{ t: "Install Ollama and download a model.", code: "ollama pull llama3.2", url: p.key_url, label: "Get Ollama" },
      inDocker ? { t: "Let Beseder's container reach it: run Ollama with OLLAMA_HOST=0.0.0.0.", url: `${DOCS}/ai.md#ollama`, label: "How to" } : null,
      { t: "Tap Load models, pick one, then Test & save." }],
    anthropic: [{ t: "Create an API key in the Anthropic Console.", ...getKey },
      { t: "Paste it below. Good models are already picked: tap Test & save." }],
    claude_cli: inDocker
      ? [{ t: "Rebuild Beseder with Claude Code inside:", code: "WITH_CLAUDE_CLI=true docker compose up -d --build", url: `${DOCS}/ai.md#claude-code`, label: "Details" },
        { t: "Sign in once (it stays signed in):", code: "docker compose exec -it beseder claude" },
        { t: "Tap Test & save." }]
      : [{ t: "Sign in once by running claude in a terminal on this machine." }, { t: "Tap Test & save." }],
    custom: [{ t: "Enter the API URL and key of any OpenAI-compatible service." },
      { t: "Load models, pick one, then Test & save." }],
  }[key];
}

function recommendModel(key, models, p) {
  const ok = (m) => !/(embed|image|tts|audio|vision-only|guard|whisper|live)/i.test(m);
  if (key === "openrouter") return models.find((m) => m.endsWith(":free") && ok(m)) || models[0];
  if (key === "google") return models.find((m) => /flash/.test(m) && ok(m) && !/preview|exp/.test(m)) || models.find((m) => /flash/.test(m)) || models[0];
  if (key === "anthropic" && models.includes(p.model)) return p.model;
  return models.find(ok) || models[0];
}

// Step-by-step AI connection. Calls onOk(label) after a successful test.
function aiSetup(key, ai, inDocker, onOk) {
  const p = ai.presets[key];
  const same = ai.preset === key;
  const apiKey = h("input", { type: "password", autocomplete: "off",
    placeholder: same && ai.has_key ? "•••••• saved (leave empty to keep it)" : "Paste your key" });
  const baseUrl = h("input", { type: "url", value: same && ai.base_url ? ai.base_url : p.base_url });
  const command = h("input", { type: "text", value: ai.command || "claude" });
  const freeOnly = h("input", { type: "checkbox", checked: true });
  let models = [];
  const modelSel = h("select");
  const modelTxt = h("input", { type: "text", placeholder: "model name", value: same ? ai.model : p.model || "" });
  const modelBox = h("div");
  const result = h("div");
  const err = h("div", { class: "error" });

  function renderModels(pick) {
    const list = key === "openrouter" && freeOnly.checked ? models.filter((m) => m.endsWith(":free")) : models;
    modelSel.replaceChildren(...list.map((m) => h("option", { value: m }, m)));
    if (pick && list.includes(pick)) modelSel.value = pick;
    modelBox.replaceChildren();
    put(modelBox, field("Model", list.length ? modelSel : modelTxt),
      key === "openrouter" && models.length ? h("label", { class: "small muted row-check" }, freeOnly, "Free models only") : null);
  }
  freeOnly.addEventListener("change", () => renderModels(modelSel.value));
  renderModels();

  const form = () => ({
    preset: key, base_url: baseUrl.value, api_key: apiKey.value, command: command.value,
    model: key === "claude_cli" ? "" : (models.length ? modelSel.value : modelTxt.value),
    model_fast: key === "anthropic" || key === "claude_cli" ? p.model_fast || "" : "",
  });

  const loadBtn = h("button", { class: "pill sm" }, "Load models");
  loadBtn.addEventListener("click", async () => {
    err.textContent = "";
    const done = busy(loadBtn, "Loading…");
    try {
      models = (await api("/api/settings/ai/models", { method: "POST", body: form() })).models;
      if (!models.length) throw new Error("No model found. Download one first (see step 1).");
      renderModels(recommendModel(key, models, p));
      toast(models.length === 1 ? "1 model found and selected" : `${models.length} models found, a good one is selected`);
    } catch (e) { err.textContent = e.message; }
    finally { done(); }
  });
  const testBtn = h("button", { class: "pill dark sm" }, "Test & save");
  testBtn.addEventListener("click", async () => {
    err.textContent = "";
    result.replaceChildren();
    const done = busy(testBtn, "Testing…");
    try {
      await api("/api/settings/ai", { method: "PUT", body: form() });
      apiKey.value = "";
      const r = await api("/api/settings/ai/test", { method: "POST" });
      result.replaceChildren(h("div", { class: "success" }, "✓ Connected. The AI answered “", r.reply, "”."));
      onOk(p.label);
    } catch (e) { err.textContent = e.message; }
    finally { done(); }
  });

  const needsKey = p.needs_key || key === "custom";
  const hasModels = key !== "claude_cli";
  return h("div", { class: "ai-setup" },
    guide(aiSteps(key, p, inDocker)),
    p.note ? h("div", { class: "notice" }, p.note) : null,
    key === "ollama" || key === "custom" ? field("API URL", baseUrl) : null,
    needsKey ? field("API key", apiKey) : null,
    key === "claude_cli" ? h("details", { class: "advanced" }, h("summary", {}, "Advanced"), field("Command", command)) : null,
    hasModels ? modelBox : null,
    h("div", { class: "btns" }, hasModels ? loadBtn : null, testBtn),
    err, result);
}

// --- welcome assistant -----------------------------------------------------------------
const wiz = { step: 0, preset: null, aiLabel: "" };
const LANGS = ["English", "French", "Spanish", "German", "Italian", "Portuguese", "Dutch", "Hebrew", "Arabic"];
const WIZ_STEPS = ["Welcome", "Mailboxes", "AI", "Finish"];

async function renderWelcome() {
  let ai, accounts, outlook;
  try {
    [ai, accounts, outlook] = await Promise.all([api("/api/settings/ai"), api("/api/accounts"), api("/api/settings/outlook")]);
    await refreshStatus();
  } catch (e) { toast(e.message); return; }
  const ctx = { ai, accounts, outlook, st: state.status };
  const body = [stepWelcome, stepMailboxes, stepAI, stepFinish][wiz.step](ctx);
  $("settings-col").replaceChildren(h("div", { class: "wizard" },
    h("div", { class: "wiz-head" },
      h("div", { class: "logo" }, icon("logo")),
      h("div", { class: "wiz-steps" }, WIZ_STEPS.map((s, i) => h("div", { class: "wiz-step" + (i === wiz.step ? " on" : "") + (i < wiz.step ? " done" : "") },
        h("span", { class: "dot" }, i < wiz.step ? "✓" : String(i + 1)), h("span", { class: "lbl" }, s))))),
    h("div", { class: "card wiz-card" }, body)));
  window.scrollTo(0, 0);
}
function wizGo(step) { wiz.step = step; renderWelcome(); }

function wizNav({ back, skip, next, nextLabel = "Continue", nextDisabled = false }) {
  const nextBtn = next ? h("button", { class: "pill dark", disabled: nextDisabled }, nextLabel, icon("arrowUpRight")) : null;
  if (nextBtn) nextBtn.addEventListener("click", async () => {
    const done = busy(nextBtn);
    try { await next(); } catch (e) { toast(e.message); } finally { done(); }
  });
  return h("div", { class: "wiz-nav" },
    back ? h("button", { class: "link", onclick: back }, icon("chevronLeft"), "Back") : h("span"),
    h("span", { style: "flex:1" }),
    skip ? h("button", { class: "link", onclick: skip[1] }, skip[0]) : null,
    nextBtn);
}

function feature(ic, title, text) {
  return h("div", { class: "feature" }, h("span", { class: "ico" }, icon(ic)), h("div", {}, h("div", { class: "t" }, title), h("div", { class: "s" }, text)));
}

function stepWelcome({ st }) {
  const name = h("input", { type: "text", value: st.my_name, placeholder: "Your first name", autocomplete: "given-name" });
  const lang = h("select", {}, LANGS.map((l) => h("option", { value: l }, l)));
  lang.value = LANGS.includes(st.summary_language) ? st.summary_language : "English";
  return [
    h("h1", { class: "wiz-title" }, "Welcome to Beseder"),
    h("p", { class: "wiz-lead" }, "One calm inbox for all your mailboxes, with an AI assistant that works for you, not instead of you. Setup takes about 5 minutes."),
    h("div", { class: "features" },
      feature("tag", "Sorts your mail", "Important, newsletters, receipts… filed as mail arrives."),
      feature("sparkles", "Briefs you", "One tap to know what matters in your unread mail."),
      feature("reply", "Drafts replies", "Only when you ask. You review it and send it yourself."),
      feature("shield", "Never acts alone", "It cannot send, delete or forward anything.")),
    field("What should we call you?", name),
    field("Language for your briefs", lang, "Drafts always use the language of the email you reply to."),
    wizNav({ next: async () => {
      await api("/api/settings/profile", { method: "PUT", body: { name: name.value, summary_language: lang.value } });
      wizGo(1);
    }, nextLabel: "Let's start" }),
  ];
}

function stepMailboxes({ accounts, outlook }) {
  return [
    h("h1", { class: "wiz-title" }, "Connect your mailboxes"),
    h("p", { class: "wiz-lead" }, "Add as many as you like. Beseder reads them, and only writes a draft when you ask it to."),
    accounts.length ? h("div", { class: "connected" }, accounts.map((a) => h("div", { class: "row-item" },
      avatar(a.name, a.email, "sm"), h("div", { class: "grow" }, h("div", { class: "t" }, a.name), h("div", { class: "s" }, a.email)),
      h("span", { class: "tag dark" }, "✓ Connected")))) : null,
    accounts.length ? h("h3", { class: "wiz-sub" }, "Add another one") : null,
    mailboxSetup(outlook, () => renderWelcome()),
    wizNav({ back: () => wizGo(0), skip: accounts.length ? null : ["Skip for now", () => wizGo(2)],
      next: async () => wizGo(2), nextDisabled: !accounts.length }),
  ];
}

function stepAI({ ai, st }) {
  const key = wiz.preset || (st.ai_configured ? ai.preset : null);
  const order = ["openrouter", "google", "ollama", "anthropic", "claude_cli", "custom"];
  const box = h("div");
  const nav = () => wizNav({ back: () => wizGo(1), skip: st.ai_configured ? null : ["Skip, I'll do it later", () => wizGo(3)],
    next: async () => wizGo(3), nextDisabled: !state.status.ai_configured });
  let navEl = nav();
  if (key) box.replaceChildren(aiSetup(key, ai, st.in_docker, async (label) => {
    wiz.aiLabel = label;
    await refreshStatus();
    const fresh = nav();
    navEl.replaceWith(fresh);
    navEl = fresh;
  }));
  return [
    h("h1", { class: "wiz-title" }, "Connect your AI"),
    h("p", { class: "wiz-lead" }, "Pick one. Free options work well to start, and you can switch any time in Settings."),
    h("div", { class: "choice-grid" }, order.map((k) => {
      const p = ai.presets[k];
      return choice(k === key, () => { wiz.preset = k; renderWelcome(); }, h("span", {}, icon(k === "ollama" ? "shield" : k === "custom" ? "settings" : "sparkles")),
        p.label, p.tagline, p.badge);
    })),
    box,
    navEl,
  ];
}

function pushRow() {
  const hint = pushHint();
  const btn = h("button", { class: "pill sm" }, "Turn on");
  const row = h("div", { class: "big-switch", style: "margin-top:10px" },
    h("div", { class: "grow" }, h("div", { class: "t" }, "Notifications"),
      h("div", { class: "s" }, hint || "Get a notification when an important email arrives.")),
    hint ? null : btn);
  btn.addEventListener("click", async () => {
    const done = busy(btn, "…");
    try { await enablePush(); btn.replaceWith(h("span", { class: "tag dark" }, "✓ On")); }
    catch (e) { toast(e.message); done(); }
  });
  return row;
}

function stepFinish({ accounts, st }) {
  const triage = h("input", { type: "checkbox", checked: st.ai_configured, disabled: !st.ai_configured });
  const check = (ok, text) => h("div", { class: "row-item" }, h("span", { class: "ico" + (ok ? " ok" : "") }, ok ? "✓" : "–"), h("div", { class: "grow t" }, text));
  return [
    h("h1", { class: "wiz-title" }, "You're all set"),
    h("p", { class: "wiz-lead" }, "One last choice, then your inbox."),
    h("label", { class: "big-switch" }, h("div", { class: "grow" }, h("div", { class: "t" }, "Sort new mail automatically"),
      h("div", { class: "s" }, st.ai_configured ? "The AI files each new email into a category. You can turn it off any time." : "Connect an AI first to use auto-triage.")),
      h("span", { class: "switch" }, triage, h("span", { class: "track" }))),
    h("div", { class: "checklist" },
      check(!!st.my_name, st.my_name ? `Hi ${st.my_name.split(" ")[0]}!` : "No name set"),
      check(accounts.length > 0, accounts.length ? `${accounts.length} mailbox${accounts.length > 1 ? "es" : ""} connected` : "No mailbox yet (add one in Settings)"),
      check(st.ai_configured, st.ai_configured ? `AI connected: ${wiz.aiLabel || st.ai_label}` : "No AI yet (add one in Settings)")),
    pushRow(),
    h("div", { class: "notice" }, "On iPhone: in Safari, tap Share › Add to Home Screen to use Beseder like an app."),
    wizNav({ back: () => wizGo(2), nextLabel: "Open my inbox", next: async () => {
      if (st.ai_configured) await api("/api/settings/triage", { method: "PUT", body: { auto: triage.checked } });
      await api("/api/settings/onboarded", { method: "PUT", body: { done: true } });
      wiz.step = 0;
      $("list-col").dataset.ready = "";
      go("#/");
    } }),
  ];
}

function notificationsCard() {
  const card = h("div", { class: "card" }, h("h2", {}, "Notifications"), h("p", { class: "muted small" }, "Loading…"));
  (async () => {
    let info, sub;
    try { [info, sub] = await Promise.all([api("/api/push"), currentPushSubscription()]); }
    catch (e) { card.replaceChildren(h("h2", {}, "Notifications"), h("div", { class: "error" }, e.message)); return; }
    const mode = h("select", {},
      h("option", { value: "important" }, "Important emails only"),
      h("option", { value: "all" }, "Every new email"),
      h("option", { value: "off" }, "Off"));
    mode.value = info.mode;
    const preview = h("input", { type: "checkbox", checked: info.preview });
    const save = async () => {
      try { await api("/api/push/settings", { method: "PUT", body: { mode: mode.value, preview: preview.checked } }); toast("Saved"); }
      catch (e) { toast(e.message); }
    };
    mode.addEventListener("change", save);
    preview.addEventListener("change", save);
    const on = !!sub && Notification.permission === "granted";
    const hint = pushHint();
    const toggle = h("button", { class: "pill sm" + (on ? "" : " dark") }, on ? "Turn off on this device" : "Turn on for this device");
    toggle.addEventListener("click", async () => {
      const done = busy(toggle, on ? "Turning off…" : "Turning on…");
      try {
        if (on) { await disablePush(); toast("Notifications off on this device"); }
        else { await enablePush(); toast("Notifications on for this device"); }
        renderSettings();
      } catch (e) { toast(e.message); done(); }
    });
    const test = h("button", { class: "pill sm" }, "Send a test");
    test.addEventListener("click", async () => {
      const done = busy(test, "Sending…");
      try { await api("/api/push/test", { method: "POST" }); toast("Test sent: it should appear in a few seconds"); }
      catch (e) { toast(e.message); }
      finally { done(); }
    });
    card.replaceChildren();
    put(card,
      h("h2", {}, "Notifications"),
      h("p", { class: "muted small", style: "margin:0" },
        on ? "On for this device." : "Off for this device.", ` ${info.devices} device${info.devices === 1 ? "" : "s"} in total.`),
      hint ? h("div", { class: "notice" }, hint) : null,
      field("Notify me about", mode, mode.value === "important" ? "Needs auto-triage, so the AI can tell what's important." : null),
      h("label", { class: "row-check small" }, preview, "Show the sender and subject (turn off for privacy on the lock screen)"),
      h("div", { class: "btns" }, hint ? null : toggle, info.devices ? test : null));
  })();
  return card;
}

function setupCard() {
  return h("div", { class: "card" },
    h("h2", {}, "Help"),
    h("p", { class: "muted small", style: "margin:0" }, "Run the setup assistant again, or read the guides."),
    h("div", { class: "btns" },
      h("button", { class: "pill sm", onclick: () => { wiz.step = 0; wiz.preset = null; go("#/welcome"); } }, "Run setup again"),
      h("a", { class: "pill sm", href: `${DOCS}/README.md`, target: "_blank", rel: "noopener" }, "Open the docs")));
}

function aiCard(ai) {
  const preset = h("select", {}, Object.entries(ai.presets).map(([k, p]) => h("option", { value: k }, p.label)));
  preset.value = ai.preset || "openrouter";
  const baseUrl = h("input", { type: "url", value: ai.base_url });
  const apiKey = h("input", { type: "password", autocomplete: "off", placeholder: ai.has_key ? "•••••• saved (leave empty to keep it)" : "" });
  const dl = h("datalist", { id: "models" });
  const model = h("input", { type: "text", value: ai.model, list: "models", placeholder: "model name" });
  const modelFast = h("input", { type: "text", value: ai.model_fast, list: "models", placeholder: "(optional) faster model for triage" });
  const command = h("input", { type: "text", value: ai.command || "claude" });
  const note = h("div", { class: "notice" });
  const err = h("div", { class: "error" });
  const urlField = field("API URL", baseUrl);
  const keyField = field("API key", apiKey);
  const cmdField = field("Command", command, "Path to the claude binary on the Pi (run `which claude`).");

  function sync(initial) {
    const p = ai.presets[preset.value];
    note.textContent = p.note || "";
    note.hidden = !p.note;
    urlField.hidden = p.kind !== "openai_compat";
    keyField.hidden = p.kind === "claude_cli" || (!p.needs_key && preset.value !== "custom");
    cmdField.hidden = p.kind !== "claude_cli";
    if (!initial) {
      baseUrl.value = p.base_url || "";
      model.value = p.model || "";
      modelFast.value = p.model_fast || "";
    } else if (!ai.preset) {
      baseUrl.value = p.base_url || "";
    }
  }
  preset.addEventListener("change", () => sync(false));
  sync(true);

  const form = () => ({ preset: preset.value, base_url: baseUrl.value, model: model.value,
    model_fast: modelFast.value, api_key: apiKey.value, command: command.value });

  const listBtn = h("button", { class: "pill sm" }, "List models");
  listBtn.addEventListener("click", async () => {
    err.textContent = "";
    const done = busy(listBtn, "Loading…");
    try {
      const r = await api("/api/settings/ai/models", { method: "POST", body: form() });
      dl.replaceChildren(...r.models.map((x) => h("option", { value: x })));
      toast(`${r.models.length} models found. Type in the field to filter (e.g. "free").`);
    } catch (e) { err.textContent = e.message; }
    finally { done(); }
  });
  const saveBtn = h("button", { class: "pill dark sm" }, "Save");
  saveBtn.addEventListener("click", async () => {
    err.textContent = "";
    try { await api("/api/settings/ai", { method: "PUT", body: form() }); toast("AI settings saved"); apiKey.value = ""; }
    catch (e) { err.textContent = e.message; }
  });
  const testBtn = h("button", { class: "pill sm" }, "Test");
  testBtn.addEventListener("click", async () => {
    err.textContent = "";
    const done = busy(testBtn, "Testing…");
    try {
      await api("/api/settings/ai", { method: "PUT", body: form() });
      apiKey.value = "";
      const r = await api("/api/settings/ai/test", { method: "POST" });
      toast(`The AI says: "${r.reply}"`);
    } catch (e) { err.textContent = e.message; }
    finally { done(); }
  });

  return h("div", { class: "card" },
    h("h2", {}, "AI provider"),
    h("p", { class: "muted small", style: "margin:0" }, "Free, local or your Claude subscription: pick one, list its models, test it."),
    field("Provider", preset), note, urlField, keyField, cmdField,
    field("Model (briefs and drafts)", model), field("Fast model (triage)", modelFast), dl,
    h("div", { class: "btns" }, listBtn, testBtn, saveBtn), err);
}

function assistantCard() {
  const card = h("div", { class: "card" }, h("h2", {}, "Assistant"), h("p", { class: "muted small" }, "Loading…"));
  (async () => {
    let a;
    try { a = await api("/api/settings/assistant"); } catch (e) { card.replaceChildren(h("h2", {}, "Assistant"), h("div", { class: "error" }, e.message)); return; }
    const rules = h("textarea", { rows: "4", placeholder: "Emails from my kids' school are important\nShipping updates go to Notifications\nAnything about my car insurance is important" });
    rules.value = a.rules;
    const saveRules = h("button", { class: "pill sm" }, "Save rules");
    saveRules.addEventListener("click", async () => {
      try {
        const r = await api("/api/settings/rules", { method: "PUT", body: { rules: rules.value } });
        rules.value = r.rules.join("\n");
        toast(r.rules.length ? "Rules saved: they apply to new mail" : "Rules cleared");
      } catch (e) { toast(e.message); }
    });
    const resort = h("button", { class: "pill sm" }, "Re-sort the last 14 days");
    resort.addEventListener("click", async () => {
      const done = busy(resort, "Sorting…");
      try {
        await api("/api/settings/rules", { method: "PUT", body: { rules: rules.value } });
        const r = await api("/api/triage/resort", { method: "POST" });
        toast(`${r.classified} email${r.classified === 1 ? "" : "s"} sorted again`);
        $("list-col").dataset.ready = "";
      } catch (e) { toast(e.message); }
      finally { done(); }
    });
    const style = h("input", { type: "checkbox", checked: a.learn_style, onchange: async (e) => {
      try { await api("/api/settings/style", { method: "PUT", body: { learn: e.target.checked } }); toast("Saved"); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
    } });
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const on = h("input", { type: "checkbox", checked: !!a.time });
    const time = h("input", { type: "time", value: a.time || "07:30", disabled: !a.time });
    const saveBrief = async () => {
      time.disabled = !on.checked;
      try {
        await api("/api/settings/brief", { method: "PUT", body: { time: on.checked ? time.value : "", tz } });
        toast(on.checked ? `Morning brief every day at ${time.value}` : "Morning brief off");
      } catch (e) { toast(e.message); }
    };
    on.addEventListener("change", saveBrief);
    time.addEventListener("change", saveBrief);
    card.replaceChildren();
    put(card,
      h("h2", {}, "Assistant"),
      field("Sorting rules", rules, `In your own words, one per line (up to ${a.max_rules}). The AI follows them when it sorts new mail.`),
      h("div", { class: "btns" }, saveRules, resort),
      h("label", { class: "big-switch", style: "margin-top:16px" },
        h("div", { class: "grow" }, h("div", { class: "t" }, "Write drafts like me"),
          h("div", { class: "s" }, "The AI looks at a few emails you sent (to the same person first) to match your tone and sign-off.")),
        h("span", { class: "switch" }, style, h("span", { class: "track" }))),
      h("label", { class: "big-switch", style: "margin-top:10px" },
        h("div", { class: "grow" }, h("div", { class: "t" }, "Morning brief"),
          h("div", { class: "s" }, `Every day, the AI summarizes your unread mail and sends you a notification (${tz}).`)),
        h("span", { class: "switch" }, on, h("span", { class: "track" }))),
      field("Time", time));
  })();
  return card;
}

function profileCard(ai) {
  const name = h("input", { type: "text", value: ai.my_name, placeholder: "First Last" });
  const lang = h("input", { type: "text", value: ai.summary_language || "English", placeholder: "English" });
  return h("div", { class: "card" },
    h("h2", {}, "Profile"),
    field("Your name", name, "Used to greet you and to sign AI drafts."),
    field("Brief language", lang, "Drafts always follow the language of the email you reply to."),
    h("div", { class: "btns" }, h("button", { class: "pill sm", onclick: async () => {
      try {
        await api("/api/settings/profile", { method: "PUT", body: { name: name.value, summary_language: lang.value } });
        toast("Profile saved");
      } catch (e) { toast(e.message); }
    } }, "Save")));
}

function rulesCard(rules) {
  return h("div", { class: "card" },
    h("h2", {}, "Sender rules"),
    h("p", { class: "muted small", style: "margin:0" }, "Created with the tag button on an email. They run before the AI, so it cannot override them."),
    rules.length ? rules.map((r) => h("div", { class: "row-item" },
      h("span", { class: "ico" }, icon(CATS[r.category]?.icon || "tag")),
      h("div", { class: "grow" }, h("div", { class: "t" }, r.addr), h("div", { class: "s" }, CATS[r.category]?.label || r.category)),
      h("button", { class: "pill sm", onclick: async () => {
        try { await api(`/api/rules/${encodeURIComponent(r.addr)}`, { method: "DELETE" }); renderSettings(); } catch (e) { toast(e.message); }
      } }, "Delete"))) : h("p", { class: "muted small" }, "No rule yet."));
}

function safetyCard() {
  return h("div", { class: "card" },
    h("h2", { style: "display:flex;align-items:center;gap:8px" }, icon("shield"), "What the AI can do"),
    h("p", { class: "small", style: "margin:6px 0 0;line-height:1.6" },
      "Read, sort, brief and draft, only when you tap a button (or turn on auto-triage). ",
      "It has no tools: it cannot send, delete, move or forward anything. ",
      "Drafts land in your Drafts folder and you send them yourself."));
}

// --- top bar and startup ----------------------------------------------------------------
document.querySelectorAll("[data-icon]").forEach((el) => el.prepend(icon(el.dataset.icon)));
$("back").addEventListener("click", () => (history.length > 1 ? history.back() : go("#/")));
$("rail-settings").addEventListener("click", () => go("#/settings"));
$("top-settings").addEventListener("click", () => go("#/settings"));
$("summarize").addEventListener("click", () => runSummary(null));
$("sync").addEventListener("click", async () => {
  try {
    const r = await api("/api/sync", { method: "POST" });
    toast(r.started ? "Syncing your mailboxes" : "A sync is already running");
    $("sync-state").textContent = "Syncing…";
  } catch (e) { toast(e.message); }
});
let searchTimer;
$("search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value.trim(); state.ask = null; state.followups = false; navigateList(); }, 300);
});
// Ask in plain language: "how much was my last electricity bill?"
$("ask").addEventListener("click", () => runAsk($("search").value.trim()));
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && /\?\s*$/.test(e.target.value)) { e.preventDefault(); clearTimeout(searchTimer); runAsk(e.target.value.trim()); }
});
$("account-filter").addEventListener("change", (e) => { state.accountId = e.target.value; navigateList(); });

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
// New mail is synced within a second of arriving (IMAP IDLE) and the server tells this page
// right away (server-sent events). A slow poll stays as a safety net.
async function refreshIfChanged() {
  if (["settings", "welcome"].includes(state.view)) return;
  const before = state.status?.version;
  await refreshStatus();
  if (before !== undefined && state.status && state.status.version !== before) {
    $("list-col").dataset.ready = "";
    renderChrome(); renderSide(); renderList();
  }
}
if ("EventSource" in window) {
  new EventSource("/api/events").onmessage = (e) => {
    if (state.status && Number(e.data) !== state.status.version) refreshIfChanged();
  };
}
setInterval(() => { if (document.visibilityState === "visible") refreshIfChanged(); }, 30000);
route();
