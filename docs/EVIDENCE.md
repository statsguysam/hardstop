# Verification evidence

HardStop has completed real API runs across Gmail, Google Slides, Dropbox, and the runtime model. The Relay source presentation and outcomes are fictional and its narration is synthesized. Preset Gmail briefs are labeled fixtures; additional authored audience briefs were saved to the dedicated draft. Full deliveries, a model-and-planner evaluation, and isolated automated tests are described separately below.

## Current release runs

The v0.3.0 presentation uses new, dedicated source workspaces and regenerated fictional recordings with a stock synthetic voice. Relay has eight recordings totaling **177.036 seconds**; Harbor has six totaling **83.202 seconds**. The previous recordings and receipts below remain unchanged. The new [source bundles](evidence/source-bundles-v3.json) were extracted, imported, fully decoded and compared with their registered source hashes.

| Recorded case | Result | Measured delivery | Checks during the run |
| --- | --- | ---: | --- |
| [Buyer audience, 90-second cap](evidence/buyer-polished.json) | Ready; optional `problem` | 87.868 seconds | 25 passed |
| [Operator audience, 90-second cap](evidence/operator-polished.json) | Ready; optional `workflow` | 88.368 seconds | 25 passed |
| [Impossible 30-second revision](evidence/impossible-polished.json) | Infeasible; no new outputs | No render | Required minimum is 55.101 seconds |
| [Harbor, 60-second cap](evidence/harbor-polished.json) | Ready; required clips and context | 44.701 seconds | 24 passed |
| [Earlier Harbor wording](evidence/harbor-review-polished.json) | Needs review; no delivery | No render | An instruction did not unambiguously name a clip |
| [Earlier operator attempt](evidence/operator-download-failure-polished.json) | Failed while downloading a source clip; no outputs | No render | 16 checks completed before the failed download |

The buyer and operator retain the same `pilot_context`, `result`, `disclaimer` and `call_to_action` clips in source order. Their only selected optional clips differ. The successful runs took **60.215**, **64.619** and **54.018 seconds** respectively for buyer, operator and Harbor, including app transfers, model interpretation, rendering and verification. Their reported model usage was **1,824**, **1,862** and **1,371 tokens**. These are observations on one machine and connection, not speed guarantees or measured user time savings.

