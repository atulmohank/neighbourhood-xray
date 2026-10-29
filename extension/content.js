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

    const bhkElements = Array.from(
        document.querySelectorAll("div.font-semibold")
    );

    const bhkText = bhkElements
        .map((el) => clean(el.textContent))
        .find((text) => /^\d+\s*BHK$/i.test(text));

    const bhkMatch = bhkText
        ? bhkText.match(/^(\d+)\s*BHK$/i)
        : heading.match(/(\d+)\s*BHK/i);

    const bhk = bhkMatch ? parseInt(bhkMatch[1], 10) : null;

    // e.g. "2 BHK Flat For Rent In HSR Layout, Bangalore"
    const locMatch = heading.match(
        /\bin\s+(.+?)(?=\s*(?:\||[-–]\s*NoBroker|Without Brokerage|$))/i
    );

    let locality = locMatch ? clean(locMatch[1]) : null;

    if (locality) {
        locality = locality.replace(/,\s*(?:Bangalore|Bengaluru).*$/i, "").trim();
    }

    // e.g. "Rent ₹32,000" or "₹ 32,000 /month"
    // Find the Rent label and read the amount immediately above it.
    const rentLabel = Array.from(document.querySelectorAll("div, span"))
        .find((el) =>
            clean(el.textContent) === "Rent" &&
            el.parentElement
        );

    const rentContainer = rentLabel?.parentElement;
    const rentText = rentContainer
        ? clean(rentContainer.innerText)
        : "";

    const rentMatch = rentText.match(/₹\s*([\d,]+)/);
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
