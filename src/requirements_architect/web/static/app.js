"use strict";
// All data from the server is inserted with textContent (never innerHTML).
const API = "/api/v1";
const app = document.getElementById("app");
const who = document.getElementById("who");
let token = null;
try { token = sessionStorage.getItem("ra_token"); } catch (e) { token = null; }
let pollTimer = null;

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "onclick" || k === "onsubmit") el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, String(v));
  }
  for (const kid of kids.flat()) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}
function setView(...nodes) { clearTimeout(pollTimer); app.replaceChildren(...nodes); }

async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (token) headers["Authorization"] = "Bearer " + token;
  if (opts.body && typeof opts.body !== "string") { opts.body = JSON.stringify(opts.body); headers["Content-Type"] = "application/json"; }
  const r = await fetch(API + path, Object.assign({}, opts, { headers }));
  if (r.status === 401 && token) { logout(false); throw new Error("Please sign in again."); }
  if (!r.ok) {
    let msg = r.status + " " + r.statusText;
    try { const j = await r.json(); const d = j.detail ?? j.error; msg = typeof d === "string" ? d : JSON.stringify(d); } catch (e) { /* keep default */ }
    throw new Error(msg);
  }
  return r;
}
const json = async (path, opts) => (await api(path, opts)).json();

function errBox(e) { return h("p", { class: "err", role: "alert" }, e.message || String(e)); }
async function guarded(box, fn) { box.replaceChildren(); try { await fn(); } catch (e) { box.replaceChildren(errBox(e)); } }

function logout(call = true) {
  if (call && token) api("/auth/logout", { method: "POST" }).catch(() => {});
  token = null; try { sessionStorage.removeItem("ra_token"); } catch (e) { /* ignore */ }
  who.replaceChildren(); loginView();
}

function loginView() {
  const err = h("div");
  const u = h("input", { id: "u", autocomplete: "username", required: true });
  const p = h("input", { id: "p", type: "password", autocomplete: "current-password", required: true });
  setView(h("form", { onsubmit: async (ev) => {
    ev.preventDefault();
    await guarded(err, async () => {
      const r = await json("/auth/login", { method: "POST", body: { username: u.value, password: p.value } });
      token = r.token; try { sessionStorage.setItem("ra_token", token); } catch (e) { /* ignore */ }
      await boot();
    });
  } }, h("h2", {}, "Sign in"), h("label", { for: "u" }, "Username"), u, h("label", { for: "p" }, "Password"), p,
  h("p", {}, h("button", { type: "submit" }, "Sign in")), err));
}

async function projectsView() {
  const err = h("div"), list = h("div");
  const name = h("input", { id: "n", maxlength: 200, required: true });
  const stmt = h("textarea", { id: "s", maxlength: 20000, required: true });
  setView(h("h2", {}, "Your projects"), list,
    h("h2", {}, "New project"),
    h("form", { onsubmit: async (ev) => {
      ev.preventDefault();
      await guarded(err, async () => {
        const p = await json("/projects", { method: "POST", body: { name: name.value, problem_statement: stmt.value } });
        projectView(p.id);
      });
    } }, h("label", { for: "n" }, "Name"), name,
    h("label", { for: "s" }, "Problem statement (at least 10 characters)"), stmt,
    h("p", {}, h("button", { type: "submit" }, "Create project")), err));
  await guarded(err, async () => {
    const ps = await json("/projects");
    list.replaceChildren(...(ps.length ? ps.map((p) => h("div", { class: "card" },
      h("a", { href: "#", onclick: (e) => { e.preventDefault(); projectView(p.id); } }, p.name), " ",
      h("span", { class: "tag" }, p.status))) : [h("p", { class: "muted" }, "No projects yet.")]));
  });
}

async function download(path, filename) {
  const blob = await (await api(path)).blob();
  const a = h("a", { href: URL.createObjectURL(blob), download: filename });
  document.body.append(a); a.click(); a.remove();
}

