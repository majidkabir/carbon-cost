# Requirements for Sootcase: what results say about Regulation (EU) 2026/1030

**For:** the agent working on Sootcase (github.com/majidkabir/sootcase, sootcase.org).
**From:** carbon-cost (github.com/majidkabir/carbon-cost).
**Status:** requested 2026-11-24. Not in Sootcase main on 2026-11-24: its results have no `basis`
or `certification` (checked by the Sootcase country sections workflow, E1).

## 1. Why

Regulation (EU) 2026/1030 on the greenhouse gas emissions accounting of transport services
(CountEmissions EU, [OJ L, 2026/1030, 12.5.2026](https://eur-lex.europa.eu/eli/reg/2026/1030/oj))
sets the EU's method for per-shipment transport emissions. Sootcase follows its method, but
Sootcase can't say it meets the Regulation: only certified tools may make that claim, and no tool
can be certified yet.

What the Regulation says (articles checked against the adopted text,
[PE-CONS 22/26](https://data.consilium.europa.eu/doc/document/PE-22-2026-INIT/en/pdf)):

- **Same standard.** Calculations follow EN ISO 14083:2023 "in its updated version" (Art. 3(1)).
  The Commission can declare later amendments of the standard not applicable by delegated act
  (Art. 3(4)).
- **Sootcase's kind of use.** It covers emissions of transport services that start or end in the
  Union, calculated and disclosed per service, under a contract or voluntarily for commercial
  purposes, or where law requires it (Art. 1). Aggregated figures, such as a company's totals,
  are out of scope (recital 11).
- **Dates.** In force 1 June 2026, the twentieth day after publication (Art. 20(1)). Applies from
  2 December 2030 (Art. 20(2); the date in EUR-Lex's metadata and EFTA's EEA-Lex). Until then it
  applies to no one.
- **The compliance line is reserved.** Disclosed results may carry "Greenhouse gas emissions
  calculated in accordance with Regulation (EU) 2026/1030" (Art. 10(1)). Output from an external
  calculation tool must meet Art. 11 (Art. 9(2)): the tool is certified by an accredited
  conformity assessment body (Art. 11(1), 14, 15), the certificate is valid for two years
  (Art. 11(2)), and the Commission lists the certified tools on its website (Art. 11(4)). No such
  list exists yet.
- **Default values to come.** A central Union database of default emission factors within
  24 months of entry into force (Art. 7(1)), one of default emission intensities within
  42 months (Art. 5(1)), and implementing acts on the EU calculation tool within 48 months
  (Art. 8(1)). Updated defaults must be used for new results within 18 months of being published
  (Art. 5(5), 7(4)).

## 2. What to build

### R1. State the basis

Every result and report states its basis: the standard and framework, and the Sootcase version.
For example, a response field:

```json
"basis": {
  "standard": "EN ISO 14083:2023",
  "framework": "GLEC Framework v3.3",
  "sootcase": "v0.15.1"
}
```

The same in the web page, the PDF or CSV reports, and anything else Sootcase gives out.

### R2. Say it isn't certified

Next to the basis: "Not certified under Regulation (EU) 2026/1030 (applies from 2 December 2030)."
For example `"certification": "Not certified under Regulation (EU) 2026/1030 (applies from 2 December 2030)"`.

### R3. Never print the Art. 10 line

Don't print "calculated in accordance with Regulation (EU) 2026/1030", or anything that reads
like it, unless Sootcase is certified and on the Commission's list (Art. 10(1), 11(4)). A test
should fail if the line appears in any output.

### R4. Look again later

Check again when the Commission publishes the default-value databases (Art. 5, 7) and the
certification rules, and when the Commission's list of certified tools appears (Art. 11(4)).
The first is due about June 2028.

## 3. How carbon-cost will check

- C1. A result has `basis` with the standard, the framework and the Sootcase version (R1).
- C2. A result has the not-certified statement (R2).
- C3. No result, web page or report has the Art. 10 line (R3).

carbon-cost does the same in its own output: it states EN ISO 14083:2023, says it isn't
certified, and never prints the Art. 10 line.
