// Best-effort extraction of locality, rent and BHK from a NoBroker or MagicBricks listing.
// Most reliable first: the listing URL (NoBroker URLs carry BHK, locality and current
// rent), then the page title, then the page text. The page text is a last resort:
// NoBroker shows a reduced rent next to the old one ("₹30,000 ₹35,000 Rent Reduced").
// The full original locality is kept for display; the backend maps sub-areas to
// their parent area (e.g. Rajiv Gandhi Nagar, 7th Sector -> HSR Layout) for matching.

(function () {
  // Building-type words NoBroker puts in front of the locality in titles.
  const BUILDING_PREFIX = /^(independent (house|floor|villa)|apartment|villa|standalone building|gated (community|society)|builder floor)\s*,?\s*/i;

  function clean(s) {
    return (s || "").replace(/\s+/g, " ").trim();
  }

  function toNumber(s) {
    const n = parseInt(String(s).replace(/[^\d]/g, ""), 10);
    return Number.isFinite(n) ? n : null;
  }

  function titleCase(slug) {
    return slug
      .split(/[-_\s]+/)
      .filter(Boolean)
      .map((w) => (/^(hsr|btm|jp|kr|rt|hal|itpl)$/i.test(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)))
      .join(" ");
  }

  function fromNoBrokerUrl(url) {
    // /property/2-bhk-apartment-for-rent-in-rajiv-gandhi-nagar-7th-sector-hsr-layout-bangalore-for-rs-30000/<id>/detail
    const m = url.match(/\/property\/(\d+)-bhk-[a-z-]*?for-rent-in-([a-z0-9-]+?)-(?:bangalore|bengaluru)-for-rs-(\d+)\//i);
    if (!m) return {};
    const parts = m[2].split(/-(?=\d+(?:st|nd|rd|th)-sector)|-(?=hsr-layout|btm-layout)/i).map(titleCase);
    return { bhk: +m[1], locality: parts.join(", "), rent: +m[3] };
  }

  function fromMagicBricksUrl(url) {
    // /propertyDetails/2-BHK-1198-Sq-ft-Multistorey-Apartment-FOR-Rent-HSR-Layout-Sector-2-in-Bangalore&id=...
    const m = url.match(/propertyDetails\/(\d+)-BHK-.*?FOR-Rent-(.+?)-in-(?:Bangalore|Bengaluru)/i);
    return m ? { bhk: +m[1], locality: titleCase(m[2]) } : {};
  }

  function fromTitle(title) {
    const out = {};
    // "... Rental Flat in Independent House, Rajiv Gandhi Nagar, 7th Sector, HSR Layout, Bangalore for Rs. 30,000 | NoBroker"
    // MagicBricks: "Rent 2 BHK Flat for Rent in Sobha Daffodil HSR Layout Bangalore @ ₹40000/month"
    const loc =
      title.match(/\bin\s+([^|]+?),\s*(?:bangalore|bengaluru)\b/i) ||
      title.match(/\bfor rent in\s+(.+?)\s+(?:bangalore|bengaluru)\b/i);
    if (loc) out.locality = clean(loc[1]).replace(BUILDING_PREFIX, "");
    // No \b before ₹: there is no word boundary between a space and "₹".
    const rent = title.match(/(?:\brs\.?|₹)\s*([\d,]{4,})/i);
    if (rent) out.rent = toNumber(rent[1]);
    const bhk = title.match(/(\d+)\s*BHK/i);
    if (bhk) out.bhk = +bhk[1];
    return out;
  }

  function fromText(body) {
    const out = {};
    const bhk = body.match(/(\d+)\s*BHK/i);
    if (bhk) out.bhk = +bhk[1];
    // First rupee amount after a "Rent" label that isn't followed by "Rent Reduced"'s old price.
    const rent = body.match(/\bRent\b[^₹\d]{0,30}₹\s*([\d,]{4,})/i);
    if (rent) out.rent = toNumber(rent[1]);
    return out;
  }

  function extractListing(doc, href) {
    const url = href || "";
    const title = clean(doc.title);
    const full = clean(doc.body?.innerText);
    let body = full.slice(0, 20000);
    // Listing details ("Water Supply: Corporation") can sit past the cut-off on long pages: keep them.
    const ws = full.search(/water\s*supply/i);
    if (ws >= 20000) body = body.slice(0, 19500) + " … " + full.slice(Math.max(0, ws - 100), ws + 300);
    const source = /magicbricks\.com/i.test(url) ? "magicbricks" : "nobroker";
    const byUrl = source === "nobroker" ? fromNoBrokerUrl(url) : fromMagicBricksUrl(url);
    const byTitle = fromTitle(title);
    const byText = fromText(body);
    // The title keeps building/sub-area names the URL slug loses, so prefer it for display.
    const locality = byTitle.locality || byUrl.locality || null;
    return {
      locality,
      rent: byUrl.rent || byTitle.rent || byText.rent || null,
      bhk: byUrl.bhk || byTitle.bhk || byText.bhk || null,
      source,
      listing_url: url,
      listing_text: body || null,
      extracted: Boolean(locality),
    };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { extractListing, fromNoBrokerUrl, fromMagicBricksUrl, fromTitle };
    return;
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "xray:extractListing") {
      try {
        sendResponse({ ok: true, listing: extractListing(document, location.href) });
      } catch (err) {
        sendResponse({ ok: false, error: String(err) });
      }
    }
  });
})();
