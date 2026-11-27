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

// A priced trip, as the server answers it.
const RESULT = { total_eur: 34.8, carbon_eur: 15.8, complete: true, date: "2026-11-03", distance_km: 100, country_km: { DE: 100 }, lines: [], notes: [], missing: [], shipments: [],
  provenance: { carbon_cost_version: "test", tables: [{ area: "DE", name: "Lkw-Maut", valid_from: "2024-07-01", file: "de/de-2024-07-01.orct.json" }] } };

function page(answer = () => ({})) {
  const dom = new JSDOM(html, {
    url: "http://localhost/", runScripts: "dangerously", pretendToBeVisual: true,
    beforeParse(w) {
      w.fetch = async (url, opt) => { const a = answer(String(url), opt) || {}; return { ok: true, status: 200, headers: { get: () => null }, json: async () => a.json || {}, text: async () => a.text || "" }; };
      w.print = () => {};
      w.URL.createObjectURL = () => "blob:test"; w.URL.revokeObjectURL = () => {};
    },
  });
  return dom.window;
}
const tick = () => new Promise((r) => setTimeout(r, 30));
const form = (w) => (n) => w.document.getElementById("f").elements.namedItem(n);

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

// A decimal comma in the diesel price is the decimal; two bare prices are
// refused, not read as the last.
{
  const w = page(), f = form(w);
  f("from").value = "DEHAM"; f("to").value = "DEBER";
  f("diesel_price").value = "1,5";
  check(w.eval("buildRequest()").diesel_eur_per_l === 1.5, "diesel 1,5: " + w.eval("buildRequest()").diesel_eur_per_l);
  f("diesel_price").value = "1.4, 1.5";
  let err = "";
  try { w.eval("buildRequest()"); } catch (e) { err = e.message; }
  check(err.includes("one price"), "diesel 1.4, 1.5: " + (err || "no error"));
}

// A stop added in between keeps a shipment unloaded where it was.
{
  const w = page(), f = form(w);
  f("from").value = "DKCPH"; f("to").value = "DEHAM";
  f("multi").checked = true; f("multi").dispatchEvent(new w.Event("change"));
  w.document.querySelector(".skg").value = "10000";
  w.document.getElementById("addstop").click();
  const stop = w.document.querySelector('input[name^="stop"]');
  stop.value = "DEBER"; stop.dispatchEvent(new w.Event("change"));
  const req = w.eval("buildRequest()");
  check(req.stops.length === 3 && req.shipments[0].to === 2, "stop added: " + JSON.stringify(req.shipments));
}

// A route picked with "Price this route" is the last trip's: a trip loaded
// from the recent ones is priced on Sootcase's route.
{
  const w = page();
  w.eval('pickRoute = "alt1"; restore(state());');
  check(w.eval("pickRoute") === "", "route picked after restore: " + w.eval("pickRoute"));
}

(async () => {
  // The cost note is the priced trip's, not the form changed since.
  {
    const w = page((url) => url.endsWith("v1/carbon-cost") ? { json: RESULT } : null), f = form(w);
    f("from").value = "DEHAM"; f("to").value = "DEBER";
    w.document.getElementById("f").dispatchEvent(new w.Event("submit", { cancelable: true }));
    await tick();
    f("to").value = "DEMUC"; f("max_mass_kg").value = "18000";
    w.document.getElementById("print").click();
    const t = w.document.getElementById("printtrip").textContent;
    check(t.startsWith("DEHAM → DEBER.") && t.includes("40,000 kg"), "cost note after the form changed: " + t);
  }
  // The CSV box counts the rows priced and those with an error.
  {
    const w = page((url) => url.includes("v1/carbon-cost/csv") ? { text: 'from;to;error\nDEHAM;DEBER;\nXXX;DEBER;"leg 1 from: unknown location ""XXX"""\n' } : null);
    Object.defineProperty(w.document.getElementById("csvfile"), "files", { value: [{ name: "trips.csv", text: async () => "from;to\nDEHAM;DEBER\nXXX;DEBER\n" }] });
    w.document.getElementById("csvgo").click();
    await tick();
    const t = w.document.getElementById("csvinfo").textContent;
    check(t.startsWith("1 of 2 rows priced, 1 with an error"), "CSV box: " + t);
  }
  done();
})();

// The data used names the datasets' folder.
{
  const w = page();
  w.eval(`show(${JSON.stringify(RESULT)})`);
  const t = w.document.getElementById("provlist").textContent;
  check(t.includes("(tariffs/data/de/de-2024-07-01.orct.json)"), "data used: " + t);
}

function done() {
  if (failed) { console.error(`test_page: ${failed} FAILED`); process.exit(1); }
  console.log("test_page: ok");
}
