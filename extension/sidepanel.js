// Neighbourhood X-Ray side panel.
// Renders a report that follows shared/report.example.json. The example is
// bundled as data/report.example.json (keep it identical to shared/).

const BACKEND = "http://localhost:8000";
const EXAMPLE_URL = "data/report.example.json";

const $ = (id) => document.getElementById(id);

// Small DOM builder; text is always set via textContent (never innerHTML).
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const inr = (n) => (n == null ? "—" : "₹" + Number(n).toLocaleString("en-IN"));
const kInr = (n) => (n == null ? "—" : "₹" + Math.round(n / 1000) + "k");
const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : null);

function sourceLink(url, label) {
  const href = safeUrl(url);
  if (!href) return h("span", { class: "src mono muted" }, label || "no source");
  return h("a", { class: "src mono", href, target: "_blank", rel: "noopener noreferrer" }, (label || "source") + " ↗");
}

const STATUS_TEXT = { verified: "Verified", no_reports: "No reports", stub: "Demo", could_not_verify: "Could not verify" };

function statusChip(status) {
  return h("span", { class: `chip status-${status}` }, STATUS_TEXT[status] || status);
}

function fmtDate(d) {
  if (!d) return "";
  const t = new Date(`${d}T00:00:00`);
  return isNaN(t) ? d : t.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

// One clickable row per piece of evidence: date · short title · source label · link.
function evidenceRow(e) {
  return h("li", { class: "ev" },
    e.date ? h("span", { class: "ev-date mono" }, fmtDate(e.date)) : null,
    h("span", { class: "ev-title" }, e.title || ""),
    h("span", { class: "ev-label" }, e.label || ""),
    sourceLink(e.source_url, "open"));
}

function openCheck(id) {
  document.querySelector('.tab[data-tab="overview"]')?.click();
  const d = document.getElementById(`check-${id}`);
  if (!d) return;
  d.open = true;
  d.scrollIntoView({ behavior: "smooth", block: "start" });
  d.classList.add("flash");
  setTimeout(() => d.classList.remove("flash"), 1200);
}

// ---------- tabs ----------
function showTab(name, scroll = true) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${name}`));
  if (!scroll) return;
  // Start the tab's content right under the sticky header + tab bar (the banner counts as content).
  const banner = $("data-banner");
  const target = banner.classList.contains("hidden") ? $(`view-${name}`) : banner;
  const top = target.getBoundingClientRect().top + window.scrollY - $("sticky-top").offsetHeight - 8;
  window.scrollTo({ top: Math.max(0, top) });
}

document.querySelectorAll(".tab").forEach((btn) => btn.addEventListener("click", () => showTab(btn.dataset.tab)));

// ---------- rendering ----------
function render(report) {
  const mode = report.data_mode;
  const pill = $("mode-pill");
  pill.textContent = { example: "EXAMPLE", stub: "DEMO", live: "LIVE", cache: "CACHED" }[mode] || mode.toUpperCase();
  pill.className = `mode-pill mode-${mode}`;

  const banner = $("data-banner");
  banner.className = `data-banner banner-${mode}`;
  banner.textContent =
    mode === "example"
      ? "Example data — illustrative only, not verified findings."
      : mode === "stub"
      ? "Demo results — the backend ran in stub mode. Nothing here is a real finding."
      : mode === "cache"
      ? `Replayed from a saved live scan (${report.cached_from?.generated_at || "earlier"}) — not re-checked now.`
      : "";
  banner.classList.toggle("hidden", mode === "live");

  const l = report.listing || {};
  // Header: the parent area (what the checks matched on); the compact line keeps the full name.
  $("listing-sub").textContent = [report.area || l.locality, l.bhk ? `${l.bhk} BHK` : null].filter(Boolean).join(" · ") || "No listing";
  currentArea = report.area || null;

  const rc = report.rent_compare || {};
  $("rent-badge").textContent = rc.premium_percent != null ? `${rc.premium_percent > 0 ? "+" : ""}${Math.round(rc.premium_percent)}%` : "";
  const mentions = report.residents?.status === "verified" ? report.residents.total_mentions : 0;
  $("residents-badge").textContent = mentions ? String(mentions) : "";

  renderOverview(report);
  renderRent(report);
  renderResidents(report);
  renderAsk(report);
}

function verdictLevel(score) {
  if (score == null) return "unknown";
  if (score >= 70) return "good";
  if (score >= 50) return "watch";
  return "risk";
}

function scoreRing(score) {
  const pct = score == null ? 0 : Math.max(0, Math.min(100, score));
  const ring = h("div", { class: "ring", style: `--pct:${pct}` },
    h("div", { class: "ring-inner" }, h("div", { class: "ring-num mono" }, score ?? "–"), h("div", { class: "ring-of mono" }, "/ 100"))
  );
  return ring;
}

function renderOverview(r) {
  const v = $("view-overview");
  v.replaceChildren();
  const level = verdictLevel(r.score);

  v.append(
    h("section", { class: "card hero" },
      r.data_mode === "example" ? h("div", { class: "example-tag" }, "Example data — illustrative, not a real scan") : null,
      h("div", { class: "hero-row" },
        scoreRing(r.score),
        h("div", {},
          h("span", { class: `verdict verdict-${level}` }, (level === "good" ? "✓ " : "⚠ ") + (r.verdict || "")),
          // No score: say which checks could not be verified instead of implying a verdict.
          r.score == null && (r.unverified_checks || []).length
            ? h("p", { class: "summary" }, "Not verified: ", h("b", {}, r.unverified_checks.join(", ")), ".")
            : null,
          h("p", { class: "summary" }, r.summary || "")
        )
      ),
      h("div", { class: "hero-foot" },
        h("span", {}, "Checked ", h("b", { class: "mono" }, r.sources_count ?? 0), " sources",
          r.duration_seconds != null ? ` · ${Math.round(r.duration_seconds)}s` : ""),
        h("span", { class: "muted" }, "Provisional scoring")
      )
    )
  );

  if (Array.isArray(r.sources) && r.sources.length) {
    v.append(
      h("section", { class: "card" },
        h("div", { class: "label-row" }, h("span", { class: "label" }, "Sources checked")),
        h("div", { class: "pills" }, r.sources.map((s) => {
          if (!s.check_id) return h("span", { class: "pill" }, h("b", { class: "mono" }, s.count), " ", s.label);
          // Clicking a source pill jumps to that check and opens its evidence rows.
          const b = h("button", { class: "pill pill-link", title: "Show these sources" }, h("b", { class: "mono" }, s.count), " ", s.label, " ↓");
          b.addEventListener("click", () => openCheck(s.check_id));
          return b;
        }))
      )
    );
  }

  v.append(
    h("section", { class: "card" },
      h("div", { class: "label-row" }, h("span", { class: "label" }, "Area scores")),
      (r.area_scores || []).map((a) => {
        const lvl = a.status === "could_not_verify" ? "unknown" : a.level || "unknown";
        const partial = a.confidence === "partial";
        // "No reports" from a source we could only partly read is not a confident 100/100.
        const hideScore = partial && a.status === "no_reports";
        return h("div", { class: "area" },
          h("div", { class: "area-row" },
            h("span", { class: "area-label" }, a.label),
            h("span", { class: "area-right" },
              a.status === "stub" || a.status === "no_reports" ? statusChip(a.status) : null,
              partial ? h("span", { class: "chip chip-partial" }, "Partial data") : null,
              hideScore ? null : h("span", { class: `chip lvl-${lvl}` }, a.tag || STATUS_TEXT[a.status] || ""),
              h("span", { class: "mono area-score" },
                a.score == null || hideScore ? "—" : [a.score, h("span", { class: "muted" }, "/100")])
            )
          ),
          h("div", { class: "track" }, h("div", { class: hideScore ? "fill partial" : `fill lvl-${lvl}`, style: `width:${hideScore ? 100 : a.score ?? 0}%` })),
          partial && a.partial_note ? h("div", { class: "partial-note" }, a.partial_note) : null
        );
      })
    )
  );

  const list = (items, cls, title) =>
    h("section", { class: `card half ${cls}` },
      h("div", { class: "half-title" }, title),
      items.length
        ? items.map((i) => h("div", { class: "finding" }, h("div", {}, i.text), sourceLink(i.source_url, i.source_label)))
        : h("div", { class: "muted" }, "Nothing yet")
    );
  v.append(h("div", { class: "two-col" }, list(r.good || [], "good", "✓ What's good"), list(r.watch_out || [], "watch", "! Watch out")));

  v.append(
    h("section", { class: "card" },
      h("div", { class: "label-row" }, h("span", { class: "label" }, "Checks")),
      (r.checks || []).map((c) => {
        const rows = c.evidence || c.findings || [];
        // Checks with hits start open so every claim's link is one glance away.
        const hasHits = c.status === "verified" && ((c.findings || []).length || rows.length);
        return h("details", { class: "check", id: `check-${c.id}`, open: hasHits ? "" : null },
          h("summary", {}, h("span", {}, c.headline), statusChip(c.status)),
          rows.length ? h("ul", { class: "evidence" }, rows.map(evidenceRow)) : null,
          c.partial_note ? h("div", { class: "partial-note" }, c.partial_note) : null,
          h("ul", { class: "check-notes" }, (c.details || []).filter((d) => !rows.some((e) => e.source_url && d.includes(e.source_url))).map((d) => h("li", {}, d))),
          h("div", { class: "check-foot" }, sourceLink(c.source_url), h("span", { class: "mono muted" }, c.fetched_at || ""))
        );
      })
    )
  );
}

function renderRent(r) {
  const v = $("view-rent");
  v.replaceChildren();
  const rc = r.rent_compare || {};
  const rent = rc.listing_rent ?? r.listing?.rent;

  if (rc.status === "could_not_verify" || !rc.fair_range) {
    v.append(
      h("section", { class: "card" },
        h("div", { class: "label-row" }, h("span", { class: "label" }, "Rent comparison"), statusChip("could_not_verify")),
        h("p", { class: "muted" }, "Rent comparison could not be verified for this scan. No comparable listings were fetched.")
      )
    );
    return;
  }

  const above = rc.premium_percent != null && rc.premium_percent > 0;
  v.append(
    h("section", { class: "card hero" },
      h("div", { class: "label-row" },
        h("span", { class: "label" }, `Is ${inr(rent)} fair?`),
        rc.premium_percent != null ? h("span", { class: `chip lvl-${above ? "risk" : "good"} mono` }, `${above ? "+" : ""}${rc.premium_percent}%`) : null
      ),
      h("h2", { class: "serif" }, above ? "Priced above the area." : "Priced within the area."),
      h("p", { class: "ink2" }, `Similar ${r.listing?.bhk ?? ""} BHKs rent for `, h("b", { class: "mono" }, inr(rc.median)), " on average."),
      h("div", { class: "stats" },
        h("div", { class: "stat" }, h("div", { class: "label" }, "Fair band"), h("div", { class: "mono stat-v" }, `${kInr(rc.fair_range.low)}–${Math.round(rc.fair_range.high / 1000)}k`)),
        h("div", { class: "stat" }, h("div", { class: "label" }, "Monthly extra"), h("div", { class: "mono stat-v risk" }, rc.monthly_extra != null ? "+" + inr(rc.monthly_extra) : "—")),
        h("div", { class: "stat" }, h("div", { class: "label" }, "1-year overpay"), h("div", { class: "mono stat-v risk" }, inr(rc.yearly_overpay)))
      )
    )
  );

  if (rc.spread && rc.spread.max > rc.spread.min) {
    const pos = (x) => ((x - rc.spread.min) / (rc.spread.max - rc.spread.min)) * 100;
    v.append(
      h("section", { class: "card" },
        h("div", { class: "label-row" }, h("span", { class: "label" }, `Rent spread · n = ${rc.spread.n}`)),
        h("div", { class: "spread" },
          h("div", { class: "spread-band", style: `left:${pos(rc.fair_range.low)}%;width:${pos(rc.fair_range.high) - pos(rc.fair_range.low)}%` }),
          rent != null ? h("div", { class: "spread-marker", style: `left:${Math.min(100, Math.max(0, pos(rent)))}%` }, h("span", { class: "mono" }, `${kInr(rent)} · this flat`)) : null
        ),
        h("div", { class: "spread-axis mono muted" }, h("span", {}, kInr(rc.spread.min)), h("span", {}, `fair ${kInr(rc.fair_range.low)}–${Math.round(rc.fair_range.high / 1000)}k`), h("span", {}, kInr(rc.spread.max)))
      )
    );
  }

  const portals = rc.portals || [];
  if (portals.length) {
    const max = Math.max(...portals.map((p) => p.median || 0));
    const min = Math.min(...portals.map((p) => p.median || Infinity));
    v.append(
      h("section", { class: "card" },
        h("div", { class: "label-row" }, h("span", { class: "label" }, "Median across portals")),
        portals.map((p) =>
          h("div", { class: "portal" },
            h("div", { class: "area-row" },
              h("span", {}, h("b", {}, p.name), p.median === min ? h("span", { class: "chip lvl-good" }, "Lowest") : null),
              h("span", { class: "mono" }, inr(p.median))
            ),
            h("div", { class: "portal-sub" }, h("span", { class: "mono muted" }, `${p.listings} listings`), sourceLink(p.source_url)),
            h("div", { class: "track" }, h("div", { class: "fill ink", style: `width:${max ? (p.median / max) * 75 : 0}%` }))
          )
        )
      )
    );
  }

  const c = rc.cheapest_comparable;
  if (c) {
    v.append(
      h("section", { class: "card value-card" },
        h("div", { class: "label-row" },
          h("span", { class: "label" }, "Better-value flat nearby"),
          c.monthly_saving ? h("span", { class: "label good-text" }, `Save ${inr(c.monthly_saving)}/mo`) : null
        ),
        h("div", { class: "mono value-title" }, `${c.bhk} BHK${c.area_sqft ? ` · ${c.area_sqft.toLocaleString("en-IN")} sq ft` : ""} · ${inr(c.rent)}`),
        h("div", { class: "ink2" }, [c.locality, c.distance_m ? `${c.distance_m} m away` : null, c.note].filter(Boolean).join(" · ")),
        sourceLink(c.source_url, `Open listing on ${c.portal || "portal"}`)
      )
    );
  }
}

function renderResidents(r) {
  const v = $("view-residents");
  v.replaceChildren();
  const res = r.residents || {};
  // Which sites were read and which blocked us (never worked around).
  const sitesLine = (res.sources || []).length
    ? h("div", { class: "res-sources" }, res.sources.map((s) =>
        h("span", { class: `chip ${s.status === "ok" ? "status-verified" : "status-could_not_verify"}`, title: s.note || "" },
          s.status === "ok" ? `${s.site} ✓ ${s.threads} thread${s.threads === 1 ? "" : "s"}` : `${s.site}: could not verify`)))
    : null;
  const head = (chip) => h("div", { class: "label-row" }, h("span", { class: "label" }, `Residents · ${res.place || ""}`), chip);

  if (res.status !== "verified" || !(res.themes || []).length) {
    const noReports = res.status === "no_reports";
    v.append(h("section", { class: "card" },
      head(statusChip(noReports ? "no_reports" : "could_not_verify")),
      h("p", { class: "muted" }, noReports ? "No resident reports found for this area in the past 12 months."
        : res.note || "Resident posts could not be checked for this scan."),
      sitesLine));
    return;
  }
  const max = Math.max(...res.themes.map((t) => t.mentions));
  v.append(
    h("section", { class: "card" },
      head(h("span", { class: "label" }, `${res.total_mentions} threads · ${res.window || ""}`)),
      sitesLine,
      res.themes.map((t) =>
        h("div", { class: "theme" }, h("span", {}, t.label),
          h("div", { class: "track" }, h("div", { class: `fill ${t.sentiment === "positive" ? "lvl-good" : "lvl-risk"} soft`, style: `width:${(t.mentions / max) * 100}%` })),
          h("span", { class: "mono" }, t.mentions))
      ),
      h("p", { class: "muted small" }, "Mentions = threads that bring up the theme. Not used in the score.")
    ),
    h("section", { class: "card" },
      h("div", { class: "label-row" }, h("span", { class: "label" }, "In their words"), h("span", { class: "label" }, "sentiment: automatic")),
      (res.quotes || []).length
        ? res.quotes.map((q) =>
            h("blockquote", { class: `quote theme-${q.theme} sent-${q.sentiment}` },
              h("p", { class: "serif" }, `“${q.text}”`),
              h("div", { class: "quote-foot" },
                h("span", { class: "mono muted" }, `${q.source} · ${q.age || fmtDate(q.posted_at)}`),
                h("span", { class: `chip sent-chip sent-${q.sentiment}` }, q.sentiment),
                sourceLink(q.source_url))))
        : h("p", { class: "muted" }, "No quotable sentences in the posts found."),
      res.note ? h("p", { class: "muted small" }, res.note) : null
    )
  );
}

const ASK_CHIPS = ["Is water bad here?", "Any power cuts recently?", "Is the rent fair?", "Does it flood?"];
let askState = { scanId: null, log: [], extraOwnerQs: [], checked: new Set() };
const STATE_TAG = { verified: ["Verified", "ok"], no_reports: ["No reports", "nr"], could_not_verify: ["Could not verify", "cnv"], stub: ["Demo", "nr"] };

function ownerItems(r) {
  const base = (r.owner_questions || []).length
    ? r.owner_questions.map((o) => ({ text: o.text, from: `From: ${o.from}` }))
    : (r.questions_for_owner || []).map((q) => ({ text: q, from: "From: this scan" }));
  const seen = new Set(base.map((o) => o.text));
  return [...base, ...askState.extraOwnerQs.filter((q) => !seen.has(q)).map((q) => ({ text: q, from: "From your question", isNew: true }))];
}

function answerBubble(m) {
  if (m.role === "user") return h("div", { class: "ask-q-bubble" }, m.text);
  const tags = (m.states || []).map((s) => {
    const [txt, cls] = STATE_TAG[s.status] || [s.status, "nr"];
    return h("span", { class: `ask-tag ${cls}`, title: s.label }, txt);
  });
  const links = (m.sources || []).map((s) => sourceLink(s.url, s.label));
  return h("div", { class: `ask-a${m.inScan ? "" : " miss"}${m.pending ? " pending" : ""}` },
    m.inScan || m.pending ? h("div", {}, m.text) : h("div", {}, h("b", {}, m.text.split(".")[0] + "."), m.text.split(".").slice(1).join(".")),
    tags.length || links.length ? h("div", { class: "ask-src" }, tags, links) : null,
    m.addedOwner ? h("div", { class: "ask-added" }, "+ Added to \u201cAsk the owner\u201d") : null);
}

function renderAsk(r) {
  const v = $("view-ask");
  v.replaceChildren();
  // A real scan (live/stub/cache) has a backend scan id; the bundled example doesn't.
  const scanId = r.data_mode === "example" ? null : r.scan_id;
  if (askState.scanId !== scanId) askState = { scanId, log: [], extraOwnerQs: [], checked: new Set() };
  const nChecks = (r.checks || []).length + (r.residents && r.residents.sources ? 1 : 0);

  const input = h("input", { type: "text", id: "ask-input", placeholder: "e.g. Is there water trouble in summer?", maxlength: "500", autocomplete: "off" });
  const send = h("button", { class: "ask-send", id: "ask-send", type: "button" }, "Ask");
  const submit = () => askQuestion(r, input.value);
  send.addEventListener("click", submit);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  if (!scanId) { input.disabled = true; send.disabled = true; }

  const thread = askState.log.length ? h("div", { class: "ask-thread", id: "ask-thread" }, askState.log.map(answerBubble)) : null;
  v.append(
    h("section", { class: "card ask-card" },
      h("div", { class: "label-row" }, h("span", { class: "label" }, "Ask about this area")),
      h("p", { class: "ask-hint" }, scanId
        ? `Answers come only from this scan's ${nChecks} checks, with sources.`
        : "Run or replay a scan to ask about it."),
      h("div", { class: "ask-composer" }, input, send),
      h("div", { class: "chips" }, ASK_CHIPS.map((c) => {
        const b = h("button", { class: "chip-btn", type: "button" }, c);
        b.disabled = !scanId;
        b.addEventListener("click", () => askQuestion(r, c));
        return b;
      })),
      thread),
    h("section", { class: "card owner-card" },
      (() => {
        const items = ownerItems(r);
        return [
          h("div", { class: "label-row" }, h("span", { class: "label" }, "Ask the owner · checklist"), h("span", { class: "label mono" }, items.length)),
          items.length
            ? h("ul", { class: "owner-list" }, items.map((o) => {
                const box = h("input", { type: "checkbox" });
                box.checked = askState.checked.has(o.text);
                box.addEventListener("change", () => (box.checked ? askState.checked.add(o.text) : askState.checked.delete(o.text)));
                return h("li", {}, box, h("span", {}, o.text, o.isNew ? h("span", { class: "owner-new" }, "NEW") : null, h("small", {}, o.from)));
              }))
            : h("p", { class: "muted" }, "No questions yet."),
        ];
      })()
    )
  );
}

