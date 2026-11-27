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
  check(err !== "", "diesel 1.4, 1.5 refused: " + (err || "no error"));
  // A country's price with a decimal comma, and several with ; between.
  f("diesel_price").value = "DE=1,5";
  let req = w.eval("buildRequest()");
  check(!req.diesel_eur_per_l && req.diesel_eur_per_l_by_country.DE === 1.5, "diesel DE=1,5: " + JSON.stringify(req));
  f("diesel_price").value = "1,45;PL=1,25";
  req = w.eval("buildRequest()");
  check(req.diesel_eur_per_l === 1.45 && req.diesel_eur_per_l_by_country.PL === 1.25, "diesel 1,45;PL=1,25: " + JSON.stringify(req));
  f("diesel_price").value = "1,459";
  err = "";
  try { w.eval("buildRequest()"); } catch (e) { err = e.message; }
  check(err.includes("1459 or 1.459"), "diesel 1,459: " + (err || "no error"));
  // Km by country the same way.
  f("diesel_price").value = "";
  f("country_km").value = "DE=320,5;PL=410";
  req = w.eval("buildRequest()");
  check(req.country_km && req.country_km.DE === 320.5 && req.country_km.PL === 410, "km DE=320,5;PL=410: " + JSON.stringify(req.country_km));
  f("country_km").value = "DE=320,5";
  check(w.eval("buildRequest()").country_km.DE === 320.5, "km DE=320,5");
  f("country_km").value = "";
  f("fuel_bought").value = "DE=300, PL=150,5; CZ=20";
  req = w.eval("buildRequest()");
  check(JSON.stringify(req.fuel_purchases) === JSON.stringify([{ country: "DE", litres: 300 }, { country: "PL", litres: 150.5 }, { country: "CZ", litres: 20 }]), "diesel bought: " + JSON.stringify(req.fuel_purchases));
}

// Lists by country as calc reads them: the cases both run.
{
  const w = page();
  const { cases } = JSON.parse(require("fs").readFileSync(require("path").join(__dirname, "../../cmd/carbon-cost/testdata/countryvalues.json"), "utf8"));
  for (const [input, want] of cases) {
    let got = null;
    try { got = Object.fromEntries(w.eval(`countryValues(${JSON.stringify(input)}, "x")`)); } catch (e) { got = null; }
    check(JSON.stringify(got) === JSON.stringify(want), `countryValues(${JSON.stringify(input)}): ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  }
}

// The CSV's separator is counted outside quotes, as the server does.
{
  const w = page(), rows = w.eval(`parseCSV('country-km;cargo-kg;"Kunde, Ort, PLZ"\\nDE=100,PL=100;1000;"A, B"\\n')`);
  check(rows.length === 2 && rows[1].length === 3 && rows[1][2] === "A, B", "; CSV with commas in a label: " + JSON.stringify(rows));
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
  // Removed again, and the way back ticked and unticked: still at DEHAM.
  stop.closest(".row").querySelector("button").click();
  check(w.eval("buildRequest()").shipments[0].to === 1, "stop removed: " + JSON.stringify(w.eval("buildRequest()").shipments));
  for (const on of [true, false]) {
    f("back").checked = on; f("back").dispatchEvent(new w.Event("change"));
    const r = w.eval("buildRequest()");
    check(r.shipments[0].to === 1, "back " + on + ": " + JSON.stringify(r.shipments));
  }
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
