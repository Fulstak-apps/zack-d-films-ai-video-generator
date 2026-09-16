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
    narration = " ".join(b.get("narration", "").strip() for b in data.get("beats", [])).strip()
    if not narration:
        parser.error("beats.json contains no narration")
    outdir = project / "audio"
    outdir.mkdir(parents=True, exist_ok=True)
    engine = args.engine
    if engine == "auto":
        engine = "say" if shutil.which("say") else "piper"
    output = outdir / ("narration.aiff" if engine == "say" else "narration.wav")
    if engine == "say":
        if not shutil.which("say"):
            parser.error("macOS 'say' was not found; use --engine piper")
        subprocess.run(["say", "-o", str(output), narration], check=True)
    else:
        executable = shutil.which("piper")
        if not executable or not args.voice:
            parser.error("Piper needs the piper executable and --voice / PIPER_VOICE_MODEL path")
        subprocess.run([executable, "--model", args.voice, "--output_file", str(output)],
                       input=narration, text=True, check=True)
    print(f"Saved local narration: {output}")


if __name__ == "__main__":
    main()
