#!/usr/bin/env python3
"""Mux local narration and optionally burn SRT captions onto video frames."""
import argparse
import json
import shutil
import subprocess
import textwrap
from pathlib import Path


def seconds(value):
    hours, minutes, rest = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def read_srt(path):
    entries = []
    for block in path.read_text(encoding="utf-8-sig").strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = (part.strip() for part in lines[1].split("-->"))
        raw = " ".join(line.strip() for line in lines[2:])
        words = raw.split()
        # Keep burned captions readable on a phone and inside the Shorts safe area.
        chunks = []
        current = []
        for word in words:
            candidate = " ".join(current + [word])
            if current and (len(current) >= 5 or len(candidate) > 32):
                chunks.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            chunks.append(" ".join(current))
        entries.append((seconds(start), seconds(end), "\n".join(chunks[:2])))
    return entries


def read_frame(stream, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def burn_captions(ffmpeg, ffprobe, video, audio, srt, output):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("caption burn-in requires Pillow; install requirements-low-cost.txt") from exc

    probe = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate", "-of", "json", str(video)],
        capture_output=True, text=True, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    width, height = int(stream["width"]), int(stream["height"])
    numerator, denominator = stream["avg_frame_rate"].split("/")
    fps = float(numerator) / float(denominator)
    frame_size = width * height * 3
    entries = read_srt(srt)
    font_path = next((p for p in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ) if Path(p).is_file()), None)
    font = ImageFont.truetype(font_path, max(32, round(width * 0.052))) if font_path else ImageFont.load_default()

    decoder = subprocess.Popen(
        [ffmpeg, "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        stdout=subprocess.PIPE)
    encoder = subprocess.Popen(
        [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{width}x{height}", "-r", f"{numerator}/{denominator}", "-i", "pipe:0",
         "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
         "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(output)], stdin=subprocess.PIPE)
    try:
        index = 0
        while True:
            raw = read_frame(decoder.stdout, frame_size)
            if not raw:
                break
            if len(raw) != frame_size:
                raise RuntimeError("FFmpeg returned an incomplete video frame")
            timestamp = index / fps
            while entries and entries[0][1] < timestamp:
                entries.pop(0)
            if entries and entries[0][0] <= timestamp <= entries[0][1]:
                image = Image.frombytes("RGB", (width, height), raw)
                draw = ImageDraw.Draw(image)
                bbox = draw.multiline_textbbox((0, 0), entries[0][2], font=font,
                                               align="center", spacing=8, stroke_width=3)
                text_width = bbox[2] - bbox[0]
                x = max(12, (width - text_width) // 2)
                safe_bottom = max(220, round(height * 0.18))
                y = height - safe_bottom - (bbox[3] - bbox[1])
                draw.multiline_text((x, y), entries[0][2], font=font, fill="white",
                                    align="center", spacing=8, stroke_width=3, stroke_fill="black")
                raw = image.tobytes()
            encoder.stdin.write(raw)
            index += 1
        encoder.stdin.close()
        decode_code = decoder.wait()
        encode_code = encoder.wait()
        if decode_code or encode_code:
            raise RuntimeError(f"FFmpeg caption render failed (decoder={decode_code}, encoder={encode_code})")
    finally:
        if decoder.stdout:
            decoder.stdout.close()
        if decoder.poll() is None:
            decoder.kill()
            decoder.wait()
        if encoder.poll() is None:
            encoder.kill()
            encoder.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir")
    parser.add_argument("--captions", action="store_true", help="burn audio/captions/captions.srt into output")
    args = parser.parse_args()
    project = Path(args.project_dir)
    video = project / "final.mp4"
    audio_dir = project / "audio"
    audio = next((p for p in (audio_dir / "narration.wav", audio_dir / "narration.aiff")
                  if p.is_file()), None)
    if not video.is_file() or audio is None:
        parser.error("need final.mp4 and generated local narration")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        parser.error("ffmpeg and ffprobe must be installed and on PATH")
    output = project / ("final_captioned.mp4" if args.captions else "final_with_voice.mp4")
    if args.captions:
        srt = audio_dir / "captions.srt"
        if not srt.is_file():
            parser.error(f"missing {srt}; run scripts/local_captions.py first")
        burn_captions(ffmpeg, ffprobe, video, audio, srt, output)
    else:
        subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(video), "-i", str(audio),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                        "-shortest", str(output)], check=True)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
