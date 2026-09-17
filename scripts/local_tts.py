#!/usr/bin/env python3
"""Synthesize beat narration locally with macOS 'say' or Piper; no hosted TTS."""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir")
    parser.add_argument("--engine", choices=("auto", "say", "piper"), default="auto")
    parser.add_argument("--voice", default=os.getenv("PIPER_VOICE_MODEL", ""))
    args = parser.parse_args()
    project = Path(args.project_dir)
    data = json.loads((project / "beats.json").read_text(encoding="utf-8"))
    beats = [b.get("narration", "").strip() for b in data.get("beats", [])]
    if not any(beats):
        parser.error("beats.json contains no narration")
    outdir = project / "audio"
    outdir.mkdir(parents=True, exist_ok=True)
    engine = args.engine
    if engine == "auto":
        engine = "say" if shutil.which("say") else "piper"
    suffix = ".aiff" if engine == "say" else ".wav"
    output = outdir / f"narration{suffix}"
    beat_outputs = []
    if engine == "say":
        if not shutil.which("say"):
            parser.error("macOS 'say' was not found; use --engine piper")
        for index, narration in enumerate(beats, 1):
            if not narration:
                continue
            beat_output = outdir / f"beat_{index}{suffix}"
            subprocess.run(["say", "-o", str(beat_output), narration], check=True)
            beat_outputs.append(beat_output)
    else:
        executable = shutil.which("piper")
        if not executable or not args.voice:
            parser.error("Piper needs the piper executable and --voice / PIPER_VOICE_MODEL path")
        for index, narration in enumerate(beats, 1):
            if not narration:
                continue
            beat_output = outdir / f"beat_{index}{suffix}"
            subprocess.run([executable, "--model", args.voice, "--output_file", str(beat_output)],
                           input=narration, text=True, check=True)
            beat_outputs.append(beat_output)
    if not beat_outputs:
        parser.error("no usable beat narration was generated")
    concat = outdir / "narration.concat.txt"
    concat.write_text("".join(f"file '{path.resolve()}'\n" for path in beat_outputs), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-c", "copy", str(output)], check=True)
    print(f"Saved local narration: {output}")


if __name__ == "__main__":
    main()
