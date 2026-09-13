"use strict";

(() => {
  let state = null;
  let requestBusy = false;
  let briefBusy = false;
  let polling = false;
  let networkError = false;
  let pollTimer = null;
  let activeVideo = "";
  const cached = new Map();
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
  const isDuration = n => Number.isFinite(n) && n >= 0;
  const seconds = ms => isDuration(ms) ? `${(ms / 1000).toFixed(3).replace(/\.?0+$/, "")}s` : "—";
  const clock = ms => {
    if (!isDuration(ms)) return "—:—";
    const whole = Math.floor(ms / 1000);
    return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
  };
  const labels = {ready:"Verified", running:"Working", infeasible:"Cannot fit", needs_review:"Needs review", stale:"Brief changed", failed:"Run failed", unknown:"Outcome unresolved"};
  const blocked = status => ["infeasible", "needs_review", "stale", "failed", "unknown"].includes(status);
  const safeExternal = url => {
    try { const parsed = new URL(url); return parsed.protocol === "https:" ? parsed.href : ""; }
    catch { return ""; }
  };
  const safeMedia = url => typeof url === "string" && /^\/media\/[A-Za-z0-9_-]+\/cut\.mp4$/.test(url) ? url : "";
  const human = value => String(value ?? "").replace(/_/g, " ").replace(/^./, s => s.toUpperCase());
  const stageName = value => ({queued:"Getting started",reading:"Reading the brief and source material",interpreting:"Finding the requirements",downloading:"Collecting the selected clips",rendering:"Making the video",deck:"Preparing matching slides",uploading:"Saving and checking the video",handoff:"Preparing the handoff draft",ready:"Your cut is ready",stale:"The brief changed before delivery",blocked:"This request needs a decision"}[value] || human(value));
  const checkName = value => ({catalog_integrity:"Source catalog",source_deck:"Original slides",nonempty_cut:"A playable selection",known_ids:"Recognized clips",unique_ids:"No repeated clips",source_order:"Original order",required_closure:"Required clips and context",excluded_absent:"Excluded clips left out",dependencies:"Supporting context",duration_budget:"Selected clips fit",resolved_brief:"Clear instructions",independent_selection:"Selection checked again",measured_deadline:"Finished video fits",decode_verified:"Video and audio playback",output_sha256:"Uploaded video matches",matching_deck:"Slides match the cut",handoff_readback:"Handoff draft checked",final_outputs:"Final files unchanged",fresh_inputs:"Brief still current",mandatory_duration:"Required clips fit the limit"}[value] || (value.startsWith("source_") ? human(value.slice(7)) + " recording" : human(value)));
  function displayPlanReason(reason, segments) {
    const reviewPrefix = "Resolve the brief before creating an output: ";
    if (reason.startsWith(reviewPrefix)) return reason.slice(reviewPrefix.length);
    const prefixes = [
      ["Required closure: ", "Required clips: "],
      ["The mandatory closure is ", "The required clips are "],
      ["Mandatory clips or their declared prerequisites are also excluded: ", "Required clips or their context are also excluded: "],
    ];
    const prefix = prefixes.find(([original]) => reason.startsWith(original));
    if (!prefix) return reason;
    const known = new Set(segments.map(segment => segment.id));
    return (prefix[1] + reason.slice(prefix[0].length)).replace(/\b[a-z][a-z0-9_]*\b/g, word => known.has(word) ? word.replace(/_/g, " ") : word);
  }
  const statusTag = status => `<span class="status-tag ${escape(status || "neutral")}">${escape(labels[status] || "Not run")}</span>`;
  const put = (id, html) => {
    if (cached.get(id) !== html) { $(id).innerHTML = html; cached.set(id, html); }
  };
  const friendlyTime = input => {
    if (!input) return "";
    const date = new Date(input);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"});
  };
  const showError = message => { $("global-error").textContent = String(message); $("global-error").hidden = false; };
  const clearError = () => { $("global-error").hidden = true; };

  async function api(path, data) {
    const options = data === undefined ? {} : {
      method:"POST", headers:{"Content-Type":"application/json", "X-HardStop-CSRF":state?.csrf || ""}, body:JSON.stringify(data),
    };
    const response = await fetch(path, {...options, credentials:"same-origin", cache:"no-store"});
    let body;
    try { body = await response.json(); } catch { throw new Error(`The local server returned an unreadable response (${response.status}).`); }
    if (!response.ok) throw new Error(typeof body.error === "string" ? body.error : body.message || `Request failed (${response.status}).`);
    return body;
  }

  function scenarioKey() {
    if (!state?.brief?.body) return null;
    return Object.keys(state.fixtures || {}).find(key => state.fixtures[key].body === state.brief.body) || null;
  }

  function updateActions() {
    const running = state?.current_run?.status === "running";
    const hasSource = !!state?.source?.segments?.length;
    const button = $("run-button");
    button.disabled = !state?.configured || !hasSource || running || requestBusy || briefBusy;
    button.textContent = requestBusy ? "Starting…" : running ? "Working on your cut…" : "Make this cut";
    button.setAttribute("aria-busy", String(!!(running || requestBusy)));
    document.querySelectorAll(".scenario-button").forEach(node => { node.disabled = briefBusy || !hasSource || !state?.configured; });
    $("brief-change-notice").hidden = !running;
    $("save-custom-brief").disabled = briefBusy || !hasSource || !state?.configured;
  }

  function render() {
    if (!state) return;
    $("initial-loading").hidden = true;
    const current = state.current_run;
    const ready = current?.status === "ready" ? current : state.last_ready?.status === "ready" ? state.last_ready : null;
    const briefChanged = !!(current?.source?.brief?.fingerprint && state.brief?.fingerprint && current.source.brief.fingerprint !== state.brief.fingerprint);
    const preserving = !!(ready && current && (ready.id !== current.id || briefChanged));
    const source = state.source || {};
    const segments = Array.isArray(source.segments) ? source.segments : [];
    const total = segments.length && segments.every(s => isDuration(s.duration_ms)) ? segments.reduce((sum,s) => sum+s.duration_ms,0) : null;
    const activeScenario = scenarioKey();
    const presetBudget = {original:120000, amendment:90000, impossible:30000}[activeScenario];
    const timingNeedsReview = current?.status === "needs_review" || current?.plan?.status === "needs_review";
    const budget = activeScenario ? presetBudget : briefChanged || timingNeedsReview ? null : current?.constraints?.max_duration_ms;
    const sourceTitle = source.title || "Your source clips will appear here";
    const duration = ready?.media?.duration_ms;
    const latestStatus = current?.status || "neutral";

    $("connection-status").className = `connection-status ${state.configured ? "configured" : ""}`;
    put("connection-status", state.configured ? "Workspace loaded" : "Setup needed");
    $("connection-status").title = "This workspace uses your connected Gmail, Google Slides and Dropbox accounts. Every cut is checked before delivery.";
    $("run-status").className = `status-tag ${latestStatus}`;
    $("run-status").textContent = briefChanged && blocked(latestStatus) ? `Previous attempt: ${(labels[latestStatus] || "stopped").toLowerCase()}` : briefChanged && latestStatus === "ready" ? "New brief waiting" : labels[latestStatus] || (segments.length ? "Ready to begin" : "Source needed");
    $("source-title").textContent = sourceTitle;
    $("brief-subject").textContent = state.brief?.subject || "No brief loaded yet";
    $("brief-body").textContent = state.brief?.body || "Set up the source presentation, recordings and Gmail draft to get started.";

    const scenarioNames = {original:["Original slot", "120s"], amendment:["Shorter slot", "90s"], impossible:["Too little time", "30s"], ambiguous:["Unclear brief", ""]};
    put("scenarios", Object.keys(state.fixtures || scenarioNames).map(key => {
      const [name, timing] = scenarioNames[key] || [state.fixtures[key].label, ""];
      return `<button type="button" class="scenario-button ${activeScenario === key ? "active" : ""}" data-scenario="${escape(key)}" aria-pressed="${activeScenario === key}" aria-label="Load ${escape(name)} scenario ${escape(timing)}">${escape(name)}<span>${escape(timing)}</span></button>`;
    }).join(""));

    let banner = "";
    if (current?.status === "running") {
      banner = `<div class="result-banner running-banner"><strong>${escape(stageName(current.stage || "Starting"))}</strong><p>We’ll check the finished video and slides before marking this cut ready.</p>${preserving ? '<div class="preserved">Your last verified cut is still available below.</div>' : ""}</div>`;
    } else if (current && blocked(current.status)) {
      const reasons = ["infeasible", "needs_review"].includes(current.status) && current.plan?.reasons?.length ? current.plan.reasons : [current.error || "This attempt stopped before a new delivery was ready."];
      const nextAction = {stale:"Read the updated brief, then make a new cut.",failed:"Resolve the issue above before trying again.",unknown:"Confirm what happened in the connected app before starting another cut."}[current.status];
      const headings = {infeasible:"This request cannot fit.",needs_review:"The brief needs a decision.",stale:"The source changed during this run.",failed:"The run stopped before delivery.",unknown:"An action could not be confirmed."};
      banner = `<div class="result-banner ${["failed","stale","unknown"].includes(current.status) ? "error-banner" : ""}"><strong>${escape(briefChanged ? "The previous request could not be completed." : headings[current.status])}</strong>${briefChanged ? `<p>${current.status === "unknown" ? "The Gmail brief has changed since that attempt. Confirm the previous app action before checking the new brief." : "The Gmail brief has changed since that attempt. Make a new cut to check it."}</p>` : ""}${reasons.map(reason => `<p>${escape(["infeasible", "needs_review"].includes(current.plan?.status) ? displayPlanReason(reason, segments) : reason)}</p>`).join("")}${nextAction ? `<p>${escape(nextAction)}</p>` : ""}${preserving ? '<div class="preserved">Your previous verified cut is unchanged.</div>' : ""}</div>`;
    } else if (briefChanged) {
      banner = '<div class="result-banner running-banner"><strong>Your brief has changed.</strong><p>Choose “Make this cut” to work from the updated brief.</p><div class="preserved">Your previous verified cut is unchanged.</div></div>';
    } else if (!segments.length) {
      banner = '<div class="result-banner running-banner"><strong>Add your source material to get started.</strong><p>The presentation, recordings and Gmail draft need to be set up first.</p></div>';
    }
    put("result-banner", banner);

    const exactNote = isDuration(duration) ? `${seconds(duration)} measured${preserving ? " for your previous cut" : " after rendering"}` : "Your finished video will appear here.";
    put("metrics", `<div class="primary-metric"><span class="metric-label">${preserving ? "Previous verified cut" : "Checked duration"}</span><div class="timer ${ready ? "verified" : ""}">${escape(clock(duration))}</div><span class="metric-detail">${escape(exactNote)}</span></div><div class="secondary-metrics"><div><span class="metric-label">${preserving ? "New time limit" : "Time limit"}</span><strong>${escape(seconds(budget))}</strong></div><div><span class="metric-label">Original</span><strong>${escape(clock(total))}</strong></div></div>`);
    const verifiedBudget = ready?.constraints?.max_duration_ms;
    const meterBudget = preserving ? verifiedBudget : budget;
    const meterDuration = duration;
    const percent = isDuration(meterDuration) && meterBudget > 0 ? Math.min(100, Math.max(0, meterDuration / meterBudget * 100)) : 0;
    const remaining = isDuration(meterDuration) && meterBudget > 0 ? meterBudget - meterDuration : null;
    put("budget-meter", `<div class="budget-topline"><span>${preserving ? `Verified against its ${escape(seconds(meterBudget))} brief` : "Finished length"}</span><span>${remaining !== null ? `${escape(seconds(Math.abs(remaining)))} ${remaining >= 0 ? "to spare" : "over limit"}` : "No finished cut yet"}</span></div><div class="budget-track ${!ready ? "waiting" : ""}" role="img" aria-label="${ready ? `${escape(seconds(meterDuration))} out of ${escape(seconds(meterBudget))}` : "No verified output yet"}"><div class="budget-fill ${remaining < 0 ? "over" : ""}" style="width:${percent}%"></div></div>`);

    const videoUrl = safeMedia(ready?.outputs?.video_url);
    if (videoUrl !== activeVideo) {
      const player = $("output-video");
      if (videoUrl) player.src = videoUrl;
      else { player.removeAttribute("src"); player.load(); }
      activeVideo = videoUrl;
    }
    $("output-video").hidden = !videoUrl;
    $("video-empty").hidden = !!videoUrl;
    const presentationUrl = safeExternal(ready?.outputs?.presentation_url);
    put("output-links", ready ? `${videoUrl ? `<a class="output-link" href="${escape(videoUrl)}" download>Download video</a>` : ""}${presentationUrl ? `<a class="output-link" href="${escape(presentationUrl)}" target="_blank" rel="noopener noreferrer">Open matching slides</a>` : ""}${ready.outputs?.draft_id ? '<span class="output-note">Handoff saved as an unsent draft</span>' : ""}${ready.outputs?.dropbox_path ? `<details class="output-details"><summary>File location</summary><p class="output-path">Dropbox: ${escape(ready.outputs.dropbox_path)}</p></details>` : ""}` : '<span class="muted">The video and slides appear here once they’ve been checked.</span>');

    const timelineRun = current?.status === "running" && current?.plan?.status === "feasible" ? current : ready;
    const selection = timelineRun?.plan?.selected_ids;
    const selected = new Set(selection || []);
    const required = new Set(timelineRun?.plan?.required_closure || []);
    $("selection-count").textContent = selection ? `${selection.length} of ${segments.length} clips retained` : "Complete clips only";
    put("timeline", segments.length ? segments.map((segment,index) => {
      const kind = !selection ? "waiting" : !selected.has(segment.id) ? "removed" : required.has(segment.id) ? "required" : "retained";
      const title = String(segment.title || human(segment.id)).trim();
      const titleSentence = /[.!?…]$/.test(title) ? title : `${title}.`;
      const description = `${titleSentence} ${seconds(segment.duration_ms)}. ${kind === "waiting" ? "No selection yet" : kind}. ${segment.requires?.length ? `Requires ${segment.requires.map(human).join(", ")}.` : ""}`;
      return `<div class="clip-card ${kind}" title="${escape(description)}" aria-label="${escape(description)}"><div class="clip-index"><span>${String(index+1).padStart(2,"0")}</span><span class="clip-marker">${kind === "required" ? "Required" : kind === "retained" ? "Kept" : kind === "removed" ? "Omitted" : ""}</span></div><div class="clip-title">${escape(segment.title)}</div><div class="clip-duration">${escape(seconds(segment.duration_ms))}</div></div>`;
    }).join("") : '<p class="empty-copy">Your source clips will appear once the workspace is set up.</p>');
    $("selection-note").textContent = selection ? `${timelineRun?.status === "running" ? "Proposed clips for this request; the video above is not replaced until delivery passes. " : preserving && timelineRun?.id === ready?.id ? "Showing your previous verified cut. " : ""}Clips stay intact and in their original order. Required clips include their declared context.` : "Each clip stays intact. The cut keeps the source order and any required context.";

    const rules = current?.constraints;
    const names = Object.fromEntries(segments.map(segment => [segment.id,segment.title]));
    let requirementHTML = '<p class="empty-copy">We’ll read the brief and show what must stay and what must go.</p>';
    if (rules) {
      const mandatory = current.plan?.required_closure || rules.required_ids || [];
      const timingSummary = timingNeedsReview ? "Time limit needs confirmation." : `${isDuration(rules.max_duration_ms) ? `Limit: <strong>${escape(seconds(rules.max_duration_ms))}</strong>. ` : ""}${isDuration(current.plan?.minimum_required_ms) ? `Required clips with context: <strong>${escape(seconds(current.plan.minimum_required_ms))}</strong>.` : ""}`;
      requirementHTML = `${(rules.ambiguities || []).map(item => `<div class="ambiguity-item">${escape(item)}</div>`).join("")}<div class="requirement-chips">${mandatory.map(id => `<span class="requirement-chip" title="${escape(names[id] || id)}">Keep: ${escape(human(id))}</span>`).join("")}${(rules.excluded_ids || []).map(id => `<span class="requirement-chip excluded">Leave out: ${escape(human(id))}</span>`).join("")}</div><div class="requirement-summary">${timingSummary}</div><details class="evidence-details"><summary>Read the supporting lines from the brief</summary>${(rules.evidence || []).map(evidence => `<blockquote class="evidence-quote"><span class="evidence-kind">${escape(human(evidence.kind))}${evidence.segment_id ? ` · ${escape(human(evidence.segment_id))}` : ""}</span>“${escape(evidence.quote)}”</blockquote>`).join("")}</details>`;
      if (briefChanged) requirementHTML = '<p class="requirement-summary">These requirements belong to the last attempt. The Gmail brief has since changed.</p>' + requirementHTML;
    }
    put("requirements", requirementHTML);

    const runChecks = [...(current?.plan?.checks || []), ...(current?.checks || [])];
    const checksByName = new Map(runChecks.map(check => [check.name,check]));
    const checks = Array.from(checksByName.values());
    const failedChecks = checks.filter(check => !check.passed).length;
    $("check-count").textContent = !checks.length ? "No checks yet" : failedChecks ? `${failedChecks} ${failedChecks === 1 ? "check needs" : "checks need"} attention` : current?.status === "ready" ? `${checks.length} checks passed` : current?.status === "running" ? `${checks.length} checks complete so far` : `${checks.length} checks completed before stop`;
    put("checks", checks.length ? checks.map(check => `<div class="check-item ${check.passed ? "" : "failed"}"><div class="check-heading"><strong>${escape(checkName(check.name))}</strong><span class="check-result">${check.passed ? "Passed" : "Needs attention"}</span></div><p>${escape(check.detail)}</p></div>`).join("") : '<p class="empty-copy">Checks appear here as the work progresses.</p>');

    const events = current?.events || [];
    $("activity-indicator").className = `activity-indicator ${current?.status === "running" ? "running" : ""}`;
    put("activity", events.length ? events.map(event => `<li>${escape(event.message || stageName(event.stage))}<time>${escape(friendlyTime(event.at))}</time></li>`).join("") : '<li class="empty-activity">Choose a brief and start your first cut.</li>');

    const runs = state.runs || [];
    $("history-section").hidden = !runs.length;
    put("history", runs.slice(0,10).map(run => {
      const media = safeMedia(run.outputs?.video_url);
      return `<article class="history-card">${statusTag(run.status)}<strong>${run.status === "ready" ? `${escape(seconds(run.media?.duration_ms))} verified cut` : escape(labels[run.status] || human(run.status))}</strong><small>${escape(friendlyTime(run.started_at))}</small>${run.status === "ready" && media ? `<a href="${escape(media)}" target="_blank" rel="noopener noreferrer">Open video</a>` : ""}</article>`;
    }).join(""));
    updateActions();
  }

  async function refresh() {
    if (polling) return;
    polling = true;
    try {
      state = await api("/api/state");
      if (networkError) { clearError(); networkError = false; }
      render();
    } catch (error) {
      networkError = true;
      showError(error.message || "Cannot reach the local agent server.");
      $("connection-status").className = "connection-status offline";
      put("connection-status", "Workspace unavailable");
      $("run-button").disabled = true;
    } finally {
      polling = false;
      clearTimeout(pollTimer);
      pollTimer = setTimeout(refresh, state?.current_run?.status === "running" || requestBusy ? 1500 : 5000);
    }
  }

  $("scenarios").addEventListener("click", async event => {
    const button = event.target.closest("button[data-scenario]");
    if (!button || button.disabled || briefBusy) return;
    briefBusy = true;
    updateActions();
    clearError();
    try {
      const response = await api("/api/brief", {scenario:button.dataset.scenario});
      if (response.csrf && "current_run" in response) { state = response; render(); }
      else await refresh();
    } catch (error) { showError(error.message || "The Gmail draft could not be updated."); }
    finally { briefBusy = false; updateActions(); }
  });

  $("focus-workspace").addEventListener("click", () => {
    const focused = document.body.classList.toggle("focus-mode");
    $("focus-workspace").setAttribute("aria-pressed", String(focused));
    $("focus-workspace").textContent = focused ? "Show introduction" : "Compact view";
  });

  $("save-custom-brief").addEventListener("click", async () => {
    if (briefBusy) return;
    briefBusy = true;
    clearError();
    $("custom-brief-status").textContent = "Saving…";
    updateActions();
    try {
      await api("/api/brief", {subject:$("custom-subject").value,body:$("custom-body").value});
      await refresh();
      $("custom-brief-status").textContent = "Saved to Gmail. Choose “Make this cut” when you’re ready.";
    } catch (error) {
      $("custom-brief-status").textContent = "Not saved.";
      showError(error.message);
    } finally { briefBusy = false; updateActions(); }
  });

  $("run-button").addEventListener("click", async () => {
    if (requestBusy || $("run-button").disabled) return;
    requestBusy = true;
    updateActions();
    clearError();
    try {
      const response = await api("/api/run", {});
      if (response.run_id) {
        if (state.current_run?.status === "ready") state.last_ready = state.current_run;
        state.current_run = {id:response.run_id, status:"running", stage:"Run accepted", events:[]};
        render();
      }
      await refresh();
    } catch (error) { showError(error.message || "The cut could not be started."); }
    finally { requestBusy = false; updateActions(); }
  });

  refresh();
})();
