# HardStop

**The slot is now 90 seconds. The result and disclaimer still have to stay.**

HardStop helps producers reuse prerecorded presentation segments and matching decks when a slot changes. It reads the revised brief in Gmail, makes a shorter video from the recordings in Dropbox, and builds a matching Google Slides deck. It checks required content, source order, actual runtime, and saved deliverables before preparing the handoff. When a request cannot fit, it explains why and keeps the last verified cut.

**[Watch the 1:50 demo](https://statsguysam.github.io/hardstop/)**

[Download the recording](https://github.com/statsguysam/hardstop/releases/download/v0.1.0/hardstop-demo.mp4) | [Read the test evidence](docs/EVIDENCE.md)

Beyond the presets, a [custom 75-second Gmail brief](docs/evidence/custom-75.json) produced a verified 53.969-second delivery through the real apps. In a separate [controlled live test](docs/evidence/stale-brief.json), changing the real brief after the model responded stopped publication and preserved the previous delivery. Custom text is interpreted at runtime.

![HardStop verified 90-second delivery](docs/images/hardstop.png)

## Three apps, one delivery

| App | Input | Action and verification |
| --- | --- | --- |
| **Gmail** | A dedicated producer-brief draft, including amendments | Read the current requirements; create an unaddressed handoff draft with the verified output references. No email is sent. |
| **Dropbox** | Immutable prerecorded clips and their catalog | Download selected clips, verify their hashes and durations, upload the rendered MP4, then download it again and compare the bytes. |
| **Google Slides** | One source slide for each recorded segment | Copy the source presentation, retain the selected slides, then read back their content and order. The source deck remains intact. |

The runtime model is **`gpt-6-astra` through the OpenAI Responses API**, with a strict JSON schema. It interprets the brief and supplies exact evidence quotations. Python validates that interpretation, enforces declared dependencies, and chooses the feasible set of complete clips. FFmpeg renders it; FFprobe measures the actual output. The model does not execute tools or provide trusted timing estimates.

## The demonstration

The source is **Relay**, a fictional product presentation with eight recordings and synthesized narration. Its measured source duration is **179.071 seconds**. All example outcomes are invented.

1. **120-second brief:** produce a playable cut, a matching copied deck and an unsent handoff draft.
2. **90-second amendment:** remove the rollout, favor the workflow explanation, and keep all mandatory content. The live five-clip delivery measures **86.203 seconds**.
3. **30-second request:** reject the impossible constraint. The mandatory clips and declared prerequisite alone need **53.969 seconds**. Preserve the previous valid delivery.

The recorded demo is **110.022 seconds**, within the two-minute limit. The scenario buttons are conveniences for repeatable demonstrations.

The source catalog declares that `result` requires `pilot_context`. HardStop verifies that specific dependency and original ordering. It does not claim to discover every important nuance or prove general semantic preservation.

## Run locally

Run commands from the repository root; this prototype supports source checkouts. Use macOS or Linux with **Python 3.10+**, `ffmpeg` and `ffprobe` on `PATH`. The normal application uses the Python standard library. Fresh sample narration generation requires **macOS `say` and Pillow**; the media pipeline itself does not require Pillow.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m unittest discover -s tests -v
```

The final local suite passed **166 tests** with FFmpeg available. A separate planner stress check matched an independent combinations-search oracle on **250 generated catalogs**; those cases are not included in the 166-test count. Tests do not need API credentials. They use controlled provider responses and local media fixtures; media tests are skipped when FFmpeg tools are unavailable. A passing unit suite is separate from a successful live API run.

For a fresh sample on macOS:

```bash
brew install ffmpeg
python3 -m pip install Pillow
python3 scripts/generate_demo_assets.py
```

This creates labeled recordings and a measured manifest under `.state/demo-assets/`. Generation uses the Mac's speech service; an execution sandbox may need access to that service. Existing generated recordings are reused only after catalog, hash, duration and decode verification.

**Portable source bundle:** [Download hardstop-source.zip](https://github.com/statsguysam/hardstop/releases/download/v0.1.0/hardstop-source.zip). It contains the eight fictional recordings, optional slide cards and a portable manifest; it contains no credentials or cloud account IDs. Download it, compare its SHA-256 with the published release checksum, then import it on macOS or Linux:

```bash
python3 scripts/import_demo_assets.py /path/to/hardstop-source.zip
```

Import requires Python and FFmpeg, but no Pillow, `say` or API credentials. It checks the committed catalog, rejects unexpected archive paths and oversized content, verifies clip hashes, measured durations and full decoding, then installs `.state/demo-assets/`. It refuses to overwrite an existing source directory. Use `--output /path/to/new-source-directory` for a separate verification; `seed` uses the default `.state/demo-assets/` location. Fresh generation remains available through the macOS commands above.

### Configure your own API access

Live execution needs your own Google, Dropbox and OpenAI developer access. Connected chat plugins do not supply these standalone runtime credentials. The setup helper stores credentials locally with owner-only permissions under `.credentials/`, which is ignored by Git. Set `HARDSTOP_CREDENTIALS_DIR` before running commands if you use another private location.

**Google:** create a dedicated Cloud project; enable Gmail, Google Slides and Google Drive APIs. Configure the OAuth consent screen, add your own account as a test user if the app is in testing, and create a **Desktop app** OAuth client. Download its JSON and run:

```bash
python3 configure.py google-client /path/to/downloaded-desktop-client.json
python3 configure.py google
```

The requested scopes are `gmail.readonly`, `gmail.compose` and `drive.file`. Google consent technically allows sending under the compose scope; HardStop implements draft creation only. `drive.file` limits access to files authorized for the app, so `seed` creates its own source presentation instead of assuming access to an arbitrary existing deck. See [Google's OAuth setup guide](https://developers.google.com/workspace/guides/configure-oauth-consent).

**Dropbox:** create a scoped **App folder** application in the [Dropbox developer console](https://www.dropbox.com/developers/apps). Enable `files.content.read`, `files.content.write` and `files.metadata.read`, and register this exact redirect URI: `http://127.0.0.1:8765/dropbox/callback`. Then authorize using the public app key:

```bash
python3 configure.py dropbox --app-key YOUR_PUBLIC_APP_KEY
```

API paths are relative to that dedicated Dropbox app folder. The OAuth flow requests offline access so access tokens can refresh. It does not need Dropbox sharing permissions.

**OpenAI:** create an API key with Responses API access and available API credit. Enter the key at the hidden terminal prompt:

```bash
python3 configure.py openai-key --model gpt-6-astra
```

Do not paste credentials into the repository or chat. API requests use `store: false`; the local report records the response identity, model, usage and validated interpretation. See the [OpenAI API quickstart](https://developers.openai.com/api/docs/quickstart).

### Seed and execute

The following commands create clearly labeled fictional demo artifacts in your three app accounts. They operate on those dedicated resources and never send email.

```bash
python3 -m hardstop.cli seed
python3 -m hardstop.cli brief original
python3 -m hardstop.cli run --id demo-120
python3 -m hardstop.cli brief amendment
python3 -m hardstop.cli run --id demo-90
python3 -m hardstop.cli brief impossible
python3 -m hardstop.cli run --id demo-30
python3 -m hardstop.cli status
python3 -m hardstop.cli serve --port 8766
```

Open [the local review interface](http://127.0.0.1:8766). Use **Write your own brief** to save an original brief to the dedicated Gmail draft; the runtime model reads that text on its next run. The interface shows run progress, requirements, selected clips, verification checks and playable verified outputs. `brief ambiguous` exercises an unclear request. Use a new run ID for a new execution; calling an existing ID returns its saved report without repeating writes.

Run reports and media are saved under `.state/runs/<run-id>/`. Only a fully verified `ready` run updates `.state/latest_ready.json`. `infeasible`, `needs_review`, `stale`, `failed` and `unknown` outcomes preserve the prior reference. An interrupted or uncertain write requires reconciliation; changing the run ID is not a substitute for checking what the service already created.

## Reliability and evidence

- Grounded interpretation: strict response schema, known segment IDs, exact brief quotations and a scoped deterministic pattern audit of explicit clip directives and active timing clauses. Omitted recognized requirements, reversed polarity, and uncertain timing block the run.
- Deterministic planning: mandatory dependency closure, exclusions, original order and a separate selection verifier. Ambiguity blocks execution.
- Actual media checks: source hashes, measured durations, complete-clip rendering, full audio/video decode and a measured final deadline check.
- Cross-app verification: compare copied Slides content with the captured source before and after trimming, verify exact retained slide order, download the Dropbox upload for byte-for-byte comparison, and read back the unaddressed Gmail handoff draft.
- Change handling: source fingerprints and revisions are checked again throughout the run; stale inputs prevent promotion.
- Recorded write outcomes: local journals, unique artifact names and known resource IDs. Unknown writes are not blindly retried.

**Verified live results:** the final 120-second brief produced a 116.770-second delivery with 26 passed checks; the final 90-second amendment produced an 86.203-second delivery with 25. The 30-second request was infeasible and created no outputs. Independent cloud readbacks before and after that request confirmed the previous video, copied deck and unaddressed handoff were unchanged. The custom 75-second run passed 24 checks. A subsequent ambiguous brief returned `needs_review`, created no outputs and retained the custom run's last-ready reference. An earlier controlled change to the real Gmail draft during a run also stopped publication and preserved the previous delivery. [Read the sanitized receipts and test conditions](docs/EVIDENCE.md).

There is no distributed transaction across Gmail, Slides and Dropbox. A failed run can leave a private copied deck or uploaded file for reconciliation. Verification is point-in-time evidence; another person can change a cloud artifact after a run finishes. See [architecture and failure behavior](docs/ARCHITECTURE.md).

## Scope

This prototype selects complete prerecorded segments in source order, with one matching slide per segment. The supplied workflow uses eight registered recordings; arbitrary media ingestion is not implemented. The planner accepts at most 18 segments. The scoped language audit can require review for unfamiliar wording, even when a person could resolve it. HardStop does not rewrite speech, change playback speed, cut inside clips, estimate a live speaker's delivery, or guarantee unrestricted semantic preservation. Deck checks compare structured content, not pixel-identical rendering. Fresh fixture generation is macOS-specific; Windows is not a supported runtime because workflow locking uses `fcntl`.

The review server binds to loopback for local use. The public demo page plays a recorded video; it exposes no live credentials or agent mutation endpoints.

[MIT license](LICENSE) | [Demo script](docs/DEMO_SCRIPT.md) | [Hackathon review](docs/HACKATHON_REVIEW.md) | [Submission checklist](docs/SUBMISSION_CHECKLIST.md)