async function projectView(id) {
  const top = h("div"), err = h("div"), body = h("div");
  setView(h("p", {}, h("a", { href: "#", onclick: (e) => { e.preventDefault(); projectsView(); } }, "← All projects")), top, err, body);
  const act = (label, fn, cls) => h("button", { class: cls || "", onclick: () => guarded(err, async () => { await fn(); await refresh(); }) }, label);
  async function refresh() {
    clearTimeout(pollTimer);
    const [p, st] = await Promise.all([json(`/projects/${id}`), json(`/projects/${id}/status`)]);
    top.replaceChildren(h("h2", {}, p.name), h("p", {}, h("span", { class: "tag" }, st.status), " ",
      st.job ? h("span", { class: st.job.state === "failed" ? "err" : "muted" }, `${st.job.kind}: ${st.job.state}` + (st.job.error ? ` - ${st.job.error}` : "")) : ""),
      h("details", {}, h("summary", {}, "Problem statement"), h("pre", {}, p.problem_statement)));
    const parts = [];
    const running = st.job && st.job.state === "running";
    if (st.status === "created") parts.push(act("Start analysis", () => json(`/projects/${id}/start`, { method: "POST" })));
    if (st.status === "failed") parts.push(act("Retry", () => json(`/projects/${id}/retry`, { method: "POST" })));
    const qs = st.workflow ? st.workflow.open_questions : [];
    if (qs.length) parts.push(questionsForm(id, qs, err, refresh));
    if (["specifications_complete", "audit_complete", "documents_complete"].includes(st.status)) {
      parts.push(h("h2", {}, "Review and package"),
        act("Run audit", () => json(`/projects/${id}/audit`, { method: "POST" }), "secondary"),
        act("Generate documents", () => json(`/projects/${id}/documents`, { method: "POST" })));
      parts.push(await auditBox(id), await approvalsBox(id, err, refresh), await documentsBox(id));
    }
    parts.push(await outputsBox(id), await activityBox(id));
    body.replaceChildren(...parts);
    if (running) pollTimer = setTimeout(() => guarded(err, refresh), 3000);
  }
  await guarded(err, refresh);
}

function questionsForm(id, qs, err, refresh) {
  const fields = qs.map((q) => {
    const input = h("textarea", { id: "q" + q.id, required: q.blocking, maxlength: 4000 });
    const accept = h("input", { type: "checkbox", id: "a" + q.id });
    const rec = q.recommended_interpretation;
    return { q, input, accept, node: h("div", { class: "card" },
      h("label", { for: "q" + q.id }, `${q.id}: ${q.question}`), h("p", { class: "muted" }, `Why asked: ${q.reason}`),
      q.options && q.options.length ? h("p", { class: "muted" }, "Options: " + q.options.join(" | ")) : "",
      rec ? h("p", {}, "Suggested: ", rec, " ", h("label", { for: "a" + q.id }, accept, " accept the suggestion")) : "", input) };
  });
  return h("form", { onsubmit: async (ev) => {
    ev.preventDefault();
    const answers = fields.map((f) => ({ question_id: f.q.id, answer: f.input.value.trim() || (f.accept.checked ? f.q.recommended_interpretation : ""), accepted_recommendation: f.accept.checked })).filter((a) => a.answer);
    await guarded(err, async () => { await json(`/projects/${id}/answers`, { method: "POST", body: { answers } }); await refresh(); });
  } }, h("h2", {}, "Questions that need your answer"), ...fields.map((f) => f.node), h("button", { type: "submit" }, "Submit answers"));
}

async function auditBox(id) {
  const box = h("div", {}, h("h2", {}, "Audit"));
  try {
    const a = (await json(`/projects/${id}/audit`)).report;
    box.append(h("p", {}, "Verdict: ", h("strong", {}, a.verdict.replace("_", " ")), " (never an approval)"),
      h("p", { class: "muted" }, `${a.findings.length} finding(s); LLM review: ${a.llm_review}`),
      ...a.findings.slice(0, 20).map((f) => h("div", { class: "card" }, h("span", { class: "tag" }, f.severity), " ", f.code, ": ", f.message)),
      ...a.limitations.map((l) => h("p", { class: "warn" }, l)));
  } catch (e) { box.append(h("p", { class: "muted" }, "Not run yet.")); }
  return box;
}

