#!/usr/bin/env python3
"""Fail a Short export when its orientation, audio, duration, or captions are unsafe."""
import argparse
import json
import subprocess
from pathlib import Path


def probe(path, entries):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir")
    parser.add_argument("--video", default="final_captioned.mp4")
    args = parser.parse_args()
    project = Path(args.project_dir)
    video = project / args.video
    audio = next((p for p in (project / "audio/narration.aiff", project / "audio/narration.wav") if p.is_file()), None)
    srt = project / "audio/captions.srt"
    if not video.is_file() or audio is None or not srt.is_file():
        raise SystemExit("quality gate needs final video, narration, and captions")
    v = probe(video, "stream=codec_type,width,height:format=duration")
    streams = v.get("streams", [])
    picture = next((s for s in streams if s.get("codec_type") == "video"), None)
    sound = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not picture or not sound or picture["height"] <= picture["width"]:
        raise SystemExit("export must include audio and a portrait video stream")
    if picture["width"] != 1080 or picture["height"] != 1920:
        raise SystemExit("export must be 1080x1920")
    video_duration = float(v["format"]["duration"])
    audio_duration = float(probe(audio, "format=duration")["format"]["duration"])
    if abs(video_duration - audio_duration) > 0.25:
        raise SystemExit(f"duration mismatch: video {video_duration:.2f}s, narration {audio_duration:.2f}s")
    caption_words = " ".join(line.strip() for line in srt.read_text(encoding="utf-8").splitlines()
                               if line and not line.isdigit() and "-->" not in line).split()
    authored = " ".join(beat.get("narration", "") for beat in
                          json.loads((project / "beats.json").read_text(encoding="utf-8")).get("beats", [])).split()
    if caption_words != authored:
        raise SystemExit("caption words do not exactly match the authored narration")
    print(f"PASS: 1080x1920, audio present, {video_duration:.2f}s, {len(caption_words)} verified caption words")


if __name__ == "__main__":
    main()