function scrollToNewestAnswer() {
  const t = $("ask-thread");
  const last = t?.lastElementChild;
  if (!last) return;
  const bottom = last.getBoundingClientRect().bottom;
  if (bottom > window.innerHeight - 12 || last.getBoundingClientRect().top < $("sticky-top").offsetHeight) {
    last.scrollIntoView({ block: "end", behavior: "smooth" });
  }
}

async function askQuestion(r, question) {
  const q = (question || "").trim();
  if (q.length < 2 || !askState.scanId) return;
  const pending = { role: "bot", text: "Checking this scan…", inScan: true, pending: true };
  askState.log.push({ role: "user", text: q }, pending);
  renderAsk(r);
  scrollToNewestAnswer();
  try {
    const res = await fetch(`${BACKEND}/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scan_id: askState.scanId, question: q }) });
    if (!res.ok) throw new Error(res.status === 404 ? "this scan is no longer on the backend — run or replay it again" : `HTTP ${res.status}`);
    const a = await res.json();
    Object.assign(pending, { text: a.answer, inScan: a.in_scan, sources: a.sources, states: a.check_states || [], pending: false });
    // Only real "not in this scan" answers add a question; errors don't.
    if (!a.in_scan && a.method !== "error" && a.owner_question && !askState.extraOwnerQs.includes(a.owner_question)) {
      askState.extraOwnerQs.push(a.owner_question);
      pending.addedOwner = true;
    }
  } catch (err) {
    Object.assign(pending, { text: `Couldn't ask: ${err.message}.`, inScan: false, pending: false });
  }
  renderAsk(r);
  scrollToNewestAnswer();
  $("ask-input")?.focus();
}

// ---------- listing extraction ----------
const LISTING_URL_RE = /^https:\/\/www\.(nobroker\.in|magicbricks\.com)\//;

async function readListing(tab) {
  try {
    return await chrome.tabs.sendMessage(tab.id, { type: "xray:extractListing" });
  } catch (err) {
    // Tabs opened before the extension (re)loaded have no content script: inject it once, retry once.
    if (!/receiving end|could not establish connection/i.test(String(err?.message || err))) throw err;
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    return await chrome.tabs.sendMessage(tab.id, { type: "xray:extractListing" });
  }
}

async function loadListingFromTab() {
  const state = $("extract-state");
  if (source) return; // never change the form while a scan is running
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !LISTING_URL_RE.test(tab.url || "")) throw new Error("not a listing tab");
    const res = await readListing(tab);
    if (!res?.ok) throw new Error(res?.error || "no response");
    const l = res.listing;
    const changed = window.__listing?.url && window.__listing.url !== l.listing_url;
    if (l.locality) $("in-locality").value = l.locality;
    if (l.rent) $("in-rent").value = l.rent;
    if (l.bhk) $("in-bhk").value = l.bhk;
    window.__listing = { url: l.listing_url, text: l.listing_text, source: l.source };
    state.textContent = l.locality ? `From ${l.source === "magicbricks" ? "MagicBricks" : "NoBroker"} — please check` : "Locality not found — type it";
    // A different listing than the report on screen: open the form so it can be scanned.
    if (changed && lastScan && lastScan.url !== l.listing_url) expandForm();
  } catch {
    state.textContent = "Enter the locality manually";
  }
}

