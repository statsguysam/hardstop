# Hackathon review

HardStop's strongest evidence is the complete revision across three real applications, with observable checks and a preserved previous delivery when a request cannot be fulfilled. The claim is narrower than automatic video editing: it coordinates a constrained whole-clip revision and verifies its deliverables.

| Criterion | Weight | Evidence and practical limit |
| --- | ---: | --- |
| Technical execution | 30% | Gmail requirements, Dropbox recordings and output, Google Slides source and copied deck, a runtime model, and real FFmpeg rendering all participate in the completed runs. The source contains eight registered clips. |
| Reliability | 25% | 166 automated tests, a separate 250-catalog planner oracle, source-to-copy content checks, uploaded-byte readback, and independent preservation checks after the impossible request. Checks are point-in-time observations across separate services. |
| Usefulness | 20% | A changed recording slot produces an updated playable video and corresponding editable deck. A custom 75-second Gmail brief also ran successfully. Broader customer demand has not been validated. |
| Originality | 15% | Mandatory content, declared prerequisites, actual playback duration, matching deliverables and stale-input handling are combined in one operation. Video shortening itself is not claimed as a new category. |
| Demo clarity | 10% | The final recording is 110.022 seconds and shows successful cuts and the impossible request. The fixtures and synthesized narration are labeled, and shortened processing waits are identified. |

The weights come from the event requirements recorded in the [submission checklist](SUBMISSION_CHECKLIST.md). They describe how the evidence maps to the rubric; they do not predict a score or an award.

## What the final runs establish

- A 120-second request produced a 116.770-second delivery with 26 passed checks.
- A 90-second amendment produced an 86.203-second delivery with 25 passed checks.
- A 30-second request was blocked because mandatory complete recordings need 53.969 seconds. It created no outputs, and independent readbacks confirmed the previous video, deck and handoff were unchanged.
- A custom 75-second request produced a 53.969-second delivery with 24 passed checks. The application reads custom Gmail text; it does not select a prerecorded result by scenario name.
- A subsequent ambiguous brief returned `needs_review`, recorded no outputs, and preserved the custom run's last-ready reference. This was a report and reference check, not another independent cloud preservation readback.
- An earlier controlled live brief change stopped a run as stale before publication.

See [verification evidence](EVIDENCE.md) for exact runs, sanitized receipts and test conditions.

## Boundaries to explain

The model interprets wording and ranks optional clips; code checks recognized directives and solves the selection problem. The language audit is deliberately limited and can require review. The agent cannot rewrite narration, accelerate playback, edit inside a clip or establish arbitrary semantic equivalence.

Google Slides checks compare structured source and copied content, not pixel-identical rendering. Cloud operations are not one atomic transaction: a later failure can leave private unpromoted artifacts for reconciliation. An unaddressed handoff draft is created, and no email is sent.

Public repository access, playable release links, remote CI and the actual submission confirmation are separate checks in the [submission checklist](SUBMISSION_CHECKLIST.md). Local test success does not establish those external results.
