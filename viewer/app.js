// Toxline viewer: the guest's-eye view of every chat, plus setup and controls.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const state = { snap: null, current: null, messages: [], showArchived: false, filter: "", typing: {} };
const COLORS = ["#7c3aed", "#db2777", "#ea580c", "#0891b2", "#16a34a", "#4f46e5", "#ca8a04", "#dc2626", "#0d9488", "#9333ea"];

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

function toast(text) {
  const t = $("#toast");
  t.textContent = text; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 2200);
}

function color(id) { let h = 0; for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return COLORS[h % COLORS.length]; }
function initials(name) { return name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("") || "?"; }
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function linkify(s) { return esc(s).replace(/https?:\/\/[^\s<]+/g, u => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`); }
function hhmm(t) { return new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
function dayLabel(t) {
  const d = new Date(t * 1000), now = new Date();
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return "Today";
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}
function ago(t) {
  const s = Date.now() / 1000 - t;
  if (s < 60) return "now"; if (s < 3600) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h"; return Math.floor(s / 86400) + "d";
}
const ROLE_BADGE = { agent: "agent", consult: "agent" };
const ROLE_NOTE = { agent: "someone's agent: it asks, yours answers", consult: "an agent yours is questioning for you" };
function onlineText(c) {
  if (c.kind === "test") return "Test guest (simulated)";
  return { udp: "Online", tcp: "Online (relayed)", none: "Offline" }[c.online] || c.online;
}

// ------------------------------------------------------------------ sidebar
function renderMe() {
  const me = state.snap.self;
  $("#me-name").textContent = me.name || "Tox disabled";
  $("#me-tox").textContent = me.tox_id || "Running with test guests only";
  $("#me-dot").className = "dot " + (me.connection || "none");
  $("#me-id").title = me.tox_id ? `Agent Tox ID (${me.connection === "none" ? "connecting to the Tox network…" : "connected via " + me.connection.toUpperCase()}). Click to copy.` : "";
}

function renderRequests() {
  const el = $("#requests");
  el.innerHTML = "";
  for (const r of state.snap.requests) {
    const d = document.createElement("div");
    d.className = "request";
    d.innerHTML = `<b>${r.returning ? `${esc(r.returning)} is back (archived guest)` : r.agent ? "Friend request from an agent" : "Friend request"}</b> <span class="hint">${ago(r.at)}</span><div>${esc(r.greeting || "(no message)")}</div>
      <code>${r.public_key.slice(0, 16)}…</code>
      <div class="row"><button class="primary">Set up guest</button><button class="ghost">Dismiss</button></div>`;
    const [setup, dismiss] = d.querySelectorAll("button");
    if (r.returning) setup.textContent = "Restore guest";
    setup.onclick = () => openNew(r.returning
      ? { tox_id: r.public_key, fromRequest: true, returning: r.returning, name: r.returning, thread: r.thread_id || "", role: r.role || "person" }
      : { tox_id: r.public_key, fromRequest: true, role: r.agent ? "agent" : "person", notes: r.greeting ? `Their request said: ${r.greeting}` : "" });
    dismiss.onclick = () => api("POST", `/api/requests/${r.public_key}/dismiss`).then(refresh);
    el.append(d);
  }
}

function renderContacts() {
  const nav = $("#contacts");
  nav.innerHTML = "";
  const f = state.filter.toLowerCase();
  for (const c of state.snap.contacts) {
    if (c.status === "archived" && !state.showArchived) continue;
    if (f && !(`${c.name} ${c.id} ${c.tox_name || ""} ${c.notes}`.toLowerCase().includes(f))) continue;
    const a = document.createElement("a");
    a.className = "contact" + (c.id === state.current ? " active" : "") + (c.status === "archived" ? " archived" : "");
    a.href = `#${c.id}`;
    const last = c.last;
    const prefix = last ? (last.direction === "out" ? "Agent: " : "") : "";
    const dotCls = c.status === "paused" ? "paused" : (c.kind === "test" ? "udp" : c.online);
    const flags = [c.kind === "test" ? "test" : "", ROLE_BADGE[c.role] || "", c.hold_outgoing ? "hold" : "", c.status === "paused" ? "paused" : ""].filter(Boolean);
    a.innerHTML = `<div class="avatar" style="background:${color(c.id)}">${esc(initials(c.name))}<span class="dot ${dotCls}"></span></div>
      <div style="min-width:0"><div class="name"><span>${esc(c.name)}</span>${flags.map(f => `<span class="badge ${f === "hold" ? "held" : ""}">${f}</span>`).join("")}</div>
      <div class="preview">${last ? esc(prefix + last.body.split("\n")[0]) : (c.thread_id ? "No messages yet" : "⚠ no agent thread")}</div></div>
      <div class="meta"><span>${last ? ago(last.created_at) : ""}</span>${c.unread && c.id !== state.current ? `<span class="unread">${c.unread}</span>` : ""}</div>`;
    nav.append(a);
  }
  if (!nav.children.length) nav.innerHTML = `<p class="hint" style="padding:12px">${state.snap.contacts.length ? "No matches." : "No guests yet. Click + Guest."}</p>`;
}