if (globalThis.chrome?.tabs?.onActivated) {
  chrome.tabs.onActivated.addListener(() => loadListingFromTab());
  chrome.tabs.onUpdated.addListener((_id, info, tab) => {
    if (info.status === "complete" && tab.active) loadListingFromTab();
  });
}

// ---------- compact listing line ----------
let lastScan = null;
let currentArea = null;

// "Rajiv Gandhi Nagar, 7th Sector, HSR Layout" + area "HSR Layout" -> "Rajiv Gandhi Nagar, 7th Sector"
function subLocality(locality, area) {
  if (!locality || !area) return locality;
  const parts = locality.split(",").map((p) => p.trim()).filter(Boolean);
  const rest = parts.filter((p) => p.toLowerCase() !== area.toLowerCase());
  return rest.length && rest.length < parts.length ? rest.join(", ") : locality;
}

function collapseForm(summary) {
  lastScan = summary;
  const parts = [subLocality(summary.locality, currentArea), summary.rent ? inr(summary.rent) : null, summary.bhk ? `${summary.bhk} BHK` : null,
    summary.total ? `${summary.done}/${summary.total} checked` : null].filter(Boolean);
  $("compact-text").textContent = parts.join(" · ");
  $("compact-listing").classList.remove("hidden");
  document.querySelector(".scan-card").classList.add("hidden");
}

