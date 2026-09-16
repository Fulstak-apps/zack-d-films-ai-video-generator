#!/usr/bin/env python3
"""Generate shot clips from existing keyframes with Replicate's Wan 2.2 Fast I2V."""
import argparse
import json
import os
from pathlib import Path

MODEL = "wan-video/wan-2.2-i2v-fast"
DEFAULT_CLIP_COST = 0.05


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir")
    parser.add_argument("--max-cost-usd", type=float, default=0.50,
                        help="Hard upper bound for this run (default: 0.50 USD)")
    parser.add_argument("--yes", action="store_true",
                        help="Confirm that this run may incur provider charges")
    args = parser.parse_args()
    project = Path(args.project_dir)
    beats_path = project / "beats.json"
    if not beats_path.is_file():
        parser.error(f"missing {beats_path}")
    if not os.environ.get("REPLICATE_API_TOKEN"):
        parser.error("set REPLICATE_API_TOKEN before using Wan")

    data = json.loads(beats_path.read_text(encoding="utf-8"))
    shots = [shot for beat in data.get("beats", []) for shot in beat.get("shots", [])]
    todo = []
    for shot in shots:
        shot_id = shot["shot_id"]
        image = project / "keyframes" / f"{shot_id}.png"
        output = project / "clips" / f"{shot_id}.mp4"
        if output.is_file() and output.stat().st_size:
            continue
        if not image.is_file():
            parser.error(f"missing keyframe: {image}")
        todo.append((shot, image, output))

    per_clip = float(os.environ.get("WAN_CLIP_COST_USD", DEFAULT_CLIP_COST))
    estimate = len(todo) * per_clip
    if estimate > args.max_cost_usd:
        parser.error(f"estimated {estimate:.2f} USD exceeds cap {args.max_cost_usd:.2f} USD")
    if todo and not args.yes:
        parser.error(f"this run may cost about {estimate:.2f} USD; rerun with --yes to confirm")
    if not todo:
        print("All shot clips already exist; nothing to generate.")
        return

    try:
        import replicate
    except ImportError:
        parser.error("install dependencies with: pip install -r requirements-low-cost.txt")

    client = replicate.Client(api_token=os.environ["REPLICATE_API_TOKEN"])
    (project / "clips").mkdir(parents=True, exist_ok=True)
    import urllib.request
    for shot, image, output in todo:
        prompt = (
            f"Subtle coherent cinematic 3D animation. Camera: {shot.get('camera_move', 'static')}. "
            f"{shot.get('scene_description', '')}"
        )
        print(f"Generating {shot['shot_id']} (run estimate {estimate:.2f} USD)")
        with image.open("rb") as image_file:
            result = client.run(MODEL, input={
                "image": image_file,
                "prompt": prompt,
                "num_frames": int(os.environ.get("WAN_NUM_FRAMES", "81")),
                "resolution": "480p",
                "frames_per_second": 16,
            })
        url = getattr(result, "url", None) or (str(result) if result else "")
        if not url.startswith("http"):
            raise RuntimeError(f"Wan returned no downloadable video for {shot['shot_id']}: {result!r}")
        output.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, output)
        if output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"empty video output for {shot['shot_id']}")
        print(f"Saved {output}")
    print(f"Done. Provider estimate: about {estimate:.2f} USD; check Replicate usage for actual charges.")


if __name__ == "__main__":
    main()
