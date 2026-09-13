"use strict";

// Offline rendering checks. Recorded interpretations are replayed into synthetic
// delivery states; this does not claim that a UI fixture is a live app delivery.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const page = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const ids = [...page.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
assert.equal(new Set(ids).size, ids.length, "HTML IDs must be unique");
const nodes = new Map(ids.map(id => [id, {
  innerHTML: "", textContent: "", hidden: false, disabled: false, value: "",
  setAttribute() {}, removeAttribute() {}, load() {}, addEventListener() {},
}]));
const node = id => { assert.ok(nodes.has(id), `Missing HTML element: ${id}`); return nodes.get(id); };
const sandbox = {
  document: {getElementById: node, querySelectorAll: () => [], body: {classList: {toggle: () => true}}},
  URL, Map, Set, Date, Number, String, Math,
  fetch() { throw new Error("Offline UI tests must never request a provider or server"); },
  setTimeout() {}, clearTimeout() {},
};
const script = fs.readFileSync(path.join(root, "web/app.js"), "utf8").replace(
  /  refresh\(\);\s*\}\)\(\);\s*$/,
  "  globalThis.renderFixture = value => { state = value; render(); };\n})();",
);
assert.ok(script.includes("globalThis.renderFixture"), "The test must suppress initial network activity");
vm.runInNewContext(script, sandbox);
const evidence = JSON.parse(fs.readFileSync(path.join(root, "docs/evidence/audience-evaluation.json"), "utf8"));
const clone = value => JSON.parse(JSON.stringify(value));
const modelRun = (id, startedAt) => {
  const result = clone(evidence.results.find(result => result.id === id));
  return {...result, id, status: "ready", started_at: startedAt,
    source: {brief: {fingerprint: id}, catalog_sha256: evidence.catalog_sha256},
    media: {duration_ms: result.plan.duration_ms}, outputs: {video_url: `/media/${id}/cut.mp4`}, checks: []};
};
const buyer = modelRun("buyer", "2026-09-14T10:00:00Z");
const operator = modelRun("operator", "2026-09-14T10:01:00Z");
const base = {
  configured: true, source: {title: "Offline replay fixture", segments: evidence.catalog, fictional: true},
  brief: {subject: "Operator brief", body: "Offline replay", fingerprint: "operator"},
  current_run: operator, last_ready: buyer, fixtures: {}, runs: [operator, buyer],
};
let count = 0;
function check(name, test) { test(); count++; }

check("actual audience outputs explain the changed optional selection", () => {
  const before = JSON.stringify(base);
  sandbox.renderFixture(base);
  assert.equal(node("decision-panel").hidden, false);
  assert.match(node("decisions").innerHTML, /Same 90s limit and required clips\./);
  assert.match(node("decisions").innerHTML, /Added: One handoff\. Three explicit steps\.<\/p>/);
  assert.match(node("decisions").innerHTML, /Left out: The work moves\. The context stays behind\.<\/p>/);
  assert.ok(!node("decisions").innerHTML.includes("steps.."));
  assert.equal(JSON.stringify(base), before);
});

check("stopped feasible proposals never masquerade as delivered decisions", () => {
  for (const status of ["stale", "failed", "unknown"]) {
    sandbox.renderFixture({...base, current_run: {...operator, status, error: "A safe stop explanation"}});
    assert.equal(node("decision-panel").hidden, true);
    assert.equal(node("decisions").innerHTML, "");
    assert.equal(node("output-video").src, "/media/buyer/cut.mp4");
    assert.ok(!node("check-count").textContent.includes("checks passed"));
  }
});

check("a changed brief cannot inherit the last cut's comparison", () => {
  sandbox.renderFixture({...base, brief: {...base.brief, fingerprint: "new-brief"}});
  assert.match(node("decisions").innerHTML, /previous brief and verified cut/);
  assert.match(node("decisions").innerHTML, /updated brief has not been checked/);
  assert.ok(!node("decisions").innerHTML.includes("version-change"));
});

check("running decisions are proposals and preserve the earlier video", () => {
  sandbox.renderFixture({...base, current_run: {...operator, status: "running"}});
  assert.match(node("decisions").innerHTML, /Proposed choices\. Delivery checks are still in progress/);
  assert.ok(!node("decisions").innerHTML.includes("version-change"));
  assert.equal(node("output-video").src, "/media/buyer/cut.mp4");
});

