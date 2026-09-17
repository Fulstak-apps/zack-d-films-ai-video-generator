#!/usr/bin/env python3
"""Apply a Replicate video edit or transfer motion to a character image."""
import argparse
import os
import subprocess
import urllib.request
from pathlib import Path


MODELS = {
    'wan-video/wan-2.7-videoedit': {
        'kind': 'video_edit',
        'resolutions': ('720p', '1080p'),
        'rate': 0.10,
        'min_duration': 2,
        'max_duration': 10,
    },
    'wan-video/wan-2.2-animate-animation': {
        'kind': 'motion_transfer',
        'resolutions': ('480', '720'),
        'rate': 0.003,
        'min_duration': 2,
        'max_duration': 60,
    },
}


def probe_video(path):
    """Return source duration and dimensions before a paid request is made."""
    result = subprocess.run(
        [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height:format=duration',
            '-of', 'default=noprint_wrappers=1', str(path),
        ], capture_output=True, text=True, check=False,
    )
    try:
        values = dict(
            line.split('=', 1) for line in result.stdout.splitlines() if '=' in line
        )
        duration = float(values['duration'])
        width = int(values['width'])
        height = int(values['height'])
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f'could not read source video metadata: {path}') from exc
    if duration <= 0:
        raise RuntimeError(f'source video has no duration: {path}')
    if width >= height:
        raise RuntimeError(f'source video must be portrait (9:16), got {width}x{height}: {path}')
    return duration, width, height


def output_url(result):
    url = getattr(result, 'url', None) or (str(result) if result else '')
    if not url.startswith('http'):
        raise RuntimeError(f'Replicate returned no downloadable video: {result!r}')
    return url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_dir')
    parser.add_argument('--shot', required=True)
    parser.add_argument('--model', required=True, choices=sorted(MODELS))
    parser.add_argument('--source-video', required=True)
    parser.add_argument('--reference-image')
    parser.add_argument('--prompt', default='')
    parser.add_argument('--resolution')
    parser.add_argument('--duration', type=int)
    parser.add_argument('--max-cost-usd', type=float, default=0.50)
    parser.add_argument('--yes', action='store_true', help='Confirm that this run may incur provider charges')
    args = parser.parse_args()

    if not os.environ.get('REPLICATE_API_TOKEN'):
        parser.error('set REPLICATE_API_TOKEN before using Replicate')
    source = Path(args.source_video)
    if not source.is_file():
        parser.error(f'missing source video: {source}')
    model = MODELS[args.model]
    resolution = args.resolution or ('720p' if model['kind'] == 'video_edit' else '480')
    if resolution not in model['resolutions']:
        parser.error(f'unsupported resolution for {args.model}: {resolution}')
    source_duration, _, _ = probe_video(source)
    if model['kind'] == 'video_edit' and source_duration > 10.5:
        parser.error('Wan 2.7 VideoEdit accepts source videos up to 10 seconds')
    duration = args.duration or round(source_duration)
    if not model['min_duration'] <= duration <= model['max_duration']:
        parser.error(
            f'{args.model} accepts {model["min_duration"]}–{model["max_duration"]} seconds; '
            f'got {duration}'
        )
    if model['kind'] == 'motion_transfer' and not args.reference_image:
        parser.error('Wan 2.2 Animate needs a character image')
    if args.reference_image and not Path(args.reference_image).is_file():
        parser.error(f'missing reference image: {args.reference_image}')
    if model['kind'] == 'video_edit' and not args.prompt.strip():
        parser.error('Wan 2.7 VideoEdit needs an editing instruction')

    estimate = duration * model['rate']
    if estimate > args.max_cost_usd:
        parser.error(f'estimated {estimate:.3f} USD exceeds cap {args.max_cost_usd:.2f} USD')
    if not args.yes:
        parser.error(f'this run may cost about {estimate:.3f} USD; rerun with --yes to confirm')

    try:
        import replicate
    except ImportError:
        parser.error('install dependencies with: pip install -r requirements-low-cost.txt')

    inputs = {}
    source_file = source.open('rb')
    reference_file = Path(args.reference_image).open('rb') if args.reference_image else None
    try:
        if model['kind'] == 'video_edit':
            inputs.update(
                video=source_file,
                prompt=args.prompt.strip(),
                duration=duration,
                resolution=resolution,
                aspect_ratio='9:16',
                audio_setting='origin',
            )
            if reference_file:
                inputs['reference_image'] = reference_file
        else:
            inputs.update(
                video=source_file,
                character_image=reference_file,
                resolution=resolution,
                frames_per_second=24,
                go_fast=True,
                refert_num=1,
                merge_audio=False,
            )
        client = replicate.Client(api_token=os.environ['REPLICATE_API_TOKEN'], timeout=900)
        print(f'Running {args.model} for {args.shot} (estimate ${estimate:.3f})')
        result = client.run(args.model, input=inputs)
    finally:
        source_file.close()
        if reference_file:
            reference_file.close()

    output = Path(args.project_dir) / 'clips' / f'{args.shot}.mp4'
    output.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(output_url(result), output)
    if not output.is_file() or not output.stat().st_size:
        output.unlink(missing_ok=True)
        raise RuntimeError(f'empty video output for {args.shot}')
    try:
        probe_video(output)
    except RuntimeError:
        output.unlink(missing_ok=True)
        raise RuntimeError(f'Replicate returned a non-portrait video for {args.shot}')
    print(f'Saved {output}')
    print(f'Provider estimate: about ${estimate:.3f}; check Replicate usage for actual charges.')


if __name__ == '__main__':
    main()
