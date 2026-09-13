#!/usr/bin/env python3
"""Create a fictional, explicitly synthesized eight-clip source presentation.

Requires Pillow, FFmpeg and macOS `say`. All output is generated under --output;
the committed catalog is never rewritten. No API credentials or services are used.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardstop.media import MediaError, _run, _tool, probe, sha256_file, verify_decode

W, H = 1280, 720
INK = "#F6F8FF"
MUTED = "#AEBDE6"
CITRUS = "#D8F366"
FONT = "/System/Library/Fonts/Avenir Next.ttc"


def font(size: int, bold: bool = False):
    # macOS Avenir Next collection: index 0 Bold, index 7 Regular.
    choices = [FONT, "/System/Library/Fonts/Helvetica.ttc",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for candidate in choices:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size, index=(0 if bold else 7) if candidate == FONT else 0)
    raise MediaError("No suitable font found for sample media")


def wrap(draw, value: str, size: int, max_width: int, bold=False) -> list[str]:
    selected_font = font(size, bold)
    lines = []
    for paragraph in value.split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if current and draw.textlength(candidate, font=selected_font) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def text(draw, value, xy, size, color=INK, max_width=1120, bold=False, spacing=1.2):
    x, y = xy
    lines = wrap(draw, value, size, max_width, bold)
    for line in lines:
        draw.text((x, y), line, font=font(size, bold), fill=color, anchor="lt")
        y += round(size * spacing)
    return y


def arrow(draw, x1, x2, y, color=CITRUS, width=4):
    draw.line((x1, y, x2, y), fill=color, width=width)
    draw.polygon([(x2, y), (x2 - 13, y - 8), (x2 - 13, y + 8)], fill=color)


def card(segment: dict, index: int, path: Path):
    image = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(image)
    for y in range(H):
        blend = y / H
        color = (round(11 + blend * 8), round(19 + blend * 14), round(42 + blend * 24))
        draw.line((0, y, W, y), fill=color)
    # A restrained cobalt field and one accent rule give all source slides a family.
    draw.rectangle((1184, 0, W, H), fill="#1C3ECD")
    draw.rectangle((80, 72, 152, 78), fill=CITRUS)
    label = "RELAY" if segment["id"] == "opening" else segment["title"]
    title_size = 30 if segment["id"] == "opening" else 42
    text(draw, label, (80, 102), title_size, max_width=1020, bold=True)
    ident = segment["id"]
    if ident == "opening":
        text(draw, "Every handoff\nneeds a next move.", (80, 213), 76, max_width=1060, bold=True, spacing=1.14)
        text(draw, "Owner. Action. Evidence.", (84, 443), 30, MUTED)
        arrow(draw, 84, 520, 537)
    elif ident == "problem":
        for line, y in zip(["A request in chat.", "A decision in a document.", "A deadline in a calendar."], [222, 293, 364]):
            text(draw, line, (80, y), 38, MUTED)
        text(draw, "Who owns the next move?", (80, 487), 46, CITRUS, bold=True)
    elif ident == "workflow":
        xs = [80, 468, 855]
        for number, x, words in zip(["01", "02", "03"], xs, ["Notice\nthe change", "Name\nthe owner", "Confirm\nthe next move"]):
            text(draw, number, (x, 224), 30, CITRUS)
            text(draw, words, (x, 283), 41, max_width=300, bold=True)
        arrow(draw, 342, 432, 319)
        arrow(draw, 729, 819, 319)
        text(draw, "People approve consequential actions.", (80, 511), 29, MUTED)
    elif ident == "pilot_context":
        text(draw, "12", (73, 201), 174, CITRUS, bold=True)
        text(draw, "simulated handoffs", (310, 245), 44, bold=True)
        text(draw, "One invented team.", (313, 319), 31, MUTED)
        text(draw, "Illustrative counts,\nnot measured customer outcomes.", (80, 446), 38, max_width=1020)
    elif ident == "result":
        text(draw, "5", (80, 202), 174, MUTED, bold=True)
        arrow(draw, 255, 465, 306, CITRUS, 8)
        text(draw, "2", (520, 202), 174, CITRUS, bold=True)
        text(draw, "Unresolved handoffs\nin the fictional scenario", (740, 265), 30, max_width=385)
        text(draw, "Interpret only with the pilot context.", (80, 478), 36, MUTED)
    elif ident == "rollout":
        for x, number, words in [(80, "1", "team"), (460, "1", "recurring handoff"), (840, "1", "week")]:
            text(draw, number, (x, 215), 138, CITRUS, bold=True)
            text(draw, words, (x, 396), 29, max_width=340)
        text(draw, "Review evidence before expanding.", (80, 516), 34, MUTED)
    elif ident == "disclaimer":
        text(draw, "Invented product,\nscenario, and outcomes.", (80, 219), 55, max_width=1050, bold=True)
        text(draw, "Synthesized narration.", (80, 421), 33, CITRUS)
        text(draw, "No customer claims or promised results.", (80, 493), 33, MUTED)
    elif ident == "call_to_action":
        for line, y in [("Choose one recurring handoff.", 221), ("Name its owner.", 320), ("Agree what done means.", 419)]:
            text(draw, line, (80, y), 49, CITRUS if y == 320 else INK, bold=True)
    else:
        text(draw, segment["slide_text"], (80, 220), 44, max_width=1010)
    draw.line((80, 618, 1120, 618), fill="#3A4969", width=1)
    text(draw, "Fictional sample · Synthesized narration", (80, 645), 20, MUTED)
    text(draw, f"{index + 1:02d} / 08", (1026, 645), 20, MUTED)
    image.save(path)


def generate(catalog_path: Path, output: Path, voice: str = "Samantha") -> dict:
    data = json.loads(catalog_path.read_text())
    if data.get("fictional") is not True:
        raise MediaError("Demo generation requires an explicitly fictional catalog")
    output.mkdir(parents=True, exist_ok=True)
    generated = []
    for index, segment in enumerate(data["segments"]):
        ident = segment["id"]
        if not ident.replace("_", "").isalnum():
            raise MediaError("Invalid sample segment ID")
        png = output / f"{ident}.png"
        audio = output / f"{ident}.aiff"
        mp4 = output / f"{ident}.mp4"
        card(segment, index, png)
        # Input comes from a text file, never shell interpolation.
        transcript = output / f"{ident}.txt"
        transcript.write_text(segment["transcript"])
        _run([_tool("say"), "-v", voice, "-r", "154", "-f", str(transcript), "-o", str(audio)], timeout=120)
        spoken_ms = probe(audio)["duration_ms"]
        # Include a clean half second before/after speech. Frame-aligned durations
        # let the solver work from conservative, real measured container lengths.
        frames = math.ceil((spoken_ms / 1000 + 1.0) * 30)
        seconds = frames / 30
        _run([_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
              "-loop", "1", "-framerate", "30", "-i", str(png), "-i", str(audio),
              "-filter:a", "adelay=500:all=1,apad", "-t", f"{seconds:.6f}",
              "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-crf", "19",
              "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
              "-ar", "48000", "-ac", "2", "-movflags", "+faststart", "-map_metadata", "-1", str(mp4)], timeout=300)
        info = probe(mp4)
        verify_decode(mp4)
        generated.append({**segment, **info, "media_path": str(mp4.resolve()),
                          "card_path": str(png.resolve()), "sha256": sha256_file(mp4),
                          "slide_id": f"hs_{ident}", "decode_verified": True,
                          "narration": "Synthesized local text-to-speech (Samantha)"})
        print(f"Generated {ident}: {info['duration_ms']} ms", flush=True)
    manifest = {**data, "segments": generated,
                "source_duration_ms": sum(s["duration_ms"] for s in generated),
                "catalog_sha256": sha256_file(catalog_path),
                "source_kind": "fictional_synthesized_recording"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path(__file__).resolve().parents[1] / "fixtures/catalog.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / ".state/demo-assets")
    parser.add_argument("--voice", default="Samantha")
    args = parser.parse_args()
    result = generate(args.catalog.resolve(), args.output.resolve(), args.voice)
    print(json.dumps({"source_duration_ms": result["source_duration_ms"], "manifest": str(args.output.resolve() / "manifest.json")}))


if __name__ == "__main__":
    main()
