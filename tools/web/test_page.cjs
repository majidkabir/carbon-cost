// Tests the calculator page (cmd/carbon-cost/web/index.html) in jsdom:
// what it sends and shows for the inputs a user gives.
//
// Usage: npm install jsdom@24 in a folder, then
//   NODE_PATH=<folder>/node_modules node tools/web/test_page.cjs
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const html = fs.readFileSync(path.join(__dirname, "../../cmd/carbon-cost/web/index.html"), "utf8")
  .replace(/<script src="[^"]*"><\/script>/g, "") // leaflet: the map isn't tested
  // jsdom has no form named properties (f.date): look them up as browsers do.
  .replace('const f = $("f");', 'const f = new Proxy($("f"), { get: (t, k) => { if (k in t) { const v = t[k]; return typeof v === "function" ? v.bind(t) : v; } return t.elements.namedItem(k); } });');
let failed = 0;
const check = (ok, what) => { if (!ok) { failed++; console.error("FAIL: " + what); } };

function page() {
  const dom = new JSDOM(html, {
    url: "http://localhost/", runScripts: "dangerously", pretendToBeVisual: true,
    beforeParse(w) {
      w.fetch = async () => ({ ok: true, status: 200, json: async () => ({}), text: async () => "" });
      w.print = () => {};
    },
  });
  return dom.window;
}

// The cost note for a trip priced by km by country names the km, not the
// stops left in the form.
{
  const w = page();
  const f = (n) => w.document.getElementById("f").elements.namedItem(n);
  f("country_km").value = "DE=320, PL=410";
  w.document.getElementById("print").click();
  const t = w.document.getElementById("printtrip").textContent;
  check(t.startsWith("Km by country: DE=320, PL=410."), "cost note header: " + t);
}

// Driving back empty with several shipments: a new shipment is unloaded,
// by default, at the last stop before the way back, and the request says so.
{
  const w = page();
  const f = (n) => w.document.getElementById("f").elements.namedItem(n);
  f("from").value = "DKCPH"; f("to").value = "DEHAM";
  f("back").checked = true; f("back").dispatchEvent(new w.Event("change"));
  f("multi").checked = true; f("multi").dispatchEvent(new w.Event("change"));
  w.document.querySelector(".skg").value = "10000";
  const req = w.eval("buildRequest()");
  check(req.stops && req.stops.length === 3 && req.shipments.length === 1 && req.shipments[0].from === 0 && req.shipments[0].to === 1,
    "back empty, several shipments: " + JSON.stringify({ stops: req.stops, shipments: req.shipments }));
}

// The data used names the datasets' folder.
{
  const w = page();
  w.eval(`show({ total_eur: 34.8, carbon_eur: 15.8, complete: true, date: "2026-11-03", distance_km: 100, country_km: { DE: 100 }, lines: [], notes: [], missing: [], shipments: [],
    provenance: { carbon_cost_version: "test", tables: [{ area: "DE", name: "Lkw-Maut", valid_from: "2024-07-01", file: "de/de-2024-07-01.orct.json" }] } })`);
  const t = w.document.getElementById("provlist").textContent;
  check(t.includes("(tariffs/data/de/de-2024-07-01.orct.json)"), "data used: " + t);
}

if (failed) { console.error(`test_page: ${failed} FAILED`); process.exit(1); }
console.log("test_page: ok");
