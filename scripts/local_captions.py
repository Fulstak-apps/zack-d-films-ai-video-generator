#!/usr/bin/env python3
"""Generate local SRT captions with faster-whisper from the narration file."""
import argparse
import difflib
import re
from pathlib import Path


def stamp(seconds):
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def parse_stamp(value):
    hours, minutes, rest = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def reuse_whisper_timing(path):
    rows = []
    for block in path.read_text(encoding="utf-8-sig").strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            start, end = (parse_stamp(item.strip()) for item in lines[1].split("-->"))
            rows.extend((word, start, end) for word in " ".join(lines[2:]).split())
    return rows


def normal(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def align_reused_timing(authored, timing):
    heard_words = [normal(word) for word, _, _ in timing]
    aligned = [None] * len(authored)
    matcher = difflib.SequenceMatcher(a=heard_words, b=[normal(word) for word in authored], autojunk=False)
    for heard_at, authored_at, size in matcher.get_matching_blocks():
        for offset in range(size):
            _, start, end = timing[heard_at + offset]
            aligned[authored_at + offset] = (start, end)
    total = timing[-1][2]
    for index, value in enumerate(aligned):
        if value is None:
            start = total * index / len(authored)
            end = total * (index + 1) / len(authored)
            aligned[index] = (start, end)
    return [type("TimedWord", (), {"start": start, "end": end}) for start, end in aligned]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir")
    parser.add_argument("--model", default="base")
    parser.add_argument("--language", default=None)
    parser.add_argument("--reuse-timing-srt", action="store_true",
                        help="reuse an existing Whisper-created captions.srt as the timing clock")
    args = parser.parse_args()
    audio = Path(args.project_dir) / "audio"
    source = next((p for p in (audio / "narration.wav", audio / "narration.aiff") if p.is_file()), None)
    if source is None:
        parser.error("generate local narration first (scripts/local_tts.py)")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        parser.error("install dependencies with: pip install -r requirements-low-cost.txt")
    project = Path(args.project_dir)
    authored = " ".join(
        beat.get("narration", "").strip()
        for beat in __import__("json").loads((project / "beats.json").read_text(encoding="utf-8")).get("beats", [])
    ).split()
    target = audio / "captions.srt"
    if args.reuse_timing_srt:
        timing = reuse_whisper_timing(target)
        if not timing:
            parser.error("existing captions.srt has no usable Whisper timing")
        heard = align_reused_timing(authored, timing)
    else:
        model = WhisperModel(args.model, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(source), language=args.language, vad_filter=True, word_timestamps=True)
        heard = [word for segment in segments for word in (segment.words or [])]
    rows = []
    if len(heard) != len(authored):
        parser.error(f"transcript word count mismatch (heard {len(heard)}, authored {len(authored)}); do not burn unverified captions")
    cues = []
    start = 0
    while start < len(authored):
        chunk = authored[start:start + 5]
        while len(" ".join(chunk)) > 32 and len(chunk) > 1:
            chunk.pop()
        end = start + len(chunk)
        cues.append((heard[start].start, heard[end - 1].end, " ".join(chunk)))
        start = end
    for number, (start, end, text) in enumerate(cues, 1):
        rows.extend([str(number), f"{stamp(start)} --> {stamp(end)}", text, ""])
    target.write_text("\n".join(rows), encoding="utf-8")
    print(f"Saved local captions: {target}")


if __name__ == "__main__":
    main()
