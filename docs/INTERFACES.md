# Module interfaces

Python 3.10+, standard library runtime plus installed FFmpeg/ffprobe. Pillow only for generating the fictional demo media, not normal execution.

## Source catalog

The Relay fixture is `fixtures/catalog.json`. A general imported catalog has exactly `title`, `description`, `fictional` (boolean), `narration` and `segments`. Each imported segment has exactly `id`, `title`, `transcript`, `slide_text`, `requires`, `value` and a relative `media_path`. IDs match `[a-z][a-z0-9_]{1,39}`: 2–40 characters, unique, with no generated slide/shape ID collisions. `value` is an integer from 1 to 10. Dependencies name earlier source IDs; source order and declared dependencies are immutable within a workspace. [Complete source guide](SOURCE_GUIDE.md).

`hardstop.source.import_source(catalog_path, output_dir)` verifies and copies 1–18 local MP4s into a new directory and returns a measured manifest. Each clip gains `sha256`, `duration_ms`, `slide_id`, dimensions and decode metadata. `source_kind` is `user_recordings`; `metadata_provenance` is `user_declared`. This function performs no API calls and no synthesis. The importer verifies media, not the truth of transcripts or content declarations.

`Workflow.import_recordings(catalog_path, subject, body)` adds registration in the three connected apps. It generates the source Slides deck from title and `slide_text`, uploads source clips and catalog, and creates a dedicated unaddressed Gmail brief draft. Local `<state-dir>/source.json` records cloud identities including `presentation_id`, `brief_draft_id`, catalog path/hash/revision and per-clip Dropbox paths/revisions. Local media paths are omitted from the cloud catalog. An existing registered source is never replaced.

## Constraints and solver

`hardstop.planner.plan(segments, constraints)` accepts source segments with measured `duration_ms`, and constraints object: `max_duration_ms` positive integer; `required_ids` unique list of known IDs; `excluded_ids` list; `priorities` object id -> positive integer; `evidence` list of objects `{kind, segment_id, quote}`; `ambiguities` list of strings. The solver always enforces declared `requires`, keeps source order, includes mandatory dependency closure, and optimizes optional content value within budget. Return JSON object: `status` (`feasible`, `infeasible`, `needs_review`), `selected_ids`, `duration_ms`, `minimum_required_ms`, `required_closure`, `removed_ids`, `reasons` list, `checks` list. No external calls or mutations.

## Runtime model interpretation

`hardstop.interpret.interpret_brief(brief_text, segments)` returns `{constraints, interpretation, receipt}` with strict schema, exact evidence substrings, and a scoped audit of explicit directives and active timing clauses. `interpretation.priorities` contains `{segment_id, value, reason}` rows: the value guides optional selection and the reason is a concise model-generated explanation, not a verbatim constraint quotation. `receipt` holds the local response identity, model, numeric usage and elapsed time. Live Responses calls use `configure` for private credentials. Explicit uncertainty blocks execution. An unresolved duration may use a schema placeholder internally; it must not be presented as a confirmed time limit or used to publish a cut.

`scripts/evaluate_briefs.py` declares its six cases and expected selections before any calls. With `--live`, it performs one genuine interpretation per case, passes constraints to the normal planner, and records all results and reported API usage. Its baseline removes model priorities while retaining extracted hard constraints. The script has no video-rendering or cloud-delivery stage.

## Media

`hardstop.media.probe(path)` returns dict with `duration_ms`, `has_video`, `has_audio`, `width`, `height`. `render_cut(paths, output_path)` concatenates complete normalized clips in order, verifies decodability and returns probe data plus `sha256`. `make_demo_assets(catalog_path, output_dir)` outputs a manifest of segments with measured paths/hash/duration.

## Provider adapter

`hardstop.providers.Providers` uses `configure` imported from repository root. Methods: `create_draft(subject, body)->dict`, `read_draft(id)->dict` with `draft_id,message_id,subject,body,fingerprint`; `update_draft(id,subject,body)->dict`; `create_source_deck(catalog)->dict` with `presentation_id,slide_ids` mapping; `read_deck(id)->dict` with raw presentation and `slide_ids` in actual order and fingerprint; `copy_and_trim_deck(source_id, selected_slide_ids, title, *, on_copied=None, expected_source_fingerprint=None)->dict`; `upload(path, local_file)->dict`; `download(path, destination)->dict`; `metadata(path)->dict`. Actual API interactions only. Safe errors with HTTP status, no upstream bodies/tokens. Upload create-only and readback. Gmail access is limited in code to the dedicated draft IDs.

## Orchestration / UI

`hardstop/workflow.py` coordinates runs; `hardstop/server.py` serves the local review interface in `web/`. Runs write `<state-dir>/runs/<id>/report.json` with stage events, source fingerprints, validated interpretation, plan and output verification. The interface shows current execution and saved results, can update the dedicated Gmail draft and can start a run. `fixtures` is empty for imported workspaces; Relay presets appear only for the fictional seed. Optional-clip explanations use validated priority rows and known source IDs. Previous-version comparisons require completed runs, a matching catalog hash and a current brief; stopped attempts never appear as delivered choices. The server binds to loopback and protects changes with CSRF and origin checks. Assets downloaded from apps are never served generically from filesystem.