// --------------------------------------------------------------------- chat
function contact() { return state.snap?.contacts.find(c => c.id === state.current); }

function renderHead() {
  const c = contact();
  if (!c) return;
  $("#chat-avatar").style.background = color(c.id);
  $("#chat-avatar").textContent = initials(c.name);
  $("#chat-name").textContent = c.name;
  $("#chat-kind").textContent = [c.kind === "test" ? "test" : (c.tox_name && c.tox_name !== c.name ? `Tox: ${c.tox_name}` : ""), ROLE_NOTE[c.role] || ""].filter(Boolean).join(" · ");
  $("#chat-dot").className = "dot " + (c.kind === "test" ? "udp" : c.online);
  const mates = state.snap.contacts.filter(o => o.id !== c.id && o.thread_id && o.thread_id === c.thread_id && o.status !== "archived").map(o => o.name);
  $("#chat-status").textContent = onlineText(c) + (c.status === "paused" ? " · bridge paused" : "") + (c.status === "archived" ? " · archived" : "") + (mates.length ? ` · shares a thread with ${mates.join(", ")}` : "");
  const hold = $("#btn-hold");
  hold.classList.toggle("on", !!c.hold_outgoing);
  hold.textContent = c.hold_outgoing ? "Holding outgoing" : "Hold outgoing";
  $("#btn-open").disabled = !c.thread_id;
  const banner = $("#banner");
  const held = state.messages.filter(m => m.state === "held").length;
  const msgs = [];
  if (c.role === "consult" && c.online === "none" && c.status === "active") msgs.push("Their agent is offline (or hasn't accepted the friend request yet). Your agent's messages wait and go out when it connects.");
  if (!c.thread_id) msgs.push("This guest has no agent thread. Open ⋯ to bind one; their messages are being kept until then.");
  if (c.status === "paused") msgs.push("Bridge paused: their messages are kept but not delivered to the agent, and the agent's replies are held. Resume from ⋯.");
  if (c.hold_outgoing) msgs.push(`Outgoing on hold. The agent's replies wait here for you${held ? ` (${held} waiting)` : ""}.`);
  if (c.status === "archived") msgs.push("Archived: they're no longer a Tox friend and nothing reaches the agent. Unarchive from ⋯.");
  if (c.budget && c.budget.used >= c.budget.limit) msgs.push(`Agent conversation paused: your agent has sent its ${c.budget.limit} messages. Its next replies are held here; Send now on one to allow ${c.budget.limit} more.`);
  if (state.offline) msgs.unshift("Toxline service is offline. Reconnecting…");
  banner.innerHTML = msgs.map(esc).join("<br>");
  banner.hidden = !msgs.length;
  $("#sim-box").hidden = c.kind !== "test" || c.status === "archived";
  $("#watch-note").hidden = c.kind === "test";
  $("#sim-text").placeholder = `Type as ${c.name}…`;
  $("#typing").hidden = !state.typing[c.id];
}

