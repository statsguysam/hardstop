#!/usr/bin/env python3
"""Assemble a narrated demo from actual captured UI and verified output media.

No app UI is fabricated. Missing captures stop rendering. --prepare generates
only narration, editorial frames and a shot list; --render needs every capture.
Preparation needs kokoro-onnx, soundfile, Pillow and separately downloaded local
Kokoro model/voice files. This script makes no speech API calls or downloads.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hardstop.media import probe, sha256_file, verify_decode

W, H = 1920, 1080
NAVY, TEXT, MUTED = "#10131B", "#F6F6F3", "#B0B4BE"
FONT = "/System/Library/Fonts/Avenir Next.ttc"
FOOTER = "Recorded runs; waits shortened. Synthetic voice; fictional samples."

SHOTS = [
    {"id": "01_hook", "seconds": 7, "image": "buyer-ready.png",
     "title": "One presentation. Two audiences.", "focus": "1082:700:0:190",
     "speech": "You've got one presentation, two audiences, and ninety seconds. Which parts do you keep?"},
    {"id": "02_brief", "seconds": 12, "image": "operator-brief.png",
     "title": "Same time limit. A different audience.", "focus": "1082:700:0:190",
     "speech": "A buyer needs to understand the problem. An operator needs the walkthrough. I change the audience in the Gmail brief, keeping the result and disclaimer required."},
    {"id": "03_decisions", "seconds": 14, "image": "operator-decisions.png",
     "title": "The audience changes what stays.", "focus": "432:392:635:94",
     "speech": "HardStop reads the brief and uses the model to rank what's relevant. The buyer gets the problem. The operator gets the workflow. The result keeps its required context."},
    {"id": "04_buyer", "seconds": 7, "image": "buyer-ready.png",
     "title": "The buyer's version.", "focus": "1082:700:0:190",
     "speech": "Here's the buyer's version. Under ninety seconds, with a deck that follows the same selection."},
    {"id": "05_operator", "seconds": 6, "image": "operator-ready.png",
     "title": "The operator's version.", "focus": "1082:700:0:190",
     "speech": "For the operator, we get a different cut, still inside the same limit."},
    {"id": "06_source", "seconds": 5, "video": True,
     "title": "The finished video, playing silently.",
     "speech": "This is the finished video, playing silently."},
    {"id": "07_deck", "seconds": 11, "image": "operator-deck.png", "focus": "984:570:0:114",
     "title": "The slides follow the chosen recordings.",
     "speech": "The clips live in Dropbox. HardStop copies the Google Slides deck, then checks that every recording has the right slide, in the right order."},
    {"id": "08_handoff", "seconds": 10, "image": "operator-handoff.png", "focus": "980:274:150:40",
     "title": "The delivery is ready for review.",
     "speech": "It downloads the saved video to check it again. Then it prepares this Gmail handoff, ready for review. Nothing is sent."},
    {"id": "09_impossible", "seconds": 14, "image": "impossible-v2.png",
     "title": "Can you make it thirty seconds?", "focus": "1026:455:28:181",
     "speech": "But what if someone asks for thirty seconds? The required recordings alone already run past that. HardStop stops, shows what's blocking the request, and keeps the last working version."},
    {"id": "10_harbor", "seconds": 16, "image": "harbor-ready.png",
     "title": "A different source. The same checks.", "focus": "1188:525:46:181",
     "speech": "To try a different source, I imported Harbor: six new recordings with their own section names and dependency. After clarifying the brief, the same workflow delivered a cut under sixty seconds. Another fictional example."},
    {"id": "11_close", "seconds": 8, "image": "operator-ready.png",
     "title": "A version for each audience.", "focus": "595:695:24:195",
     "speech": "HardStop gives each audience the version they need, with the video and slides ready to review together."},
]


def run(arguments, timeout=600):
    result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{Path(arguments[0]).name} failed: {result.stderr.decode(errors='replace')[-1000:]}")
    return result.stdout


def font(size, bold=False):
    return ImageFont.truetype(FONT, size, index=0 if bold else 7)


def draw_text(draw, value, position, size, fill=TEXT, bold=False, width=575, leading=1.16):
    x, y = position
    for paragraph in value.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if line and draw.textlength(candidate, font=font(size, bold)) > width:
                draw.text((x, y), line, fill=fill, font=font(size, bold), anchor="lt")
                y += round(size * leading)
                line = word
            else:
                line = candidate
        draw.text((x, y), line, fill=fill, font=font(size, bold), anchor="lt")
        y += round(size * leading)
    return y


def background(shot, path):
    canvas = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(canvas)
    draw_text(draw, shot["title"], (66, 48), 44, TEXT, True, width=1580)
    draw.text((1670, 54), "HardStop", fill=MUTED,
              font=ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 29), anchor="lt")
    draw_text(draw, FOOTER, (66, 1034), 20, MUTED, width=1790)
    canvas.save(path)


def caption_timestamp(seconds):
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"


def caption_groups(speech):
    # Keep sentence boundaries and readable phrase lengths. Timing is anchored
    # to each measured narration file; phrase intervals use word-length weights.
    def split_phrase(phrase):
        if len(phrase) <= 76:
            return [phrase]
        # Prefer a grammatical break, balanced enough to avoid a flashing
        # one-word remainder. Fall back to a balanced word boundary.
        candidates = [m.end() for m in re.finditer(r"[,;:] +", phrase)]
        candidates = [p for p in candidates if 20 <= p <= len(phrase) - 20]
        if not candidates:
            candidates = [m.end() for m in re.finditer(r" +(?=and |then )", phrase)
                          if 20 <= m.end() <= len(phrase) - 20]
        if not candidates:
            candidates = [m.end() for m in re.finditer(r" +", phrase)
                          if 20 <= m.end() <= len(phrase) - 20]
        boundary = min(candidates, key=lambda p: abs(p - len(phrase) / 2))
        return split_phrase(phrase[:boundary].strip()) + split_phrase(phrase[boundary:].strip())

    return [phrase for sentence in re.split(r"(?<=[.!?;]) +", speech)
            for phrase in split_phrase(sentence)]


def write_captions(storyboard, destination):
    cues = ["WEBVTT", ""]
    for shot in storyboard:
        if not shot["speech"]:
            cues += [f"{caption_timestamp(shot['start_seconds'])} --> {caption_timestamp(shot['start_seconds'] + shot['seconds'])}",
                     "[Excerpt from the original recording]", ""]
            continue
        phrases = caption_groups(shot["speech"])
        weights = [len(phrase) for phrase in phrases]
        total = sum(weights)
        start = shot["start_seconds"] + 0.1
        duration = shot["speech_duration_ms"] / 1000
        aligned = shot.get("caption_intervals", [])
        for index, (phrase, weight) in enumerate(zip(phrases, weights)):
            if aligned:
                interval = aligned[index]
                if interval["text"] != phrase:
                    raise RuntimeError("Caption alignment does not match the prepared text")
                start = shot["start_seconds"] + 0.1 + interval["start"]
                end = shot["start_seconds"] + 0.1 + interval["end"]
            else:
                end = start + duration * weight / total
            words, lines, line = phrase.split(), [], ""
            for word in words:
                if line and len(line + " " + word) > 42:
                    lines.append(line)
                    line = word
                else:
                    line = (line + " " + word).strip()
            lines.append(line)
            if len(lines) > 2:
                raise RuntimeError("Caption phrase exceeds two lines")
            cues += [f"{caption_timestamp(start)} --> {caption_timestamp(end)}", "\n".join(lines), ""]
            start = end
    destination.write_text("\n".join(cues))

def prepare(output, caption_destination, voice_model, voice_pack, voice, speed):
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from kokoro_onnx import Kokoro
    import soundfile

    output.mkdir(parents=True, exist_ok=True)
    for asset in (voice_model, voice_pack):
        if not asset.is_file():
            raise RuntimeError("Local Kokoro asset is missing: " + str(asset))
    voice_config = {"engine": "kokoro-onnx", "voice": voice, "speed": speed,
                    "model_sha256": sha256_file(voice_model),
                    "voice_pack_sha256": sha256_file(voice_pack),
                    "voice_type": "stock synthetic voice; no impersonation"}
    previous_config = output / "voice.json"
    voice_changed = not previous_config.exists() or json.loads(previous_config.read_text()) != voice_config
    engine = None
    alignment_path = output / "caption-alignment.json"
    alignments = json.loads(alignment_path.read_text()) if alignment_path.exists() else {}
    position = 0
    storyboard = []
    for shot in SHOTS:
        background(shot, output / (shot["id"] + ".png"))
        audio = output / (shot["id"] + ".wav")
        transcript = output / (shot["id"] + ".txt")
        changed = not transcript.exists() or transcript.read_text() != shot["speech"]
        transcript.write_text(shot["speech"])
        if shot["speech"] and (not audio.exists() or changed or voice_changed):
            if engine is None:
                engine = Kokoro(str(voice_model), str(voice_pack))
            spoken_text = shot["speech"].replace("HardStop", "Hard Stop")
            samples, sample_rate = engine.create(spoken_text, voice=voice, speed=speed, lang="en-us")
            soundfile.write(str(audio), samples, sample_rate, subtype="PCM_16")
        spoken_ms = probe(audio)["duration_ms"] if shot["speech"] else 0
        if spoken_ms + 250 > shot["seconds"] * 1000:
            raise RuntimeError(f"Narration too long for {shot['id']}: {spoken_ms} ms for {shot['seconds']}s")
        entry = {**shot, "start_seconds": position, "speech_duration_ms": spoken_ms}
        aligned = alignments.get(shot["id"], {})
        if (aligned.get("speech") == shot["speech"] and
                aligned.get("audio_sha256") == sha256_file(audio)):
            entry["caption_intervals"] = aligned["phrases"]
        storyboard.append(entry)
        position += shot["seconds"]
    if not 100 <= position <= 114:
        raise RuntimeError(f"Demo duration {position}s is outside its requested range")
    (output / "storyboard.json").write_text(json.dumps({"duration_seconds": position, "shots": storyboard}, indent=2) + "\n")
    previous_config.write_text(json.dumps(voice_config, indent=2) + "\n")
    write_captions(storyboard, caption_destination)
    print(json.dumps({"prepared": True, "seconds": position, "narration_words": sum(len(s['speech'].split()) for s in SHOTS)}))


def verify_captions(storyboard, duration_seconds, caption_path):
    value = caption_path.read_text()
    cues = [block.splitlines() for block in value.split("\n\n") if " --> " in block]
    previous = 0
    for cue in cues:
        bounds = []
        for timestamp in cue[0].split(" --> "):
            h, m, s = timestamp.split(":")
            bounds.append(int(h) * 3600 + int(m) * 60 + float(s))
        start, end = bounds
        if start < previous - .001 or end <= start or end > duration_seconds:
            raise RuntimeError("Caption times overlap or exceed the final recording")
        if len(cue[1:]) > 2 or any(len(line) > 42 for line in cue[1:]):
            raise RuntimeError("Caption text exceeds the readable line limits")
        previous = end
    expected = " ".join(s["speech"] for s in storyboard if s["speech"])
    actual = " ".join(line for cue in cues for line in cue[1:] if not line.startswith("[Excerpt"))
    if expected.split() != actual.split():
        raise RuntimeError("Caption text does not exactly match the final narration")
    return {"cues": len(cues), "exact_narration_text": True, "maximum_lines": 2,
            "speech_file_timing_verified": True,
            "phrase_timing": ("matched to local speech-recognition word times"
                              if all(s.get("caption_intervals") for s in storyboard)
                              else "estimated within each measured narration clip"),
            "sha256": sha256_file(caption_path)}


def verify_run_evidence(buyer_report, harbor_report, impossible_report, harbor_review_report):
    evidence, inputs = {}, {}
    expectations = [
        ("buyer", buyer_report, "ready", 90000,
         ["problem", "pilot_context", "result", "disclaimer", "call_to_action"]),
        ("harbor", harbor_report, "ready", 60000,
         ["setting", "finding", "limitations", "next_step"]),
        ("impossible", impossible_report, "infeasible", None, []),
        ("harbor_clarification", harbor_review_report, "needs_review", None, []),
    ]
    for label, path, status, maximum_duration, selected in expectations:
        receipt = json.loads(path.read_text())
        inputs[path] = sha256_file(path)
        if receipt.get("status") != status or receipt.get("plan", {}).get("selected_ids") != selected:
            raise RuntimeError(f"The {label} run does not support the final narration")
        if status == "ready":
            media = path.parent / "cut.mp4"
            duration = receipt.get("media", {}).get("duration_ms")
            if (not isinstance(duration, int) or not 0 < duration <= maximum_duration or
                    probe(media)["duration_ms"] != duration or
                    sha256_file(media) != receipt["media"].get("sha256") or
                    not all(receipt.get("outputs", {}).get(key)
                            for key in ("presentation_id", "dropbox_path", "draft_id"))):
                raise RuntimeError(f"The {label} recording or three-app delivery is unverified")
            inputs[media] = sha256_file(media)
        elif receipt.get("outputs"):
            raise RuntimeError(f"The {label} blocked run unexpectedly contains outputs")
        elif status == "infeasible" and receipt.get("plan", {}).get("minimum_required_ms", 0) <= 30000:
            raise RuntimeError("The impossible run does not match the recorded thirty-second conflict")
        else:
            duration = None
        evidence[label] = {"run_id": receipt["id"], "status": status,
                           "model": receipt.get("model", {}).get("model"),
                           "duration_ms": duration, "selected_ids": selected,
                           "receipt_sha256": inputs[path]}
    return evidence, inputs


def render(capture, output, source_video, destination, buyer_report, harbor_report, impossible_report, harbor_review_report, readbacks_path):
    missing = [shot["image"] for shot in SHOTS if "image" in shot and not (capture / shot["image"]).is_file()]
    if missing:
        raise RuntimeError("Actual captures still needed: " + ", ".join(sorted(set(missing))))
    if not source_video.is_file():
        raise RuntimeError("Actual verified source output is missing")
    evidence, evidence_inputs = verify_run_evidence(buyer_report, harbor_report, impossible_report, harbor_review_report)
    source_info = probe(source_video)
    if not 0 < source_info["duration_ms"] <= 90000:
        raise RuntimeError("Update the demo script to match the measured final ninety-second cut")
    source_before = sha256_file(source_video)
    source_receipt = source_video.parent / "report.json"
    if not source_receipt.is_file():
        raise RuntimeError("A real ready-run report is required beside the source video")
    receipt = json.loads(source_receipt.read_text())
    evidence_inputs[source_receipt] = sha256_file(source_receipt)
    if (receipt.get("status") != "ready" or receipt.get("media", {}).get("sha256") != source_before or
            receipt.get("media", {}).get("duration_ms") != source_info["duration_ms"]):
        raise RuntimeError("The source recording does not match its verified live run")
    if receipt.get("plan", {}).get("selected_ids") != ["workflow", "pilot_context", "result", "disclaimer", "call_to_action"]:
        raise RuntimeError("The operator recording does not contain the narrated selection")
    readbacks = json.loads(readbacks_path.read_text())
    observed = {item["label"]: item for item in readbacks.get("results", [])}
    for label, run_id in [("buyer", evidence["buyer"]["run_id"]),
                          ("harbor", evidence["harbor"]["run_id"]),
                          ("operator_after_impossible", receipt["id"])]:
        result = observed.get(label, {})
        checks = result.get("checks", {})
        if (result.get("run_id") != run_id or result.get("status") != "passed" or
                not checks or not all(value is True for value in checks.values())):
            raise RuntimeError("Independent delivery readback does not support " + label)
    if not observed["operator_after_impossible"]["checks"].get("ready_pointer_unchanged"):
        raise RuntimeError("The previous valid output was not confirmed after the impossible request")
    evidence_inputs[readbacks_path] = sha256_file(readbacks_path)
    info = json.loads((output / "storyboard.json").read_text())
    if [{key: shot[key] for key in ("id", "seconds", "speech")} for shot in info["shots"]] != [
            {key: shot[key] for key in ("id", "seconds", "speech")} for shot in SHOTS]:
        raise RuntimeError("Prepare the final narration before rendering this shot list")
    narration_hashes = {shot["id"] + ".wav": sha256_file(output / (shot["id"] + ".wav"))
                        for shot in SHOTS if shot["speech"]}
    captured_files = {}
    for shot in SHOTS:
        inputs = [(capture / shot["image"])] if "image" in shot else []
        if "sequence" in shot:
            inputs.extend(sorted((capture / shot["sequence"]).glob("*.png")))
        for file in inputs:
            with Image.open(file) as actual_image:
                width, height = actual_image.size
            if shot.get("focus"):
                crop_width, crop_height, x, y = map(int, shot["focus"].split(":"))
                if min(crop_width, crop_height) <= 0 or min(x, y) < 0 or x + crop_width > width or y + crop_height > height:
                    raise RuntimeError("Inspect and adjust the focus crop for this fresh capture: " + file.name)
            captured_files[str(file.relative_to(capture))] = sha256_file(file)
    rendered = []
    for shot in SHOTS:
        movie = output / (shot["id"] + ".mp4")
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-loop", "1", "-framerate", "30", "-i", str(output / (shot["id"] + ".png"))]
        if "sequence" in shot:
            frames = sorted((capture / shot["sequence"]).glob("*.png"))
            if len(frames) < 2:
                raise RuntimeError("Actual processing capture frames are missing")
            # Each captured frame is retained, with waiting condensed to this shot.
            rate = len(frames) / shot["seconds"]
            decoder = "mjpeg" if frames[0].read_bytes().startswith(b"\xff\xd8") else "png"
            args += ["-framerate", f"{rate:.8f}", "-start_number", "0", "-c:v", decoder,
                     "-i", str(capture / shot["sequence"] / "%04d.png")]
        elif shot.get("video"):
            args += ["-i", str(source_video)]
        else:
            args += ["-loop", "1", "-framerate", "30", "-i", str(capture / shot["image"])]
        if shot["speech"]:
            args += ["-i", str(output / (shot["id"] + ".wav"))]
            audio = "[2:a]loudnorm=I=-18:TP=-2:LRA=11,adelay=100:all=1,apad,alimiter=limit=0.94[a]"
        else:
            audio = "[1:a]apad,alimiter=limit=0.94[a]"
        crop = "crop=" + shot["focus"] + "," if shot.get("focus") else ""
        filters = ("[1:v]" + crop + "scale=1760:855:force_original_aspect_ratio=decrease,setsar=1[screen];"
                   "[0:v][screen]overlay=x=(1920-overlay_w)/2:y=143+(855-overlay_h)/2:shortest=0[v];" + audio)
        args += ["-filter_complex", filters, "-map", "[v]", "-map", "[a]", "-t", str(shot["seconds"]),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "2", "-r", "30",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                 "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact",
                 "-metadata", "encoder=", "-metadata:s:v:0", "encoder=", "-metadata:s:a:0", "encoder=",
                 "-movflags", "+faststart", str(movie)]
        run(args)
        rendered.append(movie)
        print("Rendered " + shot["id"], flush=True)
    playlist = output / "concat.txt"
    playlist.write_text("".join("file '" + p.name.replace("'", "'\\''") + "'\n" for p in rendered))
    run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(playlist),
         "-c", "copy", "-bsf:v", "filter_units=remove_types=6", "-map_metadata", "-1", "-map_chapters", "-1",
         "-fflags", "+bitexact", "-metadata", "encoder=", "-metadata:s:v:0", "encoder=",
         "-metadata:s:a:0", "encoder=", "-metadata", "comment=", "-metadata", "artist=",
         "-metadata", "title=", "-metadata", "creation_time=", "-movflags", "+faststart", str(destination)])
    measured = probe(destination)
    if measured["duration_ms"] > 114000 or not measured["has_audio"] or not measured["has_video"]:
        raise RuntimeError("Final demo failed duration or media verification")
    verify_decode(destination)
    metadata = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(destination)]))
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    tags = [metadata.get("format", {}).get("tags", {})] + [s.get("tags", {}) for s in metadata.get("streams", [])]
    unwanted = {"encoder", "comment", "artist", "author", "creator", "title", "creation_time"}
    if any(key.lower() in unwanted and value for group in tags for key, value in group.items()):
        raise RuntimeError("Optional identifying metadata remains in the submission video")
    volume = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(destination),
                             "-af", "volumedetect", "-vn", "-f", "null", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stderr.decode()
    mean = float(re.search(r"mean_volume: (-?[\d.]+) dB", volume)[1])
    peak = float(re.search(r"max_volume: (-?[\d.]+) dB", volume)[1])
    if not -35 <= mean <= -10 or peak >= -.1:
        raise RuntimeError("The narration is silent, too quiet, or clips")
    if (sha256_file(source_video) != source_before or
            any(sha256_file(capture / name) != value for name, value in captured_files.items()) or
            any(sha256_file(output / name) != value for name, value in narration_hashes.items()) or
            any(sha256_file(path) != value for path, value in evidence_inputs.items())):
        raise RuntimeError("An input recording or capture changed during rendering")
    captions = verify_captions(info["shots"], measured["duration_ms"] / 1000, destination.with_suffix(".vtt"))
    report = {**measured, "sha256": sha256_file(destination), "full_decode_verified": True,
              "source_video_sha256": source_before, "source_inputs_unchanged": True,
              "source_run_id": receipt["id"], "source_model": receipt.get("model", {}).get("model"),
              "additional_run_evidence": evidence,
              "independent_delivery_readbacks": readbacks,
              "capture_hashes": captured_files, "recording_disclosure": FOOTER,
              "narration": json.loads((output / "voice.json").read_text()),
              "narration_hashes": narration_hashes,
              "source_excerpt_audio": "muted under synthetic narration",
              "optional_identifying_metadata_removed": True, "mean_volume_db": mean,
              "peak_volume_db": peak, "captions": captions}
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    script = ["# HardStop demonstration script", "",
              "110-second edited montage of actual captured app states, with five seconds of silent playback from the verified operator output. This is not an uninterrupted screen recording.", "",
              "Narration uses the stock Kokoro af_heart synthetic voice. All source material is fictional. The persistent footer reads: " + FOOTER, "",
              "## Recorded sequence", ""]
    for shot in info["shots"]:
        start = int(shot["start_seconds"])
        end = int(start + shot["seconds"])
        script += [f"### {start // 60:02d}:{start % 60:02d} to {end // 60:02d}:{end % 60:02d}: {shot['title']}", "",
                   "Visual: " + (shot.get("image") or "Silent playback of the actual operator cut") + ".", "",
                   "> " + shot["speech"], ""]
    (output / "DEMO_SCRIPT.md").write_text("\n".join(script))
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--capture-dir", type=Path, default=ROOT / ".state/demo-capture-v3")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "output/demo-build-v3")
    parser.add_argument("--voice-model", type=Path, default=ROOT / "output/demo-build-v3/kokoro-v1.0.onnx")
    parser.add_argument("--voice-pack", type=Path, default=ROOT / "output/demo-build-v3/voices-v1.0.bin")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--voice-speed", type=float, default=.95)
    parser.add_argument("--source-video", type=Path)
    parser.add_argument("--buyer-report", type=Path)
    parser.add_argument("--harbor-report", type=Path)
    parser.add_argument("--impossible-report", type=Path)
    parser.add_argument("--harbor-review-report", type=Path)
    parser.add_argument("--readbacks", type=Path, default=ROOT / "docs/evidence/delivery-readbacks-v3.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output/hardstop-demo-v3.mp4")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.work_dir, args.output.with_suffix(".vtt"), args.voice_model, args.voice_pack,
                args.voice, args.voice_speed)
    if args.render:
        if not all((args.source_video, args.buyer_report, args.harbor_report, args.impossible_report, args.harbor_review_report)):
            parser.error("--render requires --source-video, --buyer-report, --harbor-report, --impossible-report and --harbor-review-report")
        render(args.capture_dir, args.work_dir, args.source_video, args.output,
               args.buyer_report, args.harbor_report, args.impossible_report, args.harbor_review_report, args.readbacks)
    if not args.prepare and not args.render:
        parser.error("Choose --prepare or --render")


if __name__ == "__main__":
    main()
