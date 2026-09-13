#!/usr/bin/env python3
"""Render fictional sample recordings with a locally supplied stock voice model.

Optional dependencies: kokoro-onnx, soundfile and Pillow. The normal application
does not need these packages. Model weights are supplied locally, not downloaded
by this script. See THIRD_PARTY_NOTICES.md for model and runtime licenses.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont
from kokoro_onnx import Kokoro
import soundfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hardstop.media import probe, sha256_file, verify_decode
from hardstop.source import validate_catalog_metadata


def command(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)


def font(size, bold=False):
    choices = [('/System/Library/Fonts/Avenir Next.ttc', 0 if bold else 7),
               ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 0)]
    for filename, index in choices:
        if Path(filename).is_file():
            return ImageFont.truetype(filename, size, index=index)
    raise ValueError('Install Avenir Next or DejaVu Sans to render sample cards')


def lines(draw, text, xy, size, width, *, bold=False, fill='#F6F6F3'):
    x, y = xy
    face = font(size, bold)
    for paragraph in text.split('\n'):
        current = ''
        for word in paragraph.split():
            candidate = (current + ' ' + word).strip()
            if current and draw.textlength(candidate, font=face) > width:
                draw.text((x, y), current, font=face, fill=fill, anchor='lt')
                y += round(size * 1.25)
                current = word
            else:
                current = candidate
        draw.text((x, y), current, font=face, fill=fill, anchor='lt')
        y += round(size * 1.25)
    return y


def card(segment, index, total, target):
    canvas = Image.new('RGB', (1280, 720), '#101820')
    draw = ImageDraw.Draw(canvas)
    lines(draw, 'HardStop', (76, 54), 26, 500, bold=True, fill='#DCE7AD')
    lines(draw, f'{index + 1:02d} / {total:02d}', (1100, 58), 22, 130, fill='#ACB6C2')
    title_end = lines(draw, segment['title'], (76, 153), 48, 1110, bold=True)
    body_start = max(296, title_end + 46)
    body_size = 34 if len(segment['slide_text']) < 170 else 28
    end = lines(draw, segment['slide_text'], (76, body_start), body_size, 1110)
    if end > 618:
        raise ValueError('Sample slide text does not fit; shorten it before rendering')
    draw.line((76, 641, 1204, 641), fill='#34414F', width=1)
    lines(draw, 'Fictional sample. Synthetic voice.', (76, 668), 20, 1120, fill='#ACB6C2')
    canvas.save(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--voices', type=Path, required=True)
    parser.add_argument('--voice', default='af_heart')
    parser.add_argument('--speed', type=float, default=0.95)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    validate_catalog_metadata(catalog)
    if not catalog['fictional'] or not 0.8 <= args.speed <= 1.15:
        raise ValueError('Use a fictional catalog and a natural speech rate from 0.8 to 1.15')
    args.output.mkdir(parents=True, exist_ok=False)
    for segment in catalog['segments']:
        segment['media_path'] = segment['id'] + '.mp4'
    voice = Kokoro(str(args.model), str(args.voices))
    measured = []
    for index, segment in enumerate(catalog['segments']):
        stem = args.output / segment['id']
        png, wav, raw, final = [stem.with_suffix(suffix) for suffix in ('.png', '.wav', '.raw.mp4', '.mp4')]
        card(segment, index, len(catalog['segments']), png)
        samples, rate = voice.create(segment['transcript'], voice=args.voice, speed=args.speed, lang='en-us')
        soundfile.write(str(wav), samples, rate)
        duration = math.ceil((len(samples) / rate + 0.6) * 30) / 30
        command(['ffmpeg', '-v', 'error', '-nostdin', '-loop', '1', '-framerate', '30', '-i', str(png),
                 '-i', str(wav), '-af', 'adelay=300:all=1,apad', '-t', f'{duration:.6f}',
                 '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-threads', '2',
                 '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-ar', '48000', '-ac', '2',
                 '-map_metadata', '-1', '-movflags', '+faststart', str(raw)])
        command(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(raw), '-c', 'copy',
                 '-bsf:v', 'filter_units=remove_types=6', '-map_metadata', '-1', '-fflags', '+bitexact',
                 '-metadata', 'encoder=', '-metadata:s:v:0', 'encoder=', '-metadata:s:a:0', 'encoder=',
                 '-movflags', '+faststart', str(final)])
        raw.unlink()
        info = probe(final)
        verify_decode(final)
        measured.append({'id': segment['id'], **info, 'sha256': sha256_file(final), 'decode_verified': True})
        print(json.dumps({'id': segment['id'], 'duration_ms': info['duration_ms']}), flush=True)
    (args.output / 'catalog.json').write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + '\n')
    (args.output / 'verification.json').write_text(json.dumps({'voice': args.voice, 'speed': args.speed,
        'source_duration_ms': sum(s['duration_ms'] for s in measured), 'segments': measured}, indent=2) + '\n')


if __name__ == '__main__':
    main()
