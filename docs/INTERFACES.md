# Module interfaces

Python 3.10+, standard library runtime plus installed FFmpeg/ffprobe. Pillow only for generating the fictional demo media, not normal execution.

## Source catalog

`fixtures/catalog.json` is a JSON object with `title`, `description`, `fictional: true`, and `segments` list. A segment has `id` (simple snake_case), `title`, `transcript`, `slide_text` (short display text), `requires` (list of segment IDs), and `value` (integer 1–10). The IDs and declared prerequisite graph are immutable; source order is presentation order. Generation adds `media_path`, `sha256`, `duration_ms`, `slide_id` to a runtime manifest in `.state/source.json`. Cloud manifest also includes `presentation_id`, `dropbox_root`, and `brief_draft_id`.

## Constraints and solver

`hardstop.planner.plan(segments, constraints)` accepts source segments with measured `duration_ms`, and constraints object: `max_duration_ms` positive integer; `required_ids` unique list of known IDs; `excluded_ids` list; `priorities` object id -> positive integer; `evidence` list of objects `{kind, segment_id, quote}`; `ambiguities` list of strings. The solver always enforces declared `requires`, keeps source order, includes mandatory dependency closure, and optimizes optional content value within budget. Return JSON object: `status` (`feasible`, `infeasible`, `needs_review`), `selected_ids`, `duration_ms`, `minimum_required_ms`, `required_closure`, `removed_ids`, `reasons` list, `checks` list. No external calls or mutations.

## Runtime model interpretation

`hardstop.interpret.interpret_brief(brief_text, segments)` returns `{constraints, interpretation, receipt}` with strict schema, exact evidence substrings, and a scoped audit of explicit directives and active timing clauses. Live Responses call uses `configure` for private credentials. Explicit uncertainty blocks execution.

## Media

`hardstop.media.probe(path)` returns dict with `duration_ms`, `has_video`, `has_audio`, `width`, `height`. `render_cut(paths, output_path)` concatenates complete normalized clips in order, verifies decodability and returns probe data plus `sha256`. `make_demo_assets(catalog_path, output_dir)` outputs a manifest of segments with measured paths/hash/duration.

## Provider adapter

`hardstop.providers.Providers` uses `configure` imported from repository root. Methods: `create_draft(subject, body)->dict`, `read_draft(id)->dict` with `draft_id,message_id,subject,body,fingerprint`; `update_draft(id,subject,body)->dict`; `create_source_deck(catalog)->dict` with `presentation_id,slide_ids` mapping; `read_deck(id)->dict` with raw presentation and `slide_ids` in actual order and fingerprint; `copy_and_trim_deck(source_id, selected_slide_ids, title, *, on_copied=None, expected_source_fingerprint=None)->dict`; `upload(path, local_file)->dict`; `download(path, destination)->dict`; `metadata(path)->dict`. Actual API interactions only. Safe errors with HTTP status, no upstream bodies/tokens. Upload create-only and readback. Gmail access is limited in code to the dedicated draft IDs.

## Orchestration / UI

`hardstop/workflow.py` coordinates runs; `hardstop/server.py` serves the local review interface in `web/`. Runs write `.state/runs/<id>/report.json` with stage events, source fingerprints, plan and verified outputs. The interface shows current execution and saved results. It can update the dedicated Gmail draft with a preset or custom brief and start a run. The server binds to loopback and protects changes with CSRF and origin checks. Assets downloaded from apps are never served generically from filesystem.
