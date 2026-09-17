#!/usr/bin/env python3
"""Generate storyboard shot clips with the supported Replicate Wan scene models."""
import argparse
import json
import os
from pathlib import Path

MODEL = os.environ.get("WAN_MODEL", "alibaba/wan-3")
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
        if not image.is_file() and MODEL != "alibaba/wan-3":
            parser.error(f"missing keyframe: {image}")
        try:
            from PIL import Image
            with Image.open(image) as keyframe:
                width, height = keyframe.size
            if height <= width:
                parser.error(
                    f"keyframe must be portrait (height > width): {image} is {width}x{height}; "
                    "generate one 9:16 scene per shot, never crop a storyboard sheet"
                )
        except (ImportError, FileNotFoundError):
            pass
        todo.append((shot, image, output))

    duration = int(os.environ.get("WAN_DURATION_SECONDS", "4"))
    resolution = os.environ.get("WAN_RESOLUTION", "480p")
    if MODEL == "alibaba/wan-3":
        if resolution not in ("480p", "720p", "1080p") or not 2 <= duration <= 30:
            parser.error("invalid Wan 3 settings")
        per_clip = duration * {"480p": 0.05, "720p": 0.10, "1080p": 0.20}[resolution]
    elif MODEL == "wan-video/wan-2.2-i2v-fast":
        if resolution != "480p":
            parser.error("Wan 2.2 Fast currently supports 480p in this studio")
        per_clip = DEFAULT_CLIP_COST
    else:
        parser.error("unsupported model")
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

    client = replicate.Client(api_token=os.environ["REPLICATE_API_TOKEN"], timeout=300)
    (project / "clips").mkdir(parents=True, exist_ok=True)
    import urllib.request
    for shot, image, output in todo:
        prompt = (
            f"Subtle coherent cinematic 3D animation. Camera: {shot.get('camera_move', 'static')}. "
            f"{shot.get('scene_description', '')}"
        )
        print(f"Generating {shot['shot_id']} (run estimate {estimate:.2f} USD)")
        image_file = image.open("rb") if image.is_file() else None
        try:
            inputs = {
                "prompt": prompt,
                "duration": int(os.environ.get("WAN_DURATION_SECONDS", "4")),
                "resolution": os.environ.get("WAN_RESOLUTION", "480p"),
                "aspect_ratio": "9:16",
            }
            if image_file:
                inputs["image"] = image_file
            if MODEL == "wan-video/wan-2.2-i2v-fast":
                inputs.pop("duration")
                inputs.pop("aspect_ratio")
                inputs.update(num_frames=81, frames_per_second=16)
            result = client.run(MODEL, input=inputs)
        finally:
            if image_file:
                image_file.close()
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
