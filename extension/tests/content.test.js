// Run with: node extension/tests/content.test.js
const assert = require("assert");
const { extractListing } = require("../content.js");

const nb = "https://www.nobroker.in/property/2-bhk-apartment-for-rent-in-rajiv-gandhi-nagar-7th-sector-hsr-layout-bangalore-for-rs-30000/8aa9a839a056cd0c01a057a8088e2a7a/detail";
const nbTitle = "Independent House Rajiv Gandhi Nagar, 7th Sector, HSR Layout Rent - WITHOUT BROKERAGE Semi-furnished 2 BHK Rental Flat in Independent House, Rajiv Gandhi Nagar, 7th Sector, HSR Layout, Bangalore for Rs. 30,000 | NoBroker";
// The page text shows the reduced rent next to the old one; it must not win.
const nbBody = "2 BHK House for Rent In Rajiv Gandhi Nagar, 7th Sector, Hsr Layout READY ₹30,000₹ 35,000 Included No Extra Maintenance Rent Reduced";

let l = extractListing({ title: nbTitle, body: { innerText: nbBody } }, nb);
assert.strictEqual(l.locality, "Rajiv Gandhi Nagar, 7th Sector, HSR Layout");
assert.strictEqual(l.rent, 30000);
assert.strictEqual(l.bhk, 2);

// Title missing: fall back to the URL slug.
l = extractListing({ title: "NoBroker", body: { innerText: "" } }, nb);
assert.strictEqual(l.locality, "Rajiv Gandhi Nagar, 7th Sector, HSR Layout");
assert.strictEqual(l.rent, 30000);

const mb = "https://www.magicbricks.com/propertyDetails/2-BHK-1198-Sq-ft-Multistorey-Apartment-FOR-Rent-HSR-Layout-Sector-2-in-Bangalore&id=4d423837313336343733";
l = extractListing({ title: "MagicBricks", body: { innerText: "Rent ₹45,000 Security deposit ₹2,00,000" } }, mb);
assert.strictEqual(l.locality, "HSR Layout Sector 2");
assert.strictEqual(l.rent, 45000);
assert.strictEqual(l.source, "magicbricks");

// Real MagicBricks titles: no comma before the city, rent after "₹".
l = extractListing({ title: "Rent 2 BHK Flat for Rent in Sobha Daffodil HSR Layout Bangalore @ ₹40000/month", body: { innerText: "" } },
  "https://www.magicbricks.com/propertyDetails/2-BHK-1198-Sq-ft-Multistorey-Apartment-FOR-Rent-HSR-Layout-in-Bangalore&id=4d423837313431363439");
assert.strictEqual(l.locality, "Sobha Daffodil HSR Layout");
assert.strictEqual(l.rent, 40000);
l = extractListing({ title: "Rent 2 BHK Flat for Rent in Sector 2 HSR Layout Bangalore @ ₹45000/month", body: { innerText: "" } }, mb);
assert.strictEqual(l.locality, "Sector 2 HSR Layout");
assert.strictEqual(l.rent, 45000);

// A long page: the "Water Supply" field past 20,000 characters must still be sent.
l = extractListing({ title: nbTitle, body: { innerText: "x ".repeat(15000) + "Water Supply Corporation Floors 3" } }, nb);
assert.ok(/Water Supply Corporation/.test(l.listing_text) && l.listing_text.length <= 20000);

console.log("content.js: all assertions passed");
