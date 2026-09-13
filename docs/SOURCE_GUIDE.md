# Bring a prepared presentation

HardStop works with complete recorded sections. A producer supplies the recordings and their descriptions, then writes an audience and timing brief. Source preparation is part of the workflow: the importer does not split a long video or transcribe it. [Who this is for](USE_CASE.md).

## Prepare the source package

Put a JSON catalog beside the MP4 files, or use relative paths to files below that directory. This two-clip example illustrates the format; replace its text and recordings with your own accurate material. Every displayed field is required, and additional fields are rejected.

```json
{
  "title": "A prepared training example",
  "description": "An illustrative two-section presentation.",
  "fictional": true,
  "narration": "Describe the actual narration in the supplied recordings",
  "segments": [
    {
      "id": "context",
      "title": "The setting for this example",
      "transcript": "The following result applies to this training example.",
      "slide_text": "Training context\nAn illustrative example",
      "requires": [],
      "value": 5,
      "media_path": "context.mp4"
    },
    {
      "id": "result",
      "title": "The example result",
      "transcript": "This example illustrates a three-step handoff.",
      "slide_text": "The example result\nA three-step handoff",
      "requires": ["context"],
      "value": 9,
      "media_path": "result.mp4"
    }
  ]
}
```

The array defines the immutable source order. Each `requires` entry names an earlier clip that must accompany this one; dependencies are transitive. IDs are unique, 2 to 40 characters, start with a lowercase letter, and contain only lowercase letters, digits and underscores. Names that collide with generated Slides object IDs are rejected. `value` is an integer from 1 to 10 used as the default optional-clip priority. The model may supply a different priority from the brief; mandatory content still takes precedence.

Transcripts, fictional-content declarations, narration labels and dependencies are **source-owner declarations**. HardStop validates their format, not whether the spoken content or real-world claims match them. Review them before use. A transcript may contain up to 12,000 characters; a clip title up to 120; `slide_text` up to 320. The application generates one simple native Google slide from the title and `slide_text` for each clip. It does not import an existing deck's design or infer slides from the video.

[Download the complete Harbor package](https://github.com/statsguysam/hardstop/releases/download/v0.2.0/hardstop-harbor-source.zip) to try six fictional recordings with their catalog and briefs. Extract it into a regular directory, then pass its `catalog.json` and `brief.txt` to the `source` command below. Compare the ZIP with [the release checksums](https://github.com/statsguysam/hardstop/releases/download/v0.2.0/SHA256SUMS). The [catalog alone](../fixtures/examples/harbor-catalog.json) is also available as a format example.

Harbor also completed a real import-and-delivery run in a separate workspace: four of its six clips produced a 43.601-second video and matching deck. Its initial grammar-related review outcome and subsequent clarification are both retained in the [integration evidence](EVIDENCE.md#imported-source-harbor). This demonstrates the prepared-source path with another synthetic fixture; it does not validate a customer's metadata or measure onboarding effort.

## File boundaries

| Input | Supported bound |
| --- | --- |
| Catalog | UTF-8 JSON, at most 256 KiB; no duplicate JSON keys |
| Recordings | 1 to 18 complete, self-contained MP4 files |
| Streams | Exactly one video and one audio stream per recording |
| Geometry | Shared dimensions across clips, even width and height, from 16 pixels up to 3840 × 2160 |
| Duration | At most 10 minutes per clip and 60 minutes in total |
| Size | At most 512 MiB per clip and 2 GiB in total |
| Paths | Relative MP4 paths within the catalog directory; no URLs, traversal or symbolic links |

The importer copies each file into a new local source directory, computes its SHA-256, measures its duration and fully decodes it. It installs the verified directory only after the package passes. It does not synthesize, rewrite or speed up the source recordings. The usual runtime media pipeline later renders the selected complete clips and checks the finished file's duration again.

## Register a new workspace

Configure Google, Dropbox and OpenAI access as described in the [README](../README.md#configure-your-own-api-access). Source import and normal execution need Python and FFmpeg on macOS or Linux; they do not need Pillow or macOS speech synthesis.

Create `brief.txt`, using the clip IDs as words or their exact titles:

```text
Fit within 90 seconds. Keep result. The audience is new team members learning the handoff.
```

The declared dependency makes `context` mandatory when `result` is required. This brief is feasible only if the actual recordings fit; the example does not promise their duration.

Run these commands from the repository root. The global `--state-dir` option goes before the command name:

```bash
python3 -m hardstop.cli --state-dir .state/my-presentation source /path/to/catalog.json \
  --brief /path/to/brief.txt --subject "Producer brief"
python3 -m hardstop.cli --state-dir .state/my-presentation run --id first-cut
python3 -m hardstop.cli --state-dir .state/my-presentation serve --port 8767
```

Registration uploads the verified clips and catalog into your dedicated Dropbox app folder, generates the matching source presentation in Google Slides, and creates an unaddressed Gmail brief draft. Running a cut adds its own output video, copied and trimmed deck, and unsent handoff draft. No email is sent.

Use the same `--state-dir` on later commands. A source package belongs to one workspace; registration refuses to replace an existing source. Partial setup is journaled, and changed inputs or unresolved writes need reconciliation before resuming. Use a new workspace for a different presentation.

The local review interface on port 8767 shows the source's actual clip names. Use **Write your own brief** to change the timing or audience in the dedicated Gmail draft. Relay's demonstration presets are hidden for imported sources.

## Write a supported brief

State one explicit upper time limit, separate hard clip requirements from audience preferences, and name any exclusions. Supported examples include `Fit within 90 seconds.`, `At most 1.5 minutes.`, `Keep result.`, `The disclaimer is mandatory.` and `Do not remove context.` An audience description can guide the model's optional-clip priorities without making every mentioned clip mandatory.

Missing or conflicting timing, unfamiliar requirement grammar, unknown content and requests to rewrite narration can require review. The system does not silently guess what an unnamed “important part” means. Selection explanations are model-generated summaries, while exact evidence quotations support explicit constraints. Neither validates every possible human intention.