function inboundTag(m) {
  return {
    delivering: ["delivering to agent…", ""],
    delivered_to_thread: ["in agent thread ✓", "ok"],
    pending: ["kept (not delivered yet)", ""],
    delivery_failed: ["delivery to agent failed", "bad"],
    waiting_for_desktop: ["waiting: thread is open in Codex Desktop", ""],
  }[m.state] || [m.state, ""];
}

function ticks(m) {
  // What the guest's own client would show for the agent's messages: nothing unusual.
  // These ticks are owner details: ✓ sent to Tox, ✓✓ their client confirmed.
  if (m.state === "delivered") return `<span class="owner ticks read" title="Their client confirmed receipt">✓✓</span>`;
  if (m.state === "sent") return `<span class="owner ticks" title="Sent over Tox; waiting for their client to confirm">✓</span>`;
  return "";
}

function renderLog(keepScroll) {
  const log = $("#log");
  let liveEditor = null;
  if (state.editing) {
    const m = state.messages.find(x => x.id === state.editing.id);
    if (!m || m.state !== "held") {
      if (log.querySelector(".edit-box")) toast("That message was already handled elsewhere");
      state.editing = null;
    } else {
      liveEditor = log.querySelector(".msg.editing");   // keep its focus, caret and text
    }
  }
  const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  const c = contact();
  const focused = document.activeElement?.classList.contains("edit-box") ? document.activeElement : null;
  const sel = focused ? [focused.selectionStart, focused.selectionEnd] : null;
  log.innerHTML = "";
  let lastDay = "", prev = null;
  for (const m of state.messages) {
    const at = m.shown_at || m.created_at;
    const day = dayLabel(at);
    if (day !== lastDay) { const d = document.createElement("div"); d.className = "day"; d.textContent = day; log.append(d); lastDay = day; prev = null; }
    // Guest's perspective: their own messages on the right, the agent's on the left.
    const mine = m.direction === "in";
    const notYetVisible = m.direction === "out" && ["held", "offline_queued", "failed", "discarded"].includes(m.state);
    const el = document.createElement("div");
    const cont = prev && prev.direction === m.direction && at - (prev.shown_at || prev.created_at) < 120;
    el.className = `msg ${mine ? "mine" : "theirs"} ${cont ? "group-cont" : "group-start"} ${m.state === "held" ? "held" : ""} ${m.state === "offline_queued" ? "offline ghost" : ""} ${m.state === "failed" ? "failed" : ""} ${m.state === "discarded" ? "discarded" : ""}`;
    el.dataset.id = m.id;
    let tag = "";
    if (mine) {
      const [t, cls] = inboundTag(m);
      tag = `<span class="owner owner-tag ${cls === "bad" ? "bad" : ""}" style="${cls === "ok" ? "color:var(--muted)" : ""}">${t}</span>`;
    } else if (notYetVisible) {
      tag = `<span class="owner owner-tag ${m.state === "failed" ? "bad" : ""}">${{ held: /budget/.test(m.detail) ? "held: message budget used up" : "held for you: they can't see this yet", offline_queued: "waiting for them to come online", failed: "failed: " + esc(m.detail), discarded: "discarded" }[m.state]}</span>`;
    }
    let actions = "";
    if (m.state === "held") actions = `<div class="owner-block when-mine"><button data-act="release" class="primary">Send now</button><button data-act="edit">Edit & send</button><button data-act="discard" class="ghost">Discard</button></div>`;
    else if (m.state === "failed" || m.state === "offline_queued") actions = `<div class="owner-block when-mine"><button data-act="release">Retry</button><button data-act="discard" class="ghost">Discard</button></div>`;
    else if (mine && ["delivery_failed", "pending"].includes(m.state)) actions = `<div class="owner-block"><button data-act="redeliver">Deliver to agent</button></div>`;
    if (state.editing?.id === m.id && liveEditor) { log.append(liveEditor); prev = m; continue; }
    if (state.editing?.id === m.id) {
      el.classList.add("editing");
      el.innerHTML = `<textarea class="edit-box" rows="4">${esc(state.editing.text)}</textarea>
        <div class="owner-block when-mine" style="display:flex"><button data-act="edit-send" class="primary">Send edited</button><button data-act="edit-cancel" class="ghost">Cancel</button></div>`;
      log.append(el); prev = m; continue;
    }
    el.innerHTML = `<div class="bubble">${linkify(m.body)}</div>${actions}<div class="stamp">${tag}<span>${hhmm(at)}</span>${mine ? "" : ticks(m)}</div>`;
    log.append(el);
    prev = m;
  }
  if (!state.messages.length) {
    log.innerHTML = `<div class="empty"><p>No messages yet.</p><p class="hint">${c?.kind === "test" ? "Type below as the guest to start." : (c?.online === "none" ? "Waiting for them to come online in their Tox client." : "They're online. Their first message will appear here.")}</p></div>`;
  }
  if (focused && document.contains(focused)) { focused.focus(); focused.setSelectionRange(...sel); }
  if (!keepScroll || nearBottom) log.scrollTop = log.scrollHeight;
}