async function approvalsBox(id, err, refresh) {
  const box = h("div", {}, h("h2", {}, "Approvals"));
  const reqs = await json(`/projects/${id}/approvals`);
  if (!reqs.length) box.append(h("p", { class: "muted" }, "Nothing needs approval."));
  for (const r of reqs) {
    const note = h("input", { "aria-label": "Note for " + r.ref, maxlength: 2000, placeholder: "Note (required to request a revision)" });
    const decide = (decision) => h("button", { class: decision === "reject" ? "danger" : "secondary", disabled: r.state === "approved" && decision === "approve",
      onclick: () => guarded(err, async () => { await json(`/projects/${id}/approvals`, { method: "POST", body: { stage_id: r.stage_id, ref: r.ref, fingerprint: r.fingerprint, decision, note: note.value } }); await refresh(); }) }, decision.replace("_", " "));
    const list = (title, xs) => xs.length ? h("p", { class: "muted" }, title + ": " + xs.join("; ")) : "";
    box.append(h("div", { class: "card" }, h("strong", {}, `${r.ref} `), h("span", { class: "tag" }, r.state), h("p", {}, r.decision),
      h("p", { class: "muted" }, "Reason: " + r.reason), list("Advantages", r.advantages), list("Disadvantages", r.disadvantages),
      list("Alternatives", r.alternatives), list("Consequences", r.consequences), list("Affected documents", r.affected_documents),
      r.note ? h("p", {}, "Note: " + r.note) : "", note, h("div", {}, decide("approve"), decide("reject"), r.kind === "nfr_target" ? "" : decide("request_revision"))));
  }
  return box;
}

async function documentsBox(id) {
  const box = h("div", {}, h("h2", {}, "Documents"));
  try {
    const m = await json(`/projects/${id}/documents`);
    box.append(h("p", {}, `Package v${m.package_version}, ${m.files.length} files. ${m.approval_status}`),
      h("button", { onclick: () => download(`/projects/${id}/documents/download.zip`, "PROJECT_DOCUMENTATION.zip").catch((e) => box.append(errBox(e))) }, "Download ZIP"));
    const pre = h("pre", { hidden: true });
    const sel = h("select", { "aria-label": "Document", onchange: async () => { if (!sel.value) return; pre.hidden = false; pre.textContent = await (await api(`/projects/${id}/documents/files/${sel.value}`)).text(); } },
      h("option", { value: "" }, "View a document…"), ...m.files.filter((f) => !f.path.endsWith(".pdf")).map((f) => h("option", { value: f.path }, f.path)));
    box.append(sel, pre);
  } catch (e) { box.append(h("p", { class: "muted" }, "Not generated yet.")); }
  return box;
}

async function outputsBox(id) {
  const outs = await json(`/projects/${id}/outputs`);
  const pre = h("pre", { hidden: true });
  const sel = h("select", { "aria-label": "Stage output", onchange: async () => { if (!sel.value) return; const o = await json(`/projects/${id}/outputs/${sel.value}`); pre.hidden = false; pre.textContent = JSON.stringify(o, null, 2); } },
    h("option", { value: "" }, "View a stage output…"), ...Object.entries(outs).map(([k, v]) => h("option", { value: k }, `${k} (versions: ${v.join(", ")})`)));
  return h("div", {}, h("h2", {}, "Stage outputs"), sel, pre);
}

async function activityBox(id) {
  const rows = await json(`/projects/${id}/activity`);
  return h("details", {}, h("summary", {}, `Activity (${rows.length})`), ...rows.map((r) => h("p", { class: "muted" }, `${r.timestamp} ${r.action}`)));
}

async function boot() {
  if (!token) return loginView();
  try {
    const me = await json("/auth/me");
    who.replaceChildren(me.username + " ", h("button", { class: "secondary", onclick: () => logout() }, "Sign out"));
    await projectsView();
  } catch (e) { loginView(); }
}
boot();
