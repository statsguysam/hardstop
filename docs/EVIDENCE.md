# Verification evidence

HardStop has completed real API runs across Gmail, Google Slides, Dropbox, and the runtime model. The source presentation, narration, and Gmail producer briefs are labeled fictional fixtures. These runs are distinct from the isolated provider mocks used by the automated tests.

## Observed live runs

| Request | Saved local run | Observed result | Actual rendered duration | Recorded checks |
| --- | --- | --- | --- | --- |
| Original, 120 seconds | `20260913T202023-1b348bc8` | Ready | 116.770 seconds | 26 passed |
| Amendment, 90 seconds | `20260913T203255-8bd1f202` | Ready | 86.203 seconds | 25 passed |
| Impossible, 30 seconds | `20260913T203635-5b572d1c` | Infeasible; no new outputs | No render started | Mandatory minimum exceeds budget |
| Custom, 75 seconds | `20260913T204335-893b5aac` | Ready | 53.969 seconds | 24 passed |
| Ambiguous brief | `20260913T204910-873095a5` | Needs review; no new outputs | No render started | Unconfirmed timing and unnamed important content |

The original, amendment and impossible rows are the final sequence used for the **110.022-second demo recording**. [Recorded media checks](evidence/demo-media.json) include its measured duration, full decode, audio levels and caption checks. The custom 75-second challenge was an additional live run. It retained `pilot_context`, `result`, `disclaimer` and `call_to_action`, using the runtime model's interpretation of custom Gmail text. The four complete mandatory clips fit the cap; no optional complete clip fit the remaining time.

Every ready run above read the connected Gmail draft, copied and trimmed the real Google Slides source deck, downloaded real Dropbox source files, rendered complete clips with FFmpeg, uploaded the resulting video, downloaded it again for SHA-256 comparison, and created an unsent Gmail handoff draft. The checks recorded source-to-copy content equality, retained slide order, successful media decoding, output revisions, and fresh input revisions before promotion. Check counts differ because each selected source recording gets its own integrity check.

The 30-second request was blocked because its mandatory clips and declared prerequisites require **53.969 seconds**. Its report has an empty output collection, an infeasible plan, and an intentionally failed feasibility check. That failed check is the expected outcome for this request.

The later ambiguous brief left the slot at one or two minutes and referred to an unspecified important part. It returned `needs_review` with no output resources recorded. The local last-ready reference still pointed to the successful custom 75-second run. This verifies the recorded blocked outcome and preserved reference; no additional independent cloud readback was performed after this ambiguity test.

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

The final local suite passed **166 tests** with FFmpeg available. A separate planner stress check compared **250 generated catalogs** against an independent combinations-search oracle, including objective value and the shorter-duration tie break. It passed; those cases are **not** included in the 166-test count. The recorded stress check also exercised the 18-segment boundary. [Read the oracle summary](evidence/planner-stress.json). This is a sampled local test, not an exhaustive proof over all inputs or a live provider check.

A fresh committed-source export imported the portable release bundle and loaded the CLI without credentials. The [GitHub Linux CI run](https://github.com/statsguysam/hardstop/actions/runs/34782456480) also passed all 166 tests with FFmpeg installed and no media-test skips. That run tested commit `9c8ecf0`; later documentation updates do not change the runtime implementation.

The suite covers deterministic planning, model-output validation, provider adapters, workflow failures, review-server access controls, OAuth flows, and private credential handling. Adversarial cases include omitted or reversed clip directives, unsupported edits hidden alongside a known clip, per-clip timing mistaken for a total limit, changed source content immediately before copying, altered copied content before readback or during trimming, malformed write identities, missing upload revisions, interrupted runs, and corrupt output readback. The media tests generate and decode real short videos with FFmpeg. Other external provider responses are isolated test doubles; they do not prove live credentials or remote app behavior.

Copied-deck verification compares the retained slide objects and presentation-wide content, including page size, layouts, masters, notes and styles, against the captured source. The delivery title may differ. Presentation identity, revision IDs, timestamps, thumbnail URLs and expiring image-URL signatures are excluded from the stable comparison. The native demo source has no external images. This checks structured content, not identical pixels or the meaning of an arbitrary presentation.

The CI workflow installs FFmpeg and runs the tests without provider credentials. The live runs above supply the separate integration evidence. Language auditing recognizes a limited grammar; unfamiliar wording can require review. Cross-app checks are repeated observations, not a distributed transaction. Verification enforces explicit requirements and declared dependencies; it does not claim complete semantic preservation or an independently validated market need.

## Published submission

The repository and every release asset were fetched without authentication. Downloaded video, captions, output cut, source archive and checksum-file hashes matched the reviewed local files. The GitHub Pages player played through the 110.022-second video, and English captions were enabled and visibly displayed. The official form confirmed one submission at 21:06 UTC on September 13, 2026. The contact address and form confirmation are kept outside public source. [Public-access receipt](evidence/publication.json).