async function loadChat(id, keepScroll) {
  const r = await api("GET", `/api/contacts/${id}/messages`);
  if (state.current !== id) return;
  state.messages = r.messages;
  renderHead();
  renderLog(keepScroll);
}

function select(id) {
  state.current = id || null;
  document.getElementById("app").classList.toggle("chatting", !!id);
  $("#empty").hidden = !!id;
  $("#chat").hidden = !id;
  if (id) {
    state.messages = [];
    renderHead();
    loadChat(id).then(() => api("POST", `/api/contacts/${id}/seen`).catch(() => {}));
    try { localStorage.setItem("toxline.current", id); } catch (e) {}
  }
  renderContacts();
}

$("#log").addEventListener("click", async e => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  const id = b.closest(".msg").dataset.id;
  if (b.dataset.act === "edit" && state.editing) return;
  const m = state.messages.find(x => x.id === id);
  try {
    if (b.dataset.act === "release") await api("POST", `/api/messages/${id}/release`, {});
    if (b.dataset.act === "discard") await api("POST", `/api/messages/${id}/discard`);
    if (b.dataset.act === "redeliver") await api("POST", `/api/messages/${id}/redeliver`);
    if (b.dataset.act === "edit") {
      state.editing = { id, text: m.body };
      renderLog(true);
      const box = $(".edit-box"); box.focus(); box.setSelectionRange(box.value.length, box.value.length);
      box.oninput = () => (state.editing.text = box.value);
    }
    if (b.dataset.act === "edit-cancel") { state.editing = null; renderLog(true); return; }
    if (b.dataset.act === "edit-send") {
      const text = state.editing.text;
      if (!text.trim()) { toast("Message is empty"); return; }
      state.editing = null;
      try { await api("POST", `/api/messages/${id}/release`, { body: text }); }
      finally { await loadChat(state.current, true); }
    }
  } catch (err) { toast(err.message); }
});

// --------------------------------------------------------------- live feed
let refreshTimer = null;
async function refresh() {
  state.snap = await api("GET", "/api/state");
  renderMe(); renderRequests(); renderContacts();
  if (state.current) renderHead();
}
function scheduleRefresh() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 120); }

function connect() {
  const es = new EventSource(`/api/events`);
  es.onmessage = e => {
    const ev = JSON.parse(e.data);
    if (ev.kind === "typing") {
      state.typing[ev.contact_id] = ev.data.on;
      if (ev.contact_id === state.current) $("#typing").hidden = !ev.data.on;
      return;
    }
    if (ev.kind === "agent") return;
    if (ev.kind === "seen") return;
    if (ev.kind === "contact_deleted" && ev.contact_id === state.current) { location.hash = ""; toast("That guest was deleted"); }
    scheduleRefresh();
    if (ev.contact_id && ev.contact_id === state.current && (ev.kind === "message" || ev.kind === "contact_updated")) {
      clearTimeout(connect.t);
      connect.t = setTimeout(() => loadChat(state.current, true).then(() => {
        if (ev.kind === "message" && document.visibilityState === "visible") api("POST", `/api/contacts/${state.current}/seen`).catch(() => {});
      }), 60);
    }
    if (ev.kind === "friend_request") toast("New friend request");
    if (ev.kind === "thread_error") toast("Thread error: " + ev.data.error);
  };
  es.onerror = () => {
    state.offline = true;
    $("#me-dot").className = "dot"; $("#me-name").textContent = "Service offline, reconnecting…";
    if (state.current) renderHead();
  };
  es.onopen = () => { state.offline = false; refresh(); if (state.current) loadChat(state.current, true); };
}

