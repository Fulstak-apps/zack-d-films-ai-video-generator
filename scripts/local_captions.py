#!/usr/bin/env python3
"""Generate local SRT captions with faster-whisper from the narration file."""
import argparse
from pathlib import Path


def stamp(seconds):
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir")
    parser.add_argument("--model", default="base")
    parser.add_argument("--language", default=None)
    args = parser.parse_args()
    audio = Path(args.project_dir) / "audio"
    source = next((p for p in (audio / "narration.wav", audio / "narration.aiff") if p.is_file()), None)
    if source is None:
        parser.error("generate local narration first (scripts/local_tts.py)")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        parser.error("install dependencies with: pip install -r requirements-low-cost.txt")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(source), language=args.language, vad_filter=True)
    rows = []
    for number, segment in enumerate(segments, 1):
        text = segment.text.strip()
        if text:
            rows.extend([str(number), f"{stamp(segment.start)} --> {stamp(segment.end)}", text, ""])
    target = audio / "captions.srt"
    target.write_text("\n".join(rows), encoding="utf-8")
    print(f"Saved local captions: {target}")


if __name__ == "__main__":
    main()
