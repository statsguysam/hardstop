# HardStop submission checklist

Local implementation, live validation, release media, and clean source-export checks are complete. Public repository contents, release hosting, signed-out access checks, CI results, and official submission are the remaining publication checks.

The official event page lists a submission deadline of **September 13, 2026, 23:00 UTC**, which is **September 14, 2026, 04:30 IST**. Complete the form before that cutoff; leave time to verify access and the confirmation. The [event page](https://multiappagenthackathon.com/) is the authority if the organizers announce another change.

## Required submission package

- [ ] An accessible GitHub repository containing the actual implementation, fictional source catalog, tests, and setup instructions.
- [x] A README with a concise project overview, the three external apps, setup and run instructions, reliability test evidence, and the demo link.
- [ ] A playable demo recording of **at most two minutes**, with an accessible link in the README. Verify the link while signed out.
- [ ] The team's email address and GitHub URL entered in the [official submission form](https://docs.google.com/forms/d/e/1FAIpQLSclU5z63xMUenxypmW_PTcgXIGgwnENY_mgX87mPeoAWOTIoA/viewform).
- [ ] One submission for this solo team/project. Save the actual confirmation or receipt after submitting.

## What the project must demonstrate

| Judging criterion | Weight | Concrete evidence to show |
| --- | ---: | --- |
| Technical execution | 30% | A working Gmail, model interpretation, Dropbox recordings, rendering, copied Slides deck, Dropbox upload, and Gmail handoff draft sequence using real APIs. |
| Reliability | 25% | Independently checked constraints, measured output duration, complete media decode, byte-for-byte upload readback, actual slide-order readback, and a blocked impossible brief that preserves the last valid output. |
| Usefulness | 20% | A producer changes a recorded presentation slot from 120 to 90 seconds; the video and deck both get rebuilt from the same verified selection. |
| Originality | 15% | Explicit requirement handling across deliverables, declared context dependencies, and a clear explanation when complete required recordings cannot fit. Avoid presenting AI video shortening itself as new. |
| Demo clarity | 10% | A legible successful run followed by the 30-second conflict, within two minutes. Show actual deliverables and outcomes before architecture. |

## Live acceptance gate

Connection smoke tests alone do not satisfy this gate. Record results from the complete application.

- [x] Bootstrap the labeled demo in the dedicated app resources. Gmail contains a draft fixture; Google Slides contains the eight-slide source deck; Dropbox contains the eight actual narrated clips.
- [x] Confirm the source clip bytes and measured durations. The current fixture source is **179,071 ms**, not eight minutes.
- [x] Complete the 120-second brief through the real application. Record its model event, selected IDs, verified output duration, deck readback, Dropbox readback and unsent delivery draft.
- [x] Amend the dedicated Gmail draft to the 90-second fixture. Run again with a new run ID and preserve the original successful artifacts.
- [x] Verify the new result contains `pilot_context`, `result`, `disclaimer`, and `call_to_action`; `pilot_context` appears before `result`. For this fixture, the mandatory closure totals **53,969 ms**.
- [x] Verify the rendered output is no longer than 90,000 ms, has audio/video, fully decodes, and matches the uploaded bytes. The current local five-clip example is **86,203 ms**; use the live result as the submission evidence.
- [x] Verify the copied Google Slides deck contains exactly the selected slide IDs in the selected order. Keep the source deck intact.
- [x] Apply the 30-second fixture and run. Confirm it is blocked because 53,969 ms of mandatory complete recordings cannot fit inside 30,000 ms.
- [x] Confirm the 30-second failure does not replace the previous valid video, copied deck, or last-valid delivery references.
- [x] Run the ambiguity and failure tests applicable to the final code. Report actual passing counts and limits in the README; distinguish unit tests, injected failures, local media tests, and live API checks.
- [x] Confirm errors and unavailable services fail visibly; live mode must not fall back to a mock or saved replay silently.

## Repository and reproduction

- [x] Provide exact commands to install prerequisites, configure the approved scoped credentials, run tests, prepare fixtures, launch the interface and execute the demo sequence.
- [x] Document Python and FFmpeg requirements. Fresh local fixture generation also requires Pillow and macOS `say`; existing verified recordings can be reused. Do not imply fresh speech generation is cross-platform.
- [x] Keep credentials and raw live state outside committed source. Check tracked files and commit contents before publishing; exclude `.credentials/`, `.env`, private `.state/`, tokens and OAuth client secrets.
- [ ] Publish only sanitized evidence. Clearly label any saved report as a replay of a real run, with enough information to understand what was checked.
- [x] Include the fictional catalog, transcripts and dependency declaration. Explain that all sample outcomes are invented and source narration is synthesized.
- [x] Explain the boundary: HardStop selects complete prerecorded segments and checks explicit constraints and declared dependencies. It does not prove general semantic preservation, arbitrary video editing, or live-speaker timing.
- [x] Identify any remaining limitations honestly, including the small bounded source catalog and OAuth test-mode requirements.
- [x] Import the portable source bundle and load the CLI from a clean committed source export without credentials.
- [ ] Verify public README links and ensure the public demo can play without access to private Google Slides or Dropbox source resources.
- [ ] Inspect the first GitHub Actions result after publication; local passing tests do not establish the remote CI result.

## Final recording and form

- [x] Follow [DEMO_SCRIPT.md](DEMO_SCRIPT.md) and show the actual 120-second, 90-second and 30-second sequence.
- [x] Keep the fictional fixture and synthesized narration labels readable. Keep a saved-replay label when using recorded run state.
- [x] Label shortened processing waits rather than implying unrealistically fast execution.
- [x] Measure the exported recording; target **119.9 seconds or less**. Verify the audio track and measured levels, on-screen legibility, and the ending frame.
- [ ] Open the public repository and demo link while signed out; verify both work without the builder's account session.
- [ ] Submit the correct solo-builder email and repository URL through the official form.
- [ ] Verify the form confirmation and record the submission time before the deadline.

The scoring weights and submission requirements above come from the event page checked during implementation. They are a checklist for the actual submission, not a prediction of a winning result.