// ----------------------------------------------------------------- actions
$("#me-id").onclick = () => {
  const id = state.snap?.self.tox_id;
  if (id) navigator.clipboard.writeText(id).then(() => toast("Agent Tox ID copied"));
};
$("#filter").oninput = e => { state.filter = e.target.value; renderContacts(); };
$("#show-archived").onchange = e => { state.showArchived = e.target.checked; renderContacts(); };
$("#btn-back").onclick = () => { location.hash = ""; };
$("#overlay").onchange = e => $("#log").classList.toggle("overlay-on", e.target.checked);
$("#log").classList.add("overlay-on");

$("#btn-hold").onclick = async () => {
  const c = contact();
  await api("POST", `/api/contacts/${c.id}/update`, { hold_outgoing: !c.hold_outgoing });
  await refresh();
};
$("#btn-open").onclick = async () => {
  try { const r = await api("POST", `/api/contacts/${state.current}/open`); toast(r.note || "Opening agent thread…"); }
  catch (e) { toast(e.message); }
};

const simText = $("#sim-text");
simText.addEventListener("input", () => { simText.style.height = "auto"; simText.style.height = Math.min(simText.scrollHeight, 200) + "px"; });
simText.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#sim-send").click(); } });
$("#sim-send").onclick = async () => {
  const body = simText.value.trim();
  if (!body) return;
  simText.value = ""; simText.style.height = "auto";
  try { await api("POST", `/api/contacts/${state.current}/simulate`, { body }); } catch (e) { toast(e.message); simText.value = body; }
};

async function fillThreads(select, current) {
  // New guests default to a fresh thread seeded with the current brief.
  select.innerHTML = current ? "" : `<option value="new" selected>＋ Create a new thread for them (seeded with the current brief)</option>`;
  try {
    const { threads } = await api("GET", "/api/threads");
    const bound = new Map();
    for (const c of state.snap.contacts.filter(c => c.thread_id && c.status !== "archived"))
      bound.set(c.thread_id, [...(bound.get(c.thread_id) || []), c.name]);
    for (const t of threads) {
      const o = document.createElement("option");
      o.value = t.id;
      const owners = (bound.get(t.id) || []).filter(n => !(t.id === current && n === contact()?.name));
      o.textContent = `${t.title || t.id}`.slice(0, 70) + (owners.length ? ` (shared with ${owners.join(", ")})` : "");
      select.append(o);
    }
  } catch (e) { /* listing threads is optional */ }
  if (current) { const n = document.createElement("option"); n.value = "new"; n.textContent = "＋ Create a new thread for them"; select.append(n); }
  if (current) {
    if (![...select.options].some(o => o.value === current)) {
      const o = document.createElement("option"); o.value = current; o.textContent = current; select.append(o);
    }
    select.value = current;
  }
}

