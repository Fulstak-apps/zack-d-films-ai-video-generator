#!/usr/bin/env python3
"""Mux local narration and optionally burn local SRT captions onto final.mp4."""
import argparse
import shutil
import subprocess
from pathlib import Path


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
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("ffmpeg was not found on PATH")
    output = project / ("final_captioned.mp4" if args.captions else "final_with_voice.mp4")
    command = [ffmpeg, "-y", "-i", str(video), "-i", str(audio),
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-crf", "20",
               "-preset", "medium", "-c:a", "aac", "-shortest"]
    if args.captions:
        srt = audio_dir / "captions.srt"
        if not srt.is_file():
            parser.error(f"missing {srt}; run scripts/local_captions.py first")
        escaped = str(srt.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        command.extend(["-vf", f"subtitles='{escaped}'"])
    command.append(str(output))
    subprocess.run(command, check=True)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