function expandForm() {
  $("compact-listing").classList.add("hidden");
  document.querySelector(".scan-card").classList.remove("hidden");
}

// ---------- scanning ----------
let source = null;

function setProgress(done, total, label) {
  $("progress").classList.remove("hidden");
  $("progress-count").textContent = total ? `${done}/${total}` : "";
  $("progress-fill").style.width = total ? `${(done / total) * 100}%` : "0%";
  if (label) $("progress-label").textContent = label;
}

// While a scan runs, show only progress + a skeleton: never leave the example (or a previous
// report) on screen where it could be mistaken for this scan's result.
function clearReport(demo, body = {}) {
  $("listing-sub").textContent = [body.locality, body.bhk ? `${body.bhk} BHK` : null].filter(Boolean).join(" · ") || "Scanning…";
  const pill = $("mode-pill");
  pill.textContent = demo ? "LOADING" : "SCANNING";
  pill.className = "mode-pill mode-scanning";
  $("data-banner").classList.add("hidden");
  $("rent-badge").textContent = "";
  $("residents-badge").textContent = "";
  const skeleton = (lines) =>
    h("section", { class: "card skeleton" }, Array.from({ length: lines }, (_, i) => h("div", { class: "sk-line", style: `width:${90 - i * 15}%` })));
  $("view-overview").replaceChildren(
    h("section", { class: "card skeleton hero-skel" },
      h("div", { class: "sk-ring" }),
      h("div", { class: "sk-text" }, h("div", { class: "sk-line", style: "width:60%" }), h("div", { class: "sk-line", style: "width:85%" }), h("div", { class: "sk-line", style: "width:70%" }))),
    h("p", { class: "muted sk-note" }, demo ? "Loading the saved scan…" : "Results appear here when the checks finish."),
    skeleton(5), skeleton(3));
  for (const id of ["view-rent", "view-residents", "view-ask"]) {
    $(id).replaceChildren(h("p", { class: "muted sk-note" }, "Waiting for this scan's results…"), skeleton(3));
  }
}