function openNew(prefill = {}) {
  const f = $("#form-new");
  f.reset();
  $("#new-error").textContent = "";
  for (const [k, v] of Object.entries(prefill)) if (f.elements[k]) f.elements[k].value = v;
  const fromRequest = !!prefill.fromRequest;
  f.classList.toggle("from-request", fromRequest);
  f.elements.kind.forEach(r => (r.disabled = fromRequest));
  $("#new-title").textContent = prefill.returning ? `Restore ${prefill.returning}` : fromRequest ? "Set up guest from their request" : "Invite a guest";
  $("#new-ok").textContent = prefill.returning ? "Restore" : "Create";
  f.classList.toggle("returning", !!prefill.returning);
  f.elements.thread.required = true;
  const sync = () => {
    f.classList.toggle("tox-hidden", f.elements.kind.value !== "tox"); f.elements.tox_id.required = f.elements.kind.value === "tox";
    const consult = f.elements.role.value === "consult";
    $("#notes-label").textContent = consult ? "What should your agent find out? (it opens with this once they accept)" : "About them (the agent sees this)";
    f.elements.notes.placeholder = consult ? "e.g. How does their registry stop one certificate being claimed twice? Get the mechanism and sources." : "Who they are, what they care about, how deep to go…";
    f.elements.tox_id.placeholder = f.elements.role.value !== "person"
      ? "76 hex characters: the agent Tox ID shown at the top-left of their Toxline"
      : "76 hex characters from THEIR client (qTox: click their own name/avatar at top-left → Tox ID → Copy)";
    f.elements.greeting.placeholder = consult ? "Leave empty to use the agent greeting from Settings" : "Leave empty to use the greeting from Settings";
  };
  const shareNote = () => {
    const t = f.elements.thread.value, paste = (f.elements.thread_paste.value.match(/[0-9a-f-]{36}/i) || [""])[0].toLowerCase();
    const tid = paste || t;
    const names = state.snap.contacts.filter(c => c.thread_id === tid && c.status !== "archived").map(c => c.name);
    $("#share-note").hidden = !names.length;
    $("#share-note").textContent = names.length ? `That thread already talks to ${names.join(", ")}. They'll share it: the agent sees everyone's messages and picks who each reply goes to. Each person only sees what's sent to them.` : "";
  };
  f.elements.thread.onchange = shareNote;
  f.elements.kind.forEach(r => (r.onchange = sync)); f.elements.role.forEach(r => (r.onchange = sync)); sync();
  f.elements.thread_paste.oninput = () => { f.elements.thread.required = !f.elements.thread_paste.value.trim(); shareNote(); };
  shareNote();
  fillThreads(f.elements.thread, prefill.thread || undefined);
  $("#dlg-new").showModal();
}
$("#btn-new").onclick = () => openNew();
$("#form-new").addEventListener("submit", async e => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const f = e.target, btn = $("#new-ok");
  const body = Object.fromEntries(new FormData(f));
  const pasted = (body.thread_paste || "").match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  if (pasted) body.thread = pasted[0];
  else if ((body.thread_paste || "").trim()) { $("#new-error").textContent = "That doesn't look like a Codex thread ID."; return; }
  delete body.thread_paste;
  btn.disabled = true; btn.textContent = "Creating thread…";
  try {
    const c = await api("POST", "/api/contacts", body);
    $("#dlg-new").close();
    await refresh();
    location.hash = c.id;
    toast(c.thread_id ? `${c.name} is set up` : `${c.name} added, but the agent thread failed`);
  } catch (err) { $("#new-error").textContent = err.message; }
  finally { btn.disabled = false; btn.textContent = f.classList.contains("returning") ? "Restore" : "Create"; }
});

