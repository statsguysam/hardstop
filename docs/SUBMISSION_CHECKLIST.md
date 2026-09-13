# HardStop submission checklist

One solo-team submission was confirmed at 21:06 UTC on September 13, 2026, before the 23:00 UTC deadline. The original v0.1.0 publication and strengthened v0.2.0 revision were checked publicly. The same submitted repository and Pages URLs remain the entry points. The form still showed its recorded-response confirmation when checked at 22:35 UTC; no second response was submitted. Confirmation details remain private.

The current v0.3.0 release has passed all local, live and public gates below: 216 local and Linux CI tests, 32 independent provider readback checks, eight anonymous release downloads, both public-source imports, captioned playback and all four inspector cases. [Final publication checks](evidence/publication-v3.json).

The official event page lists a submission deadline of **September 13, 2026, 23:00 UTC**, which is **September 14, 2026, 04:30 IST**. The form was completed before that cutoff; the same submitted URLs continue to identify this entry. The [event page](https://multiappagenthackathon.com/) is the authority if the organizers announce another change.

Entry points: [repository](https://github.com/statsguysam/hardstop), [demo](https://statsguysam.github.io/hardstop/), [recorded-result inspector](https://statsguysam.github.io/hardstop/explore.html). The [v0.3.0 release](https://github.com/statsguysam/hardstop/releases/tag/v0.3.0) is published and publicly verified. Historical verification: [v0.2.0 files](https://github.com/statsguysam/hardstop/releases/tag/v0.2.0), [213-test Linux CI run](https://github.com/statsguysam/hardstop/actions/runs/34784957386).

## Current v0.3.0 local and live gates

- [x] Register new, truthful synthetic-voice sources in separate app workspaces. Relay measures 177,036 ms and Harbor 83,202 ms; earlier verified sources remain unchanged.
- [x] Complete the buyer and operator variants at 87.868 and 88.368 seconds with different optional clips, identical required context, and 25 checks each.
- [x] Complete the Harbor variant at 44.701 seconds with 24 checks. Preserve its earlier review outcome and exact clarified brief.
- [x] Preserve the earlier operator source-download failure, which stopped before outputs, alongside the later successful run.
- [x] Run the impossible 30-second revision against the 55.101-second mandatory minimum. Confirm no outputs and preserve the operator delivery.
- [x] Complete the later buyer/operator/Harbor provider readbacks with 10/12/10 passed checks.
- [x] Document the unknown source-upload outcome and registration recovery using the same pending path and verified content, with the local-journal evidence limit stated.
- [x] Pass all 216 local tests, including FFmpeg, loopback and the durable inspector checks; pass JavaScript syntax validation.
- [x] Make all four saved cases inspectable without OAuth setup, with explicit recorded-run labels and no live actions. Validate video identity against receipt/readback/release hashes and fail visibly on incomplete data.
- [x] Preserve fictional-content and synthetic-voice disclosures while simplifying current interface text and removing decorative punctuation and unnecessary voice-engine labels.
- [x] Verify the two new source ZIPs through extraction, import, full decode and comparison with registered source hashes.

## Current v0.3.0 publication gates

- [x] Publish the final source snapshot and confirm its current Linux CI result.
- [x] Publish the new demo, captions, output videos, source bundles and checksum file; verify anonymous downloads against local hashes.
- [x] Confirm the public demo completes within two minutes with visible English captions.
- [x] Confirm the public recorded-result inspector loads all four cases, matching videos and the impossible-request preservation evidence.
- [x] Reproduce the current CLI and source import using anonymously downloaded public source and release files.
- [x] Confirm the already-submitted repository and Pages URLs serve the new revision. Preserve the original form confirmation without another submission.

## Original submitted package

- [x] An accessible GitHub repository containing the actual implementation, fictional source catalog, tests, and setup instructions.
- [x] A README with a concise project overview, the three external apps, setup and run instructions, reliability test evidence, and the demo link.
- [x] A playable demo recording of **at most two minutes**, with an accessible link in the README. Verify the link while signed out.
- [x] The team's email address and GitHub URL entered in the [official submission form](https://docs.google.com/forms/d/e/1FAIpQLSclU5z63xMUenxypmW_PTcgXIGgwnENY_mgX87mPeoAWOTIoA/viewform).
- [x] One submission for this solo team/project. Save the actual confirmation or receipt after submitting.

## What the project must demonstrate

| Judging criterion | Weight | Concrete evidence to show |
| --- | ---: | --- |
| Technical execution | 30% | A working Gmail, model interpretation, Dropbox recordings, rendering, copied Slides deck, Dropbox upload, and Gmail handoff draft sequence using real APIs. |
| Reliability | 25% | Independently checked constraints, measured output duration, complete media decode, byte-for-byte upload readback, actual slide-order readback, and a blocked impossible brief that preserves the last valid output. |
| Usefulness | 20% | A producer obtains different buyer and operator versions under the same 90-second cap, with matching video and deck; another prepared source can be registered in its own workspace. |
| Originality | 15% | Audience-dependent optional selection and explicit requirement handling across deliverables, with declared context and preserved outputs when a request cannot fit. Avoid presenting AI video shortening itself as new. |
| Demo clarity | 10% | A legible successful run followed by the 30-second conflict, within two minutes. Show actual deliverables and outcomes before architecture. |

## Original v0.1.0 live acceptance gate

Connection smoke tests alone do not satisfy this gate. Record results from the complete application.

- [x] Bootstrap the labeled demo in the dedicated app resources. Gmail contains a draft fixture; Google Slides contains the eight-slide source deck; Dropbox contains the eight actual narrated clips.
- [x] Confirm the source clip bytes and measured durations. The original fixture source measured **179,071 ms**.
- [x] Complete the 120-second brief through the real application. Record its model event, selected IDs, verified output duration, deck readback, Dropbox readback and unsent delivery draft.
- [x] Amend the dedicated Gmail draft to the 90-second fixture. Run again with a new run ID and preserve the original successful artifacts.
- [x] Verify the new result contains `pilot_context`, `result`, `disclaimer`, and `call_to_action`; `pilot_context` appears before `result`. For this fixture, the mandatory closure totals **53,969 ms**.
- [x] Verify the rendered output is no longer than 90,000 ms, has audio/video, fully decodes, and matches the uploaded bytes. The original five-clip example measured **86,203 ms**.
- [x] Verify the copied Google Slides deck contains exactly the selected slide IDs in the selected order. Keep the source deck intact.
- [x] Apply the 30-second fixture and run. Confirm it is blocked because 53,969 ms of mandatory complete recordings cannot fit inside 30,000 ms.
- [x] Confirm the 30-second failure does not replace the previous valid video, copied deck, or last-valid delivery references.
- [x] Run the ambiguity and failure tests applicable to the final code. Report actual passing counts and limits in the README; distinguish unit tests, injected failures, local media tests, and live API checks.
- [x] Confirm errors and unavailable services fail visibly; live mode must not fall back to a mock or saved replay silently.

## Strengthened v0.2.0 revision: verified local work

- [x] Complete buyer and operator deliveries under the same 90-second cap and required closure, with different optional clips and 25 checks passed for each. Actual outputs measure 85.603 and 86.203 seconds.
- [x] Run the six predeclared model-evaluation cases once each, preserve all results, and report 6/6 plus the limited baseline comparison and all 11,028 reported tokens.
- [x] Register the independent six-clip Harbor source in a new workspace and complete a 43.601-second delivery with 24 checks. Retain the initial review outcome and clarified brief.
- [x] Independently read back buyer, operator and Harbor deliveries. Preserve the operator version after a subsequent impossible request; retain the 10/12/10 check results.
- [x] Pass the v0.2.0 213-test local suite, including FFmpeg and loopback checks, and JavaScript syntax validation.
- [x] Check explanation escaping, stopped/proposed state labels, current-brief comparisons, imported-source presets and placeholders using recorded interpretations in offline UI tests.
- [x] Document the producer use case, source-owner transcripts, generated Slides from `slide_text`, IDs of 2 to 40 characters, and new-workspace onboarding. State customer-demand and semantic limits.

## Strengthened v0.2.0 revision: publication gates

- [x] Publish the strengthened source snapshot. Public source and evidence are accessible without authentication; revised viewing-page checks follow below.
- [x] Verify all 213 tests passed in Linux CI for release commit `90654b7`, with no skipped tests.
- [x] Publish the revised demo, captions, source bundles and checksums; all eight public downloads match the verified local files without authentication.
- [x] Verify the revised public Pages video plays through to 1:50 with visible English captions; the file measures 110.022 seconds.
- [x] Reproduce CLI loading and six-clip Harbor import from the anonymously downloaded release source and source ZIP. This is a local import check, separate from the live provider deliveries.
- [x] Confirm the existing submitted repository/demo URLs serve the strengthened source and V2 video. The original solo-team form confirmation is preserved; no second response was submitted.

## Original release: repository and reproduction

- [x] Provide exact commands to install prerequisites, configure the approved scoped credentials, run tests, prepare fixtures, launch the interface and execute the demo sequence.
- [x] Document Python and FFmpeg requirements. Fresh local fixture generation also requires Pillow and macOS `say`; existing verified recordings can be reused. Do not imply fresh speech generation is cross-platform.
- [x] Keep credentials and raw live state outside committed source. Check tracked files and commit contents before publishing; exclude `.credentials/`, `.env`, private `.state/`, tokens and OAuth client secrets.
- [x] Publish only sanitized evidence. Clearly label any saved report as a replay of a real run, with enough information to understand what was checked.
- [x] Include the fictional catalog, transcripts and dependency declaration. Explain that all sample outcomes are invented and source narration is synthesized.
- [x] Explain the boundary: HardStop selects complete prerecorded segments and checks explicit constraints and declared dependencies. It does not prove general semantic preservation, arbitrary video editing, or live-speaker timing.
- [x] Identify any remaining limitations honestly, including the small bounded source catalog and OAuth test-mode requirements.
- [x] Import the portable source bundle and load the CLI from a clean committed source export without credentials.
- [x] Verify public README links and ensure the public demo can play without access to private Google Slides or Dropbox source resources.
- [x] Inspect the first GitHub Actions result after publication; local passing tests do not establish the remote CI result.

## Original release: recording and form

- [x] Follow the [original demo script](https://github.com/statsguysam/hardstop/blob/v0.1.0/docs/DEMO_SCRIPT.md) and show the actual 120-second, 90-second and 30-second sequence.
- [x] Keep the fictional fixture and synthesized narration labels readable. Keep a saved-replay label when using recorded run state.
- [x] Label shortened processing waits rather than implying unrealistically fast execution.
- [x] Measure the exported recording; target **119.9 seconds or less**. Verify the audio track and measured levels, on-screen legibility, and the ending frame.
- [x] Open the public repository and demo link while signed out; verify both work without the builder's account session.
- [x] Submit the correct solo-builder email and repository URL through the official form.
- [x] Verify the form confirmation and record the submission time before the deadline.

The scoring weights and submission requirements above come from the event page checked during implementation. They are a checklist for the actual submission, not a prediction of a winning result.