function showFailed(msg) {
  const pill = $("mode-pill");
  pill.textContent = "FAILED";
  pill.className = "mode-pill mode-failed";
  const note = h("section", { class: "card" }, h("p", { class: "muted" }, `No result: ${msg} Use “Show example” or “Replay cached scan”.`));
  for (const id of ["view-overview", "view-rent", "view-residents", "view-ask"]) $(id).replaceChildren(note.cloneNode(true));
}

function setBusy(busy) {
  $("btn-scan").disabled = busy;
  $("btn-replay").disabled = busy;
}

function showError(msg) {
  const e = $("scan-error");
  e.textContent = msg;
  e.classList.toggle("hidden", !msg);
}

async function startScan(demo = false) {
  showError("");
  const locality = $("in-locality").value.trim() || (demo ? "latest" : "");
  if (locality.length < 2) {
    showError("Please enter a locality.");
    $("in-locality").focus();
    return;
  }
  const num = (id) => {
    const n = parseInt($(id).value, 10);
    return Number.isFinite(n) ? n : null;
  };
  const body = { locality, rent: num("in-rent"), bhk: num("in-bhk"), listing_url: window.__listing?.url || null, listing_text: window.__listing?.text || null, source: window.__listing?.source || "manual" };

  if (source) source.close();
  expandForm();
  clearReport(demo, body);
  setBusy(true);
  $("progress-list").replaceChildren();
  setProgress(0, 0, demo ? "Loading cached scan…" : "Starting scan…");

  let scanId;
  try {
    const res = await fetch(`${BACKEND}/scan${demo ? "?demo=1" : ""}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (demo && res.status === 404) throw new Error("no cached scan saved yet — run a live scan first");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    scanId = (await res.json()).scan_id;
  } catch (err) {
    setBusy(false);
    $("progress").classList.add("hidden");
    const msg = err.message.startsWith("no cached") ? `Replay failed: ${err.message}.` : `Could not reach the backend at ${BACKEND} (${err.message}). Is it running?`;
    showError(msg);
    showFailed(msg);
    return;
  }

  let total = 0;
  let gotReport = false;
  source = new EventSource(`${BACKEND}/scan/${scanId}/stream`);
  source.addEventListener("started", (e) => {
    const d = JSON.parse(e.data);
    total = d.total;
    setProgress(0, total, "Running checks…");
    $("progress-list").replaceChildren(...d.checks.map((id) => h("li", { id: `pg-${id}`, class: "pending" }, h("span", { class: "dot" }), h("span", {}, id.replace(/_/g, " ")), h("span", { class: "muted" }, "running…"))));
  });
  source.addEventListener("progress", (e) => {
    const d = JSON.parse(e.data);
    done = d.completed;
    setProgress(d.completed, d.total, d.completed < d.total ? "Running checks…" : "Building report…");
    const li = $(`pg-${d.check_id}`);
    if (li) li.replaceChildren(h("span", { class: `dot st-${d.status}` }), h("span", {}, d.headline), statusChip(d.status));
    if (li) li.className = "";
  });
  source.addEventListener("report", (e) => { gotReport = true; render(JSON.parse(e.data)); });
  let done = 0;
  source.addEventListener("done", () => {
    source.close();
    source = null;
    setBusy(false);
    setProgress(total, total, demo ? "Cached scan replayed" : "Scan complete");
    // Fold the form + progress rows into one line so every tab starts near the top.
    if (gotReport) collapseForm({ ...body, url: body.listing_url, done: done || total, total });
  });
  source.onerror = () => {
    if (!source) return;
    source.close();
    source = null;
    setBusy(false);
    showError("Lost connection to the scan stream.");
    if (!gotReport) showFailed("Lost connection to the scan stream before the report arrived.");
  };
}

function showEmpty() {
  const pill = $("mode-pill");
  pill.textContent = "READY";
  pill.className = "mode-pill mode-ready";
  $("data-banner").classList.add("hidden");
  $("rent-badge").textContent = "";
  $("residents-badge").textContent = "";
  $("view-overview").replaceChildren(h("p", { class: "empty-state" }, "Click Scan to check this area live."));
  for (const id of ["view-rent", "view-residents", "view-ask"]) {
    $(id).replaceChildren(h("p", { class: "empty-state" }, "Click Scan to check this area live."));
  }
}

async function showExample() {
  const report = await (await fetch(EXAMPLE_URL)).json();
  expandForm();
  render(report);
}

$("btn-scan").addEventListener("click", () => startScan(false));
$("btn-replay").addEventListener("click", () => startScan(true));
$("btn-example").addEventListener("click", showExample);

// Open on an empty state: no report until the user scans (or asks for the example).
showEmpty();
$("btn-edit").addEventListener("click", () => { expandForm(); window.scrollTo({ top: 0 }); });
$("btn-read-page").addEventListener("click", () => {
  if (globalThis.chrome?.tabs) loadListingFromTab();
  else $("extract-state").textContent = "Open a NoBroker/MagicBricks listing first";
});
if (globalThis.chrome?.tabs) loadListingFromTab();
else $("extract-state").textContent = "Enter the locality manually";