$("#btn-more").onclick = async () => {
  const c = contact(), f = $("#form-more");
  $("#more-title").textContent = c.name;
  $("#more-error").textContent = "";
  $("#more-facts").innerHTML = [
    ["Guest id", c.id], ["Kind", c.kind === "test" ? "Test guest" : "Tox contact"],
    ["Tox key", c.public_key], ["Their Tox name", c.tox_name || "—"], ["Agent thread", c.thread_id || "none"],
    ["Added", new Date(c.created_at * 1000).toLocaleString()],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
  f.elements.notes.value = c.notes || "";
  f.elements.role.value = c.role || "person";
  $("#btn-pause").textContent = c.status === "paused" ? "Resume" : "Pause";
  $("#btn-archive").textContent = c.status === "archived" ? "Unarchive" : "Archive";
  $("#btn-delete").hidden = c.status !== "archived";
  $("#btn-pause").hidden = c.status === "archived";
  await fillThreads(f.elements.thread, c.thread_id);
  $("#dlg-more").showModal();
};
$("#btn-pause").onclick = async () => {
  const c = contact();
  try { await api("POST", `/api/contacts/${c.id}/update`, { status: c.status === "paused" ? "active" : "paused" }); $("#dlg-more").close(); refresh(); }
  catch (e) { $("#more-error").textContent = e.message; }
};
$("#btn-archive").onclick = async () => {
  const c = contact();
  if (c.status !== "archived" && !(await ask(`Archive ${c.name}?`, "Their Tox friendship is removed and nothing reaches the agent. History stays; you can unarchive later.", "Archive"))) return;
  try { await api("POST", `/api/contacts/${c.id}/update`, { status: c.status === "archived" ? "active" : "archived" }); $("#dlg-more").close(); refresh(); }
  catch (e) { $("#more-error").textContent = e.message; }
};
$("#btn-delete").onclick = async () => {
  const c = contact();
  if (!(await ask(`Delete ${c.name} for good?`, "Their chat history in Toxline is erased. Their Codex thread is not touched.", "Delete"))) return;
  try { await api("POST", `/api/contacts/${c.id}/delete`); $("#dlg-more").close(); location.hash = ""; refresh(); }
  catch (e) { $("#more-error").textContent = e.message; }
};
$("#form-more").addEventListener("submit", async e => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const c = contact(), f = e.target;
  try {
    await api("POST", `/api/contacts/${c.id}/update`, { notes: f.elements.notes.value, role: f.elements.role.value });
    const t = f.elements.thread.value;
    if (t !== (c.thread_id || "new") || (t === "new" && c.thread_id)) {
      if (await ask(t === "new" ? "Start a fresh thread for this guest?" : "Move this guest to the selected thread?",
                    "Their future messages go there. The new thread gets a short note about who it's talking to.", "Move"))
        await api("POST", `/api/contacts/${c.id}/rebind`, { thread: t });
    }
    $("#dlg-more").close(); refresh();
  } catch (err) { $("#more-error").textContent = err.message; }
});

const SETTINGS = ["owner", "topic", "guide_name", "status_message", "library_map", "greeting", "agent_greeting", "agent_budget"];
$("#btn-settings").onclick = async () => {
  const f = $("#form-settings"), me = state.snap.self;
  $("#settings-facts").innerHTML = [["Agent Tox ID", me.tox_id || "Tox disabled"], ["Tox network", me.connection], ["Delivery", state.snap.ingress]]
    .map(([k, v]) => `<dt>${k}</dt><dd>${esc(v || "—")}</dd>`).join("");
  const [cfg, persona] = await Promise.all([api("GET", "/api/settings"), api("GET", "/api/persona")]);
  for (const k of SETTINGS) f.elements[k].value = cfg[k] || "";
  f.elements.persona.value = persona.text;
  f.dataset.persona = persona.text;
  $("#dlg-settings").showModal();
};
$("#form-settings").addEventListener("submit", async e => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const f = e.target;
  try {
    await api("POST", "/api/settings", Object.fromEntries(SETTINGS.map(k => [k, f.elements[k].value])));
    if (f.elements.persona.value !== f.dataset.persona) await api("POST", "/api/persona", { text: f.elements.persona.value });
    $("#dlg-settings").close(); toast("Settings saved"); refresh();
  } catch (err) { toast(err.message); }
});

window.addEventListener("hashchange", () => select(decodeURIComponent(location.hash.slice(1)) || null));
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && state.current) api("POST", `/api/contacts/${state.current}/seen`).catch(() => {}); });

(async function boot() {
  await refresh();
  connect();
  let start = decodeURIComponent(location.hash.slice(1));
  if (!start) { try { start = localStorage.getItem("toxline.current") || ""; } catch (e) {} }
  if (start && state.snap.contacts.some(c => c.id === start)) location.hash === "#" + start ? select(start) : (location.hash = start);
})();
setInterval(() => { if (state.snap) renderContacts(); }, 30000);

// Confirm dialog that works everywhere (window.confirm is blocked in some embedded browsers).
function ask(title, text, ok = "OK") {
  const d = $("#dlg-ask");
  $("#ask-title").textContent = title;
  $("#ask-text").textContent = text;
  $("#ask-ok").textContent = ok;
  $("#ask-ok").className = ["Archive", "Delete"].includes(ok) ? "danger-solid" : "primary";
  d.returnValue = "";
  d.showModal();
  return new Promise(res => d.addEventListener("close", () => res(d.returnValue === "ok"), { once: true }));
}
