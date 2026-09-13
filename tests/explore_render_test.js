"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "docs/explore.html"), "utf8");
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
assert.ok(!script.includes("innerHTML"), "Receipt data must enter the DOM as text");

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.hidden = false;
    this.disabled = true;
    this.dataset = {};
    this.events = {};
    this.text = "";
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(""); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.text = ""; this.children = children; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(name, listener) { this.events[name] = listener; }
  pause() {}
  load() {}
}

async function render({mutate = () => {}, unavailable = false} = {}) {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length, "HTML IDs must be unique");
  const nodes = new Map(ids.map(id => [id, new Element()]));
  const buttons = ["buyer", "operator", "harbor", "impossible"].map(key => {
    const button = new Element("button");
    button.dataset.case = key;
    return button;
  });
  const elements = [], requests = [];
  const context = {
    document: {
      getElementById(id) { assert.ok(nodes.has(id), id); return nodes.get(id); },
      querySelectorAll: () => buttons,
      createElement(tag) { const element = new Element(tag); elements.push(element); return element; },
    },
    async fetch(url, options) {
      requests.push(url);
      assert.match(url, /^evidence\/[a-z0-9-]+\.json$/, "Only fixed local receipt paths are allowed");
      assert.equal(options.credentials, "omit");
      if (unavailable) throw new Error("Receipt unavailable");
      const data = JSON.parse(fs.readFileSync(path.join(root, "docs", url), "utf8"));
      mutate(url, data);
      return {ok: true, json: async () => data};
    },
    Date, Number, String, Math, JSON, Object, Array, Promise, Error,
  };
  vm.createContext(context);
  const awaited = script.replace(/      start\(\);\s*\}\)\(\);\s*$/,
    "      globalThis.finished = start();\n})();");
  assert.notEqual(awaited, script, "Test must await the actual page initialization");
  vm.runInContext(awaited, context);
  await context.finished;
  return {nodes, buttons, elements, requests};
}

async function main() {
  let count = 0;
  const view = await render();
  assert.equal(view.nodes.get("results").hidden, false);
  assert.equal(view.nodes.get("duration").textContent, "87.868s");
  assert.equal(view.nodes.get("selected").children.length, 5);
  assert.match(view.nodes.get("video").getAttribute("src"), /v0\.3\.0\/hardstop-buyer-cut\.mp4$/);
  assert.match(view.nodes.get("comparison").textContent, /Optional: Problem/);
  assert.match(view.nodes.get("comparison").textContent, /Optional: Workflow/);
  count++;

  for (const [key, duration, clips] of [
    ["operator", "88.368s", 5], ["harbor", "44.701s", 4], ["impossible", "Cannot fit", 0],
  ]) {
    view.buttons.find(button => button.dataset.case === key).events.click();
    assert.equal(view.nodes.get("duration").textContent, duration);
    assert.equal(view.nodes.get("selected").children.length, clips);
    assert.ok(view.nodes.get("required").children.length > 0);
    if (key === "impossible") {
      assert.match(view.nodes.get("video-label").textContent, /Previous operator delivery/);
      assert.match(view.nodes.get("video").getAttribute("src"), /hardstop-operator-cut\.mp4$/);
      assert.match(view.nodes.get("readback-checks").textContent, /Impossible request created no new outputsPassed/);
      assert.match(view.nodes.get("run-checks").textContent, /Required clips fit the deadlineDid not pass/);
    }
    count++;
  }
  assert.equal(view.requests.length, 6, "Case buttons must not request another run or fetch more data");

  const mismatch = await render({mutate(url, data) {
    if (url === "evidence/release-v3.json") {
      data.artifacts.find(asset => asset.name === "hardstop-buyer-cut.mp4").sha256 = "f".repeat(64);
    }
  }});
  assert.equal(mismatch.nodes.get("results").hidden, true);
  assert.equal(mismatch.nodes.get("load-status").className, "notice error");
  assert.ok(mismatch.buttons.every(button => button.disabled));
  count++;

  const missingProof = await render({mutate(url, data) {
    if (url === "evidence/delivery-readbacks-v3.json") {
      data.results.find(result => result.label === "operator_after_impossible").checks.ready_pointer_unchanged = false;
    }
  }});
  assert.equal(missingProof.nodes.get("results").hidden, true);
  count++;

  const markup = await render({mutate(url, data) {
    if (url === "evidence/buyer-polished.json") data.checks.push({name: "<img src=x onerror=bad()>", passed: true});
  }});
  assert.equal(markup.nodes.get("results").hidden, false);
  assert.ok(markup.nodes.get("run-checks").textContent.includes("<img src=x onerror=bad()>"));
  assert.ok(markup.elements.every(element => element.tag !== "img"));
  count++;

  const failed = await render({unavailable: true});
  assert.equal(failed.nodes.get("results").hidden, true);
  assert.equal(failed.nodes.get("load-status").className, "notice error");
  assert.equal(failed.nodes.get("load-status").children[0].children.length, 4);
  count++;

  console.log(`${count} recorded-result inspector scenarios passed with published receipts. No network requests.`);
}

main().catch(error => { console.error(error); process.exitCode = 1; });
