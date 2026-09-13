#!/usr/bin/env python3
"""Assemble a narrated demo from actual captured UI and verified output media.

No app UI is fabricated. Missing captures stop rendering. --prepare generates
only narration, editorial frames and a shot list; --render needs every capture.
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
FOOTER = "Recorded API runs. Waiting time shortened. Fictional example. Synthesized narration."

SHOTS = [
    {"id": "01_hook", "seconds": 7, "image": "final120-ready.png",
     "title": "Your slot just got shorter.", "focus": "1082:700:0:190",
     "speech": "Your two-minute presentation is ready. Then the producer says, we only have ninety seconds."},
    {"id": "02_apps", "seconds": 9, "sequence": "original-processing",
     "title": "One change affects three apps.", "focus": "1082:700:0:190",
     "speech": "That change touches three places: the brief in Gmail, the recordings in Dropbox, and the deck in Google Slides."},
    {"id": "03_original", "seconds": 8, "image": "final120-ready.png",
     "title": "The first version fits: 116.770 seconds.", "focus": "1082:700:0:190",
     "speech": "Here's the original cut: one minute, fifty-six seconds. It fits the first brief. Now let's change the deadline."},
    {"id": "04_amendment", "seconds": 10, "image": "90-amendment.png",
     "title": "“Make it ninety seconds.”", "focus": "1082:700:0:190",
     "speech": "HardStop's model reads the new brief and turns it into requirements. Each one links back to what the producer actually wrote."},
    {"id": "05_checks", "seconds": 12, "image": "90-checks.png",
     "title": "The result stays with its explanation.", "focus": "1082:745:0:155",
     "speech": "The result must stay, with its explanation and disclaimer. HardStop keeps those complete clips together, removes the rollout, and checks the timing."},
    {"id": "06_ready", "seconds": 8, "image": "90-ready.png",
     "title": "The new cut: 86.203 seconds.", "focus": "1082:700:0:190",
     "speech": "Here's the new version: eighty-six point two seconds. That's the finished file's measured length. Let's hear a few seconds."},
    {"id": "07_source", "seconds": 4, "video": True,
     "title": "Four seconds from the finished video.", "speech": ""},
    {"id": "08_deck", "seconds": 9, "image": "90-deck.png", "focus": "1180:530:0:108",
     "title": "The slide deck changes with it.",
     "speech": "It also copies the slide deck and keeps exactly the slides that match the video. The original deck stays intact."},
    {"id": "09_handoff", "seconds": 8, "image": "final-gmail-handoff.png", "focus": "980:274:150:40",
     "title": "The delivery is ready for review.",
     "speech": "The video goes back to Dropbox, then gets downloaded and checked. HardStop prepares this email draft for review."},
    {"id": "10_impossible", "seconds": 13, "image": "30-blocked.png",
     "title": "“Actually, you have thirty seconds.”", "focus": "1082:700:0:190",
     "speech": "Now ask for thirty seconds. The required recordings alone need almost fifty-four. HardStop explains why they cannot fit, and leaves the working version untouched."},
    {"id": "11_challenge", "seconds": 13, "image": "custom-challenge.png",
     "title": "Write a brief in your own words.", "focus": "432:430:637:180",
     "speech": "You can write your own brief, too. The same checks apply. This example uses fictional content and synthesized narration; the app calls and recorded results are real."},
    {"id": "12_close", "seconds": 9, "image": "30-blocked.png",
     "title": "Keep the last version that works.", "focus": "595:695:24:195",
     "speech": "That's HardStop: change the brief, keep the video and deck in step, and know when the request simply cannot be met."},
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
        for phrase, weight in zip(phrases, weights):
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

def prepare(output):
    output.mkdir(parents=True, exist_ok=True)
    position = 0
    storyboard = []
    for shot in SHOTS:
        background(shot, output / (shot["id"] + ".png"))
        audio = output / (shot["id"] + ".aiff")
        transcript = output / (shot["id"] + ".txt")
        changed = not transcript.exists() or transcript.read_text() != shot["speech"]
        transcript.write_text(shot["speech"])
        if shot["speech"] and (not audio.exists() or changed):
            run(["say", "-v", "Samantha", "-r", "166", "-f", str(transcript), "-o", str(audio)])
        spoken_ms = probe(audio)["duration_ms"] if shot["speech"] else 0
        if spoken_ms + 250 > shot["seconds"] * 1000:
            raise RuntimeError(f"Narration too long for {shot['id']}: {spoken_ms} ms for {shot['seconds']}s")
        storyboard.append({**shot, "start_seconds": position, "speech_duration_ms": spoken_ms})
        position += shot["seconds"]
    if not 110 <= position <= 119:
        raise RuntimeError(f"Demo duration {position}s is outside its requested range")
    (output / "storyboard.json").write_text(json.dumps({"duration_seconds": position, "shots": storyboard}, indent=2) + "\n")
    write_captions(storyboard, ROOT / "output/hardstop-demo.vtt")
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
            "phrase_timing": "estimated within each measured narration clip",
            "sha256": sha256_file(caption_path)}


def render(capture, output, source_video, destination):
    missing = [shot["image"] for shot in SHOTS if "image" in shot and not (capture / shot["image"]).is_file()]
    if missing:
        raise RuntimeError("Actual captures still needed: " + ", ".join(sorted(set(missing))))
    if not source_video.is_file():
        raise RuntimeError("Actual verified source output is missing")
    source_info = probe(source_video)
    if source_info["duration_ms"] != 86203:
        raise RuntimeError("Update the demo script to match the measured final ninety-second cut")
    source_before = sha256_file(source_video)
    source_receipt = source_video.parent / "report.json"
    if not source_receipt.is_file():
        raise RuntimeError("A real ready-run report is required beside the source video")
    receipt = json.loads(source_receipt.read_text())
    if receipt.get("status") != "ready" or receipt.get("media", {}).get("sha256") != source_before:
        raise RuntimeError("The source recording does not match its verified live run")
    info = json.loads((output / "storyboard.json").read_text())
    if [{key: shot[key] for key in ("id", "seconds", "speech")} for shot in info["shots"]] != [
            {key: shot[key] for key in ("id", "seconds", "speech")} for shot in SHOTS]:
        raise RuntimeError("Prepare the final narration before rendering this shot list")
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
            args += ["-i", str(output / (shot["id"] + ".aiff"))]
            audio = "[2:a]adelay=100:all=1,apad,alimiter=limit=0.94[a]"
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
    if measured["duration_ms"] > 119000 or not measured["has_audio"] or not measured["has_video"]:
        raise RuntimeError("Final demo failed duration or media verification")
    verify_decode(destination)
    metadata = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(destination)]))
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
    if sha256_file(source_video) != source_before or any(
            sha256_file(capture / name) != value for name, value in captured_files.items()):
        raise RuntimeError("An input recording or capture changed during rendering")
    captions = verify_captions(info["shots"], measured["duration_ms"] / 1000, ROOT / "output/hardstop-demo.vtt")
    report = {**measured, "sha256": sha256_file(destination), "full_decode_verified": True,
              "source_video_sha256": source_before, "source_inputs_unchanged": True,
              "source_run_id": receipt["id"], "source_model": receipt.get("model", {}).get("model"),
              "capture_hashes": captured_files, "recording_disclosure": FOOTER,
              "optional_identifying_metadata_removed": True, "mean_volume_db": mean,
              "peak_volume_db": peak, "captions": captions}
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--capture-dir", type=Path, default=ROOT / ".state/demo-capture")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "output/demo-build")
    parser.add_argument("--source-video", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "output/hardstop-demo.mp4")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.work_dir)
    if args.render:
        if not args.source_video:
            parser.error("--render requires --source-video from the final verified run")
        render(args.capture_dir, args.work_dir, args.source_video, args.output)
    if not args.prepare and not args.render:
        parser.error("Choose --prepare or --render")


if __name__ == "__main__":
    main()
