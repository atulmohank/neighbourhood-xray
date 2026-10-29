// Best-effort extraction of locality, rent and BHK from a NoBroker listing.
// NoBroker's markup is not a stable API, so every field may come back null;
// the side panel then asks the user to type the locality.

(function () {
  function clean(s) {
    return (s || "").replace(/\s+/g, " ").trim();
  }

  function toNumber(s) {
    const n = parseInt(String(s).replace(/[^\d]/g, ""), 10);
    return Number.isFinite(n) ? n : null;
  }

  function extractListing() {
    const title = clean(document.title);
    const h1 = clean(document.querySelector("h1")?.textContent);
    const heading = `${h1} | ${title}`;
    const body = clean(document.body?.innerText).slice(0, 20000);

    const bhkMatch = heading.match(/(\d+)\s*BHK/i) || body.match(/(\d+)\s*BHK/i);
    const bhk = bhkMatch ? parseInt(bhkMatch[1], 10) : null;

    // e.g. "2 BHK Flat For Rent In HSR Layout, Bangalore"
    const locMatch = heading.match(/\bin\s+([A-Za-z0-9 .'-]+(?:,\s*[A-Za-z .'-]+)?)/i);
    const locality = locMatch ? clean(locMatch[1]).replace(/\s*\|.*$/, "") : null;

    // e.g. "Rent ₹32,000" or "₹ 32,000 /month"
    const rentMatch =
      body.match(/Rent[^₹\d]{0,30}₹\s*([\d,]{4,})/i) ||
      body.match(/₹\s*([\d,]{4,})\s*(?:\/\s*month|per month)/i);
    const rent = rentMatch ? toNumber(rentMatch[1]) : null;

    return {
      locality: locality || null,
      rent,
      bhk,
      source: "nobroker",
      listing_url: location.href,
      extracted: Boolean(locality),
    };
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "xray:extractListing") {
      try {
        sendResponse({ ok: true, listing: extractListing() });
      } catch (err) {
        sendResponse({ ok: false, error: String(err) });
      }
    }
  });
})();
