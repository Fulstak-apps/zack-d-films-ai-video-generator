#!/usr/bin/env python3
"""Create a resumable, inspectable record for every scene generation run."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--model", default="wan3")
    args = parser.parse_args()
    project = Path(args.project_dir)
    beats = json.loads((project / "beats.json").read_text(encoding="utf-8"))["beats"]
    catalog = json.loads((Path(__file__).parent.parent / "config/model_catalog.json").read_text())
    if args.model not in catalog:
        parser.error(f"unknown model catalog entry: {args.model}")
    entry = catalog[args.model]
    rows = []
    for beat in beats:
        for shot in beat.get("shots", []):
            image = project / "keyframes" / f"{shot['shot_id']}.png"
            clip = project / "clips" / f"{shot['shot_id']}.mp4"
            rows.append({
                "shot_id": shot["shot_id"], "status": "complete" if clip.is_file() else "ready",
                "start_frame": str(image), "output": str(clip), "model": entry["model"],
                "settings": entry["defaults"]
            })
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "model": args.model, "shots": rows}
    target = project / "run_manifest.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {target}: {len(rows)} scenes, {sum(r['status'] == 'complete' for r in rows)} complete")


if __name__ == "__main__":
    main()
