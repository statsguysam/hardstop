# Hackathon review

HardStop serves a producer who needs versions of prepared recordings for different audiences and time limits. It combines model-guided optional selection with a checked video, companion deck and handoff across three real applications. Its evidence includes different audience choices under identical hard constraints, a second imported source, and preservation of working deliverables after an impossible request. [Use case and market-evidence limits](USE_CASE.md).

| Criterion | Weight | Evidence and practical limit |
| --- | ---: | --- |
| Technical execution | 30% | Gmail briefs, runtime model priorities, Dropbox recordings/output, copied Google Slides and FFmpeg participate in completed deliveries. A six-clip Harbor package completed the general source-import path in a separate workspace. |
| Reliability | 25% | 213 current local tests, a separate 250-catalog planner oracle, source-to-copy checks, uploaded-byte readback, and independent audience/Harbor delivery checks. The new remote CI run is pending. Checks are point-in-time observations across separate services. |
| Usefulness | 20% | The same 90-second cap produced a buyer version emphasizing the problem and an operator version emphasizing the workflow, with matching deliverables. Preparation effort, customer demand and time savings remain unvalidated. |
| Originality | 15% | Audience-dependent selection, mandatory content, declared prerequisites, actual playback duration, matching deliverables and stale-input handling are combined in one operation. Prompt-based video shortening already exists; it is not claimed as a new category. |
| Demo clarity | 10% | The original submitted recording is 110.022 seconds. Revised media has also been verified locally and awaits publication. Recorded app states, fictional content, synthesized narration and shortened processing waits are identified. |

The weights come from the event requirements recorded in the [submission checklist](SUBMISSION_CHECKLIST.md). They describe how the evidence maps to the rubric; they do not predict a score or an award.

## What the completed runs establish

- A 120-second request produced a 116.770-second delivery with 26 passed checks.
- A 90-second amendment produced an 86.203-second delivery with 25 passed checks.
- A 30-second request was blocked because mandatory complete recordings need 53.969 seconds. It created no outputs, and independent readbacks confirmed the previous video, deck and handoff were unchanged.
- A custom 75-second request produced a 53.969-second delivery with 24 passed checks. The application reads custom Gmail text; it does not select a prerecorded result by scenario name.
- A subsequent ambiguous brief returned `needs_review`, recorded no outputs, and preserved the custom run's last-ready reference. This was a report and reference check, not another independent cloud preservation readback.
- An earlier controlled live brief change stopped a run as stale before publication.
- Buyer and operator briefs with the same 90-second cap and required closure produced 85.603- and 86.203-second deliveries, selecting different optional clips. Both passed 25 delivery checks. Independent follow-up checks passed for both; the operator delivery was preserved after another impossible request.
- The imported Harbor source produced a 43.601-second delivery under a 60-second cap, with 24 checks and ten independent readback checks. Its first brief returned `needs_review`; the clarified brief and both outcomes remain public. No interpreter changes were made to force that case through.

See [verification evidence](EVIDENCE.md) for exact runs, sanitized receipts and test conditions.

The separate predeclared model evaluation passed 6/6 on six first calls, consuming 11,028 reported tokens. Model priorities met the expected audience selection in 4/4 cases versus 2/4 for the source-priority baseline. The baseline retains model-extracted hard constraints, and the evaluation performs no app deliveries. This is a small authored functional check, not general model accuracy or customer validation.

## Boundaries to explain

The model interprets wording and ranks optional clips; code checks recognized directives and solves the selection problem. The language audit is deliberately limited and can require review. Source owners provide accurate transcripts, labels and declared dependencies for 1–18 prepared recordings. The importer generates the source deck from `slide_text`; it does not import an existing designed deck. The agent cannot transcribe or split arbitrary footage, rewrite narration, accelerate playback, edit inside a clip or establish arbitrary semantic equivalence.

Google Slides checks compare structured source and copied content, not pixel-identical rendering. Cloud operations are not one atomic transaction: a later failure can leave private unpromoted artifacts for reconciliation. An unaddressed handoff draft is created, and no email is sent.

The original release's public access, hashes, video, captions and 166-test Linux CI result were verified. The official form confirmed the original submission at 21:06 UTC on September 13, 2026. The strengthened source has 213 passing local tests; publication, new CI and revised media checks remain separate pending gates in the [submission checklist](SUBMISSION_CHECKLIST.md).
