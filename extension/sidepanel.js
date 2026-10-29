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

const STATUS_TEXT = { verified: "Verified", stub: "Demo", could_not_verify: "Could not verify" };

function statusChip(status) {
  return h("span", { class: `chip status-${status}` }, STATUS_TEXT[status] || status);
}

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${btn.dataset.tab}`));
  })
);

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
  $("listing-sub").textContent = [l.locality, l.bhk ? `${l.bhk} BHK` : null].filter(Boolean).join(" · ") || "No listing";

  const rc = report.rent_compare || {};
  $("rent-badge").textContent = rc.premium_percent != null ? `${rc.premium_percent > 0 ? "+" : ""}${Math.round(rc.premium_percent)}%` : "";
  const mentions = report.residents?.total_mentions;
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
      h("div", { class: "hero-row" },
        scoreRing(r.score),
        h("div", {},
          h("span", { class: `verdict verdict-${level}` }, (level === "good" ? "✓ " : "⚠ ") + (r.verdict || "")),
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
        h("div", { class: "pills" }, r.sources.map((s) => h("span", { class: "pill" }, h("b", { class: "mono" }, s.count), " ", s.label)))
      )
    );
  }

  v.append(
    h("section", { class: "card" },
      h("div", { class: "label-row" }, h("span", { class: "label" }, "Area scores")),
      (r.area_scores || []).map((a) => {
        const lvl = a.status === "could_not_verify" ? "unknown" : a.level || "unknown";
        return h("div", { class: "area" },
          h("div", { class: "area-row" },
            h("span", { class: "area-label" }, a.label),
            h("span", { class: "area-right" },
              a.status === "stub" ? statusChip("stub") : null,
              h("span", { class: `chip lvl-${lvl}` }, a.tag || STATUS_TEXT[a.status] || ""),
              h("span", { class: "mono area-score" }, a.score == null ? "n/a" : [a.score, h("span", { class: "muted" }, "/100")])
            )
          ),
          h("div", { class: "track" }, h("div", { class: `fill lvl-${lvl}`, style: `width:${a.score ?? 0}%` }))
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
      (r.checks || []).map((c) =>
        h("details", { class: "check" },
          h("summary", {}, h("span", {}, c.headline), statusChip(c.status)),
          h("ul", {}, (c.details || []).map((d) => h("li", {}, d))),
          h("div", { class: "check-foot" }, sourceLink(c.source_url), h("span", { class: "mono muted" }, c.fetched_at || ""))
        )
      )
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
  if (res.status === "could_not_verify" || !(res.themes || []).length) {
    v.append(h("section", { class: "card" }, h("div", { class: "label-row" }, h("span", { class: "label" }, "Residents"), statusChip("could_not_verify")),
      h("p", { class: "muted" }, "No resident discussions were fetched for this scan.")));
    return;
  }
  const max = Math.max(...res.themes.map((t) => t.mentions));
  v.append(
    h("section", { class: "card" },
      h("div", { class: "label-row" }, h("span", { class: "label" }, `Top complaints · ${res.window || ""}`), h("span", { class: "label" }, `${res.total_mentions} mentions`)),
      res.themes.map((t) =>
        h("div", { class: "theme" }, h("span", {}, t.label), h("div", { class: "track" }, h("div", { class: "fill lvl-risk soft", style: `width:${(t.mentions / max) * 100}%` })), h("span", { class: "mono" }, t.mentions))
      )
    ),
    h("section", { class: "card" },
      h("div", { class: "label-row" }, h("span", { class: "label" }, "In their words")),
      (res.quotes || []).map((q) =>
        h("blockquote", { class: `quote theme-${q.theme}` }, h("p", { class: "serif" }, `“${q.text}”`), h("div", { class: "quote-foot" }, h("span", { class: "mono muted" }, `${q.source} · ${q.posted_at || ""}`), sourceLink(q.source_url)))
      )
    )
  );
}

function renderAsk(r) {
  const v = $("view-ask");
  v.replaceChildren();
  const qs = r.questions_for_owner || [];
  v.append(
    h("section", { class: "card" },
      h("div", { class: "label-row" }, h("span", { class: "label" }, "Ask the owner"), h("span", { class: "label mono" }, qs.length)),
      qs.length ? qs.map((q) => h("label", { class: "ask-q" }, h("input", { type: "checkbox" }), h("span", {}, q))) : h("p", { class: "muted" }, "No questions yet.")
    ),
    h("section", { class: "card" },
      h("div", { class: "label-row" }, h("span", { class: "label" }, "Ask anything")),
      h("p", { class: "muted" }, "Coming soon — free-form questions about the area are not implemented yet.")
    )
  );
}

// ---------- listing extraction ----------
async function loadListingFromTab() {
  const state = $("extract-state");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !/^https:\/\/www\.nobroker\.in\//.test(tab.url || "")) throw new Error("not a NoBroker tab");
    const res = await chrome.tabs.sendMessage(tab.id, { type: "xray:extractListing" });
    if (!res?.ok) throw new Error(res?.error || "no response");
    const l = res.listing;
    if (l.locality) $("in-locality").value = l.locality;
    if (l.rent) $("in-rent").value = l.rent;
    if (l.bhk) $("in-bhk").value = l.bhk;
    window.__listingUrl = l.listing_url;
    state.textContent = l.locality ? "From NoBroker — please check" : "Locality not found — type it";
  } catch {
    state.textContent = "Enter the locality manually";
  }
}

// ---------- scanning ----------
let source = null;

function setProgress(done, total, label) {
  $("progress").classList.remove("hidden");
  $("progress-count").textContent = total ? `${done}/${total}` : "";
  $("progress-fill").style.width = total ? `${(done / total) * 100}%` : "0%";
  if (label) $("progress-label").textContent = label;
}

function showError(msg) {
  const e = $("scan-error");
  e.textContent = msg;
  e.classList.toggle("hidden", !msg);
}

async function startScan() {
  showError("");
  const locality = $("in-locality").value.trim();
  if (locality.length < 2) {
    showError("Please enter a locality.");
    $("in-locality").focus();
    return;
  }
  const num = (id) => {
    const n = parseInt($(id).value, 10);
    return Number.isFinite(n) ? n : null;
  };
  const body = { locality, rent: num("in-rent"), bhk: num("in-bhk"), listing_url: window.__listingUrl || null, source: window.__listingUrl ? "nobroker" : "manual" };

  if (source) source.close();
  $("btn-scan").disabled = true;
  $("progress-list").replaceChildren();
  setProgress(0, 0, "Starting scan…");

  let scanId;
  try {
    const res = await fetch(`${BACKEND}/scan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    scanId = (await res.json()).scan_id;
  } catch (err) {
    $("btn-scan").disabled = false;
    $("progress").classList.add("hidden");
    showError(`Could not reach the backend at ${BACKEND} (${err.message}). Is it running?`);
    return;
  }

  let total = 0;
  source = new EventSource(`${BACKEND}/scan/${scanId}/stream`);
  source.addEventListener("started", (e) => {
    const d = JSON.parse(e.data);
    total = d.total;
    setProgress(0, total, "Running checks…");
    $("progress-list").replaceChildren(...d.checks.map((id) => h("li", { id: `pg-${id}`, class: "pending" }, h("span", { class: "dot" }), h("span", {}, id.replace(/_/g, " ")), h("span", { class: "muted" }, "running…"))));
  });
  source.addEventListener("progress", (e) => {
    const d = JSON.parse(e.data);
    setProgress(d.completed, d.total, d.completed < d.total ? "Running checks…" : "Building report…");
    const li = $(`pg-${d.check_id}`);
    if (li) li.replaceChildren(h("span", { class: `dot st-${d.status}` }), h("span", {}, d.headline), statusChip(d.status));
    if (li) li.className = "";
  });
  source.addEventListener("report", (e) => render(JSON.parse(e.data)));
  source.addEventListener("done", () => {
    source.close();
    source = null;
    $("btn-scan").disabled = false;
    setProgress(total, total, "Scan complete");
  });
  source.onerror = () => {
    if (!source) return;
    source.close();
    source = null;
    $("btn-scan").disabled = false;
    showError("Lost connection to the scan stream.");
  };
}

async function showExample() {
  const report = await (await fetch(EXAMPLE_URL)).json();
  render(report);
}

$("btn-scan").addEventListener("click", startScan);
$("btn-example").addEventListener("click", showExample);

showExample().catch((err) => showError(`Could not load example data: ${err.message}`));
if (globalThis.chrome?.tabs) loadListingFromTab();
else $("extract-state").textContent = "Enter the locality manually";