check("comparisons require the same known catalog and an earlier valid selection", () => {
  for (const older of [
    {...buyer, source: {...buyer.source, catalog_sha256: undefined}},
    {...buyer, source: {...buyer.source, catalog_sha256: "b".repeat(64)}},
    {...buyer, started_at: "2026-09-14T10:02:00Z"},
    {...buyer, plan: {...buyer.plan, selected_ids: ["nonexistent"]}},
  ]) {
    sandbox.renderFixture({...base, runs: [operator, older]});
    assert.ok(!node("decisions").innerHTML.includes("version-change"));
  }
  sandbox.renderFixture({...base, current_run: {...operator, source: {brief: operator.source.brief}},
    runs: [{...buyer, source: {}}]});
  assert.ok(!node("decisions").innerHTML.includes("version-change"));
});

check("reason and title markup is escaped rather than executed", () => {
  const changed = clone(base);
  changed.current_run.interpretation.priorities.find(row => row.segment_id === "workflow").reason = '<img src=x onerror="bad()"> & quoted';
  changed.source.segments.find(segment => segment.id === "workflow").title = "<script>bad()</script>";
  changed.source.segments.find(segment => segment.id === "result").title = 'A result with <markup> & quotes';
  sandbox.renderFixture(changed);
  assert.ok(!node("decisions").innerHTML.includes("<img"));
  assert.ok(!node("decisions").innerHTML.includes("<script"));
  assert.match(node("decisions").innerHTML, /&lt;img src=x onerror=&quot;bad\(\)&quot;&gt; &amp; quoted/);
  assert.match(node("decisions").innerHTML, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
  assert.match(node("requirements").innerHTML, /Keep: A result with &lt;markup&gt; &amp; quotes/);
  assert.ok(!node("requirements").innerHTML.includes("<markup>"));
});

check("unknown selected IDs and irrelevant reasons do not become displayed choices", () => {
  const changed = clone(base);
  changed.current_run.plan.selected_ids.push("nonexistent");
  changed.current_run.interpretation.priorities.push({segment_id: "nonexistent", value: 10, reason: "Invalid choice"});
  sandbox.renderFixture(changed);
  assert.equal(node("decision-panel").hidden, true);
});

check("imported sources cannot offer demo presets or nonexistent placeholder clips", () => {
  node("custom-body").value = "My unfinished instructions";
  const imported = {configured: true, source: {source_kind: "user_recordings", fictional: false,
    narration: "Original human narration", segments: [{id: "onboarding_context", title: "Our orientation", duration_ms: 21500, requires: []}]},
    fixtures: {original: {body: "Demo", label: "Demo"}}, brief: {body: "Demo"}, runs: []};
  sandbox.renderFixture(imported);
  assert.equal(node("scenarios").innerHTML, "");
  assert.match(node("custom-body").placeholder, /22 seconds\. Keep onboarding context\./);
  assert.ok(!node("custom-body").placeholder.includes("disclaimer"));
  assert.equal(node("custom-body").value, "My unfinished instructions");
  assert.match(node("source-disclosure").textContent, /User-supplied recordings/);
  assert.match(node("source-disclosure").textContent, /Narration: Original human narration\./);
  assert.ok(!node("source-disclosure").textContent.includes("Fictional"));
  for (const narration of ["Synthesized narration.", "Synthetic voice: Kokoro af_heart"]) {
    sandbox.renderFixture({...imported, source: {...imported.source, fictional: true, narration}});
    assert.match(node("source-disclosure").textContent, /Fictional sample\. Synthetic voice\./);
    assert.ok(!node("source-disclosure").textContent.includes("Kokoro"));
    assert.ok(!node("source-disclosure").textContent.includes("af_heart"));
  }
});

check("recorded unresolved timing cannot display schema placeholders", () => {
  const review = modelRun("ambiguous_timing", "2026-09-14T10:03:00Z");
  review.status = "needs_review";
  sandbox.renderFixture({...base, current_run: review, brief: {fingerprint: "ambiguous_timing"}});
  assert.match(node("requirements").innerHTML, /Time limit needs confirmation/);
  assert.ok(!node("requirements").innerHTML.includes("Required clips with context:"));
  assert.ok(!node("metrics").innerHTML.includes("<strong>1s</strong>"));
});

console.log(`${count} offline UI scenarios passed using the recorded audience interpretations. No API requests.`);