A [separate provider readback](evidence/delivery-readbacks-v3.json) passed **10 buyer checks, 12 operator checks and 10 Harbor checks**. It compared downloaded video bytes/revisions, copied deck content/order and the exact unaddressed handoff drafts with the saved run records. The operator readback happened after the impossible request and additionally confirmed no new outputs and an unchanged last-ready reference. The [recorded-result inspector](https://statsguysam.github.io/hardstop/explore.html) shows these cases without account setup; it performs no live actions.

The successful operator result followed a failed attempt. That [earlier attempt](evidence/operator-download-failure-polished.json) stopped after **142.261 seconds** during a Dropbox source download, before rendering or publishing outputs. Its **1,832 reported model tokens** are retained separately from the successful-run totals. The initial Harbor wording also required clarification before the successful run. The receipts include the exact labeled fictional briefs; these outcomes are not presented as uninterrupted first-attempt success.

Source registration encountered a separate unknown Dropbox upload outcome. Setup kept the pending path in its private journal. When resumed, the pending-upload code downloaded that exact existing file and checked its hash before continuing; it did not blindly repeat the upload. The [reconciliation receipt](evidence/registration-recovery-v3.json) compares the interruption and completed journals, confirms the same registration identity, matching recording bytes and all eight uploads recorded, and notes that it is not a complete provider request trace.

The [current demonstration](evidence/demo-recording-v3.json) measures **110.022 seconds**, with full decode, audio-level and caption checks recorded.

The current local suite passed **216 tests**, including the durable public-inspector checks and the Harbor holdout evaluator tests. Eight offline inspector scenarios cover the four actual recorded cases, mismatched release hashes, missing preservation proof, unsafe markup and unavailable receipts. These tests use saved data and do not constitute additional provider runs. [Release artifact hashes](evidence/release-v3.json) identify the prepared files; anonymous publication checks are recorded separately after upload.

## Original observed live runs (v0.1.0)

| Request | Saved local run | Observed result | Actual rendered duration | Recorded checks |
| --- | --- | --- | --- | --- |
| Original, 120 seconds | `20260913T202023-1b348bc8` | Ready | 116.770 seconds | 26 passed |
| Amendment, 90 seconds | `20260913T203255-8bd1f202` | Ready | 86.203 seconds | 25 passed |
| Impossible, 30 seconds | `20260913T203635-5b572d1c` | Infeasible; no new outputs | No render started | Mandatory minimum exceeds budget |
| Custom, 75 seconds | `20260913T204335-893b5aac` | Ready | 53.969 seconds | 24 passed |
| Ambiguous brief | `20260913T204910-873095a5` | Needs review; no new outputs | No render started | Unconfirmed timing and unnamed important content |

The original, amendment and impossible rows supplied the sequence for the **110.022-second original submission recording**. [Recorded media checks](evidence/demo-media.json) include its measured duration, full decode, audio levels and caption checks. The custom 75-second challenge was an additional live run. It retained `pilot_context`, `result`, `disclaimer` and `call_to_action`, using the runtime model's interpretation of custom Gmail text. The four complete mandatory clips fit the cap; no optional complete clip fit the remaining time.

Every ready run above read the connected Gmail draft, copied and trimmed the real Google Slides source deck, downloaded real Dropbox source files, rendered complete clips with FFmpeg, uploaded the resulting video, downloaded it again for SHA-256 comparison, and created an unsent Gmail handoff draft. The checks recorded source-to-copy content equality, retained slide order, successful media decoding, output revisions, and fresh input revisions before promotion. Check counts differ because each selected source recording gets its own integrity check.

The 30-second request was blocked because its mandatory clips and declared prerequisites require **53.969 seconds**. Its report has an empty output collection, an infeasible plan, and an intentionally failed feasibility check. That failed check is the expected outcome for this request.

The later ambiguous brief left the slot at one or two minutes and referred to an unspecified important part. It returned `needs_review` with no output resources recorded. The local last-ready reference still pointed to the successful custom 75-second run. This verifies the recorded blocked outcome and preserved reference; no additional independent cloud readback was performed after this ambiguity test.

## Live audience versions

These are the earlier v0.2.0 audience deliveries on the original Relay recordings. The current release results are above.

Two further completed runs used the same Relay recordings, **90-second cap**, explicit required IDs (`result`, `disclaimer`, `call_to_action`), empty exclusion list and declared `pilot_context` dependency. The briefs described their audiences without naming the preferred optional clip.

| Audience | Saved local run | Selected optional clip | Actual rendered duration | Result |
| --- | --- | --- | --- | --- |
| Prospective buyer assessing the coordination problem | [`20260913T212354-e378ced3`](evidence/buyer-audience.json) | `problem` | 85.603 seconds | Ready; 25 checks passed |
| Operator learning the day-to-day process | [`20260913T212933-b404cd00`](evidence/operator-audience.json) | `workflow` | 86.203 seconds | Ready; 25 checks passed |

Both selected `pilot_context`, `result`, `disclaimer` and `call_to_action` in source order alongside the optional clip. Both recorded `gpt-6-astra` interpretations, full media decoding, measured deadline checks, matching copied Slides content/order, uploaded-byte readback, an unaddressed Gmail handoff readback, and final input/output checks. These are actual three-app deliveries, separate from the evaluation below.

The [subsequent 30-second request](evidence/impossible-after-operator.json), run `20260913T213746-97c1decd`, was infeasible and recorded no outputs. An [independent post-run readback](evidence/delivery-readbacks-v2.json) then downloaded both audience videos and read their copied decks and handoff drafts: **10 checks passed for the buyer** and **12 for the operator**. The operator checks additionally confirmed that the impossible request created no outputs and preserved the last-ready reference. These are recorded point-in-time provider checks, not a guarantee against later changes.

This demonstrates an audience-dependent choice within one authored scenario. It does not demonstrate customer demand, time savings, automatic discovery of all needed context, or superiority to other editing products. [Producer use case and market-evidence limits](USE_CASE.md).

## Imported source: Harbor

This section records the earlier v0.2.0 Harbor source and deliveries. The regenerated source has different measured durations, listed above.

A separate six-clip fictional inventory-training package exercised the general source importer and a new three-app workspace. Its recordings were synthesized beforehand and supplied as local MP4s; the importer itself did not synthesize media. The source declared `finding` dependent on earlier `setting`, with unrelated IDs and content from the Relay catalog. [Source metadata](../fixtures/examples/harbor-catalog.json) and [both authored briefs](../fixtures/examples/harbor-briefs.json) are public.

The [initial request](evidence/harbor-initial-review.json), `20260913T213143-57fd898f`, returned `needs_review`. The generic instruction “Retain complete clips and their declared prerequisites” was outside the supported explicit clip grammar. No delivery was created. A clarified brief removed that generic instruction and its redundant embedded subject line; the importer, interpreter and audit were not tuned to make the request pass.

The [clarified run](evidence/harbor-imported-source.json), `20260913T213617-67c33f4a`, completed at **43.601 seconds** against the **60-second cap**, retaining `setting`, `finding`, `limitations` and `next_step`. It passed **24 delivery checks** and created the video, matching copied deck and unsent handoff. A separate [post-run provider readback](evidence/delivery-readbacks-v2.json) passed **10 checks** for its video bytes/revision, slide content/order and unaddressed handoff content/identity.

Both attempts are retained because the clarification is a real limit of the current grammar. This is a second synthetic source integration test, not a customer onboarding study, independent validation of the declared transcripts, or proof that arbitrary unprepared video works. [Supported package format](SOURCE_GUIDE.md).

## Six-case model evaluation

[The complete public report](evidence/audience-evaluation.json) retains all six original results, declared ground truth, prompts, sanitized catalog input, model outputs, deterministic plans, checks and usage. The suite was fixed before its first call; its SHA-256 is `116a189ea79db0b3edf2c5edcf4ec355ec9e121ff67cacd23ff51d0edd4d27b5`. Each case received **one** genuine Responses API interpretation. There were no retries, prompt repairs or selective resampling.

| Predeclared case | Expected outcome | Observed outcome |
| --- | --- | --- |
| Buyer audience | Feasible; optional `problem` | Passed; planned 85.603 seconds |
| Operator audience | Feasible; optional `workflow` | Passed; planned 86.203 seconds |
| Buyer with supported passive requirements and 1.5-minute wording | Same buyer selection | Passed; planned 85.603 seconds |
| Operator with a negated removal requirement | Same operator selection | Passed; planned 86.203 seconds |
| Request to rewrite the result narration | `needs_review`; no selected output | Passed; model identified the unsupported edit |
| Unconfirmed 60- or 90-second timing | `needs_review`; no selected output | Passed; uncertain timing blocked planning |

The score was **6/6**. A baseline kept each model interpretation's hard constraints but removed its optional priorities, using the source catalog's fixed values instead. That baseline passed **4/6 overall** and **2/4 audience cases**; model priorities passed **4/4 audience cases**. This comparison isolates optional ranking; it is not a fully model-free baseline. Audience ground truth was deliberately strict, with one expected optional clip for each described need. Other editorial choices could be defensible and would still count as failures in this test.

The six calls used `gpt-6-astra` and reported **8,210 input tokens + 2,818 output tokens = 11,028 total tokens**. Usage was available for every call. These totals exclude the separate full-app audience runs. The evaluator also captures provider usage before downstream validation, so a rejected interpretation does not silently disappear from reported consumption.

The evaluation invoked interpretation and the ordinary deterministic planner only. **It rendered no video and made no Gmail, Slides or Dropbox writes.** Six authored cases on one fictional catalog are a focused functional check, not a general accuracy estimate or customer validation. Supported paraphrases were within the existing language audit; validation was not weakened for the test.

Inspect or repeat the entire suite with your own configured OpenAI access and the Relay manifest:

```sh
python3 scripts/evaluate_briefs.py
python3 scripts/evaluate_briefs.py --live --source .state/demo-assets/manifest.json \
  --output .state/evaluations/new-evaluation.json
```

The first command lists cases without any API calls. The second saves a new checkpointed report and refuses to overwrite an existing output file. It requires the measured Relay manifest produced by generation or portable-bundle import; it is not an evaluation of arbitrary source packages. Preserve later reports separately from the original evidence.

## Separate Harbor holdout

The [Harbor holdout report](evidence/harbor-holdout.json) extends the check to the original six-recording Harbor catalog and a new 65-second cap. Its cases and exact expected selections were [declared at 22:15:47 UTC](evidence/harbor-holdout-declaration.json) before any attempt. The case SHA-256 is `fdbd887fce03d2e813ac1fa07baba8a407173236ee333aff57e9eba7529fdc13`; the declaration also records the catalog and implementation hashes. The original Relay evaluation was not modified.

This is an authored holdout, developed after reviewing the earlier Relay evaluation and Harbor deliveries. It is not an independently sampled or blinded benchmark. The catalog, cap and wording differ; the sample remains small and intentionally bounded.

| Fixed case | Expected outcome | Observed model-and-planner outcome |
| --- | --- | --- |
| Newcomer audience | Optional introduction | Passed; 61.535-second plan |
| Experienced operator audience | Optional walkthrough | Passed; 64.535-second plan |
| Explicit walkthrough exclusion | Introduction and required closure | Passed; 61.535-second plan, no walkthrough |
| Impossible 30-second request | Infeasible | Passed; 43.601-second mandatory minimum, no selection |
| Unconfirmed 45- or 65-second slot | Needs review | Passed; no selection |
| Rewrite the finding narration | Needs review | Passed; no selection |

**6/6 responded model cases passed**, using `gpt-6-astra`. Removing only the model's optional priorities while retaining extracted hard constraints passed **5/6**; the newcomer selection distinguishes the model ranking from the fixed catalog baseline here. Responses reported **5,822 input + 2,392 output = 8,214 tokens** across the six completed calls. These were plans, not rendered or delivered outputs. No Gmail, Slides or Dropbox calls occurred.

There were **12 client attempts across two batches**. The [first six attempts](evidence/harbor-holdout-transport.json) all failed in 0 to 3 milliseconds without a Responses result under restricted network permissions. Their usage is unknown; the report's empty aggregate of known usage is not evidence of zero cost. A [separate operational rerun declaration](evidence/harbor-holdout-rerun-declaration.json), saved at 22:17:44 UTC, records that failure and authorizes one full rerun with network permission. All six unchanged prompts and expectations were then attempted once, from 22:17:51 to 22:18:45 UTC. No case was selectively retried or rewritten, and no model, interpreter or planner change was made between these batches. This operational exception is disclosed rather than described as six first attempts.

The evaluator is [`scripts/evaluate_harbor_holdout.py`](../scripts/evaluate_harbor_holdout.py). It requires the original measured Harbor catalog, verifies the saved declaration against the current cases, source and implementation before live calls, and refuses to replace existing reports. The original v0.2 Harbor source is used for these numbers; later regenerated recordings may have different durations.

```sh
python3 scripts/evaluate_harbor_holdout.py --source .state/harbor-workspace/source.json \
  --declaration .state/evaluations/my-harbor-declaration.json
python3 scripts/evaluate_harbor_holdout.py --live --source .state/harbor-workspace/source.json \
  --declaration .state/evaluations/my-harbor-declaration.json \
  --output .state/evaluations/my-harbor-result.json
```

The first command makes no model calls. The second requires the user's configured Responses credentials. Two additional offline tests check predeclaration before calls, exact duration boundaries, baseline differences, and retention of a failed request while later cases continue. Those tests use controlled responses; they are distinct from the recorded live result.

## Independent preservation readback

The final 90-second output was read independently before and after the final impossible request. Both checks downloaded the full Dropbox video and compared its SHA-256 with the completed local file. The second read also confirmed unchanged Dropbox revision and size, copied Slides content fingerprint and slide order, and the specific Gmail handoff's fingerprint and unaddressed state. The last-ready reference still pointed to the 90-second delivery after the blocked request. All nine preservation checks passed. [Read the sanitized preservation receipt](evidence/final-readback.json).

These verification operations made no cloud writes. The handoff contained 96 words; its body, addresses, application object IDs and URLs are not included in the public preservation receipt.

An earlier **controlled live fault test** exercised a different failure: the real Gmail brief was changed immediately after the real model response. Run `live-stale-brief` stopped as stale before rendering or publication, created no outputs, and preserved the earlier custom delivery (`20260913T194144-e2540c8a`). Further Dropbox and Slides readbacks confirmed the prior output was unchanged. This was an intentionally injected live race, distinct from a naturally occurring incident and from the final impossible request.

The model receipts for these observed runs identify `gpt-6-astra`. Each exported receipt retains its actual recorded model name, numeric usage, and elapsed time. Later runs may use a different configured model; the exporter does not rewrite earlier model provenance.

## Public receipt exports

[Original 120-second receipt](evidence/original-120.json) | [90-second amendment](evidence/amendment-90.json) | [Impossible 30-second request](evidence/impossible-30.json) | [Custom 75-second challenge](evidence/custom-75.json) | [Ambiguous brief](evidence/ambiguous-brief.json) | [Controlled stale-input test](evidence/stale-brief.json)

Run the following command from the repository root to produce the five redacted JSON receipts under `docs/evidence/`:

```sh
python3 scripts/export_evidence.py \
  --run original-120=20260913T202023-1b348bc8 \
  --run amendment-90=20260913T203255-8bd1f202 \
  --run impossible-30=20260913T203635-5b572d1c \
  --run custom-75=20260913T204335-893b5aac \
  --run ambiguous-brief=20260913T204910-873095a5
```

The command reads only explicitly selected local reports. It makes no API calls and cannot turn a failed, stale, unknown, ambiguous, or infeasible run into a ready run. Earlier receipts remain historical evidence; their dates and local run IDs are not rewritten to imply they came from the final sequence.

Exports retain status, timestamps, stage events, constraints, plan, checks, media measurements, output SHA-256, and a numeric model usage summary. Provider object IDs, response IDs, URLs, absolute paths, and temporary download links are omitted. The local run identifier remains so the builder can reconcile a public receipt against its private source report.

Brief text is included only when its subject and body exactly match a checked-in fixture whose body begins with `FICTIONAL DEMO BRIEF`. Custom brief content is replaced with hashes; free-form excerpts, event messages, and reasons are also redacted to prevent indirect disclosure.

These exports are saved receipts generated by the application, not independently signed provider attestations. Review them alongside the recorded demonstration and the runnable code. A receipt establishes what that run recorded at its verification point; it does not guarantee that remote objects remain unchanged afterward.

## Automated tests and their limits

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
```

The current local suite passed **216 tests**, including FFmpeg operations, loopback-server checks and the recorded-result inspector. JavaScript syntax passed. A separate planner stress check compared **250 generated catalogs** against an independent combinations-search oracle, including objective value and the shorter-duration tie break. It passed; those cases are **not** included in the unit-test count. The recorded stress check also exercised the 18-segment boundary. [Read the oracle summary](evidence/planner-stress.json). This is a sampled local test, not an exhaustive proof over all inputs or a live provider check.

A fresh committed-source export imported the portable release bundle and loaded the CLI without credentials. The [earlier GitHub Linux CI run](https://github.com/statsguysam/hardstop/actions/runs/34782456480) also passed all 166 tests with FFmpeg installed and no media-test skips. That run tested commit `9c8ecf0`, before the general source importer, evaluation harness and additional UI checks. It does not validate those later changes.

[GitHub Linux CI for the strengthened release](https://github.com/statsguysam/hardstop/actions/runs/34784957386) passed **213 tests** in 5.541 seconds with FFmpeg installed and no skipped tests. It tested source commit `90654b77e16710d4dbd7825d94f85d8f16709aa5`. JavaScript syntax also passed.

The current suite adds source-import and registration cases, evaluation scoring/failure accounting, offline interface replay using recorded audience interpretations, and public-inspector identity and failure checks. Source tests verify real local media boundaries and use isolated provider responses for registration. The UI tests use synthetic delivery states around the saved model outputs; they are not further live deliveries. Rerun the complete suite for the current source revision.

The suite covers deterministic planning, model-output validation, provider adapters, workflow failures, review-server access controls, OAuth flows, and private credential handling. Adversarial cases include omitted or reversed clip directives, unsupported edits hidden alongside a known clip, per-clip timing mistaken for a total limit, changed source content immediately before copying, altered copied content before readback or during trimming, malformed write identities, missing upload revisions, interrupted runs, and corrupt output readback. The media tests generate and decode real short videos with FFmpeg. Other external provider responses are isolated test doubles; they do not prove live credentials or remote app behavior.

Copied-deck verification compares the retained slide objects and presentation-wide content, including page size, layouts, masters, notes and styles, against the captured source. The delivery title may differ. Presentation identity, revision IDs, timestamps, thumbnail URLs and expiring image-URL signatures are excluded from the stable comparison. The native demo source has no external images. This checks structured content, not identical pixels or the meaning of an arbitrary presentation.

The CI workflow installs FFmpeg and runs the tests without provider credentials. The live runs above supply the separate integration evidence. Language auditing recognizes a limited grammar; unfamiliar wording can require review. Cross-app checks are repeated observations, not a distributed transaction. Verification enforces explicit requirements and declared dependencies; it does not claim complete semantic preservation or an independently validated market need.

## Original published submission

The original repository release and its assets were fetched without authentication. Downloaded video, captions, output cut, source archive and checksum-file hashes matched the reviewed local files. The GitHub Pages player played through the 110.022-second video, and English captions were enabled and visibly displayed. The official form confirmed one submission at 21:06 UTC on September 13, 2026. The contact address and form confirmation are kept outside public source. [Original public-access receipt](evidence/publication.json). The original release remains available; the strengthened release is documented below.

## Strengthened release

[Version 0.2.0](https://github.com/statsguysam/hardstop/releases/tag/v0.2.0) contains the revised **110.022-second** demonstration and English captions, both fictional source packages, and the buyer, operator and Harbor output videos. All eight released assets, including the checksum file, were fetched **without authentication** and matched the verified local bytes. [Anonymous download checks](evidence/public-downloads-v2.json), [artifact hashes](evidence/release-v2.json), [video verification](evidence/demo-recording-v2.json).

The actual public source archive at release commit `90654b7` and the released Harbor ZIP were also fetched without authentication. The downloaded implementation loaded the CLI and independently imported and fully decoded all six Harbor recordings; all measured durations, clip hashes and ten bundle checksums matched. This is a local reproduction from public files, separate from the live three-app run. [Public-source reproduction](evidence/public-source-reproduction-v2.json).

The existing repository and Pages URLs remain the submission entry points. The revised public video played through to **1:50 / 1:50**, and English captions were enabled and visibly displayed. The page, caption file and poster matched the reviewed local bytes when fetched without authentication. [Final publication check](evidence/publication-v2.json). No second form submission was created.
