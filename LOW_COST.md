# Lower-cost Shorts workflow

This adds a local-first alternative to the default provider workflow. It retains the existing beats/keyframes/clips/FFmpeg project layout and does not change the upstream repository.

## What costs money

- Script: local Ollama; no API charge.
- TTS: macOS `say` or a locally installed Piper voice; no hosted TTS charge.
- Captions: faster-whisper on CPU; no hosted transcription charge.
- Assembly: FFmpeg; no API charge.
- Motion: Replicate's `wan-video/wan-2.2-i2v-fast` image-to-video model or Alibaba's `alibaba/wan-3` model. The studio estimates Wan 2.2 Fast at $0.05 per 480p clip, while Wan 3 is priced per second ($0.05/sec at 480p, $0.10/sec at 720p, and $0.20/sec at 1080p on the model page). Provider pricing and inputs can change; check the [Wan 2.2 page](https://replicate.com/wan-video/wan-2.2-i2v-fast) and [Wan 3 page](https://replicate.com/alibaba/wan-3) before running. Wan 2.2 Fast needs a portrait start frame; Wan 3 can use a prompt alone or an optional start frame. Reuse images or generate them with local ComfyUI to avoid the original MuAPI image-generation charge.

Seven new clips estimate to about $0.35, excluding retries and keyframe generation. Actual charges are determined by Replicate. Existing non-empty clips are skipped.

## Setup

1. Install Python 3.10+, FFmpeg, and Ollama. Pull a local model, for example `ollama pull qwen3:4b`.
2. From the repository root, install optional dependencies:

   ```sh
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements-low-cost.txt
   ```

3. Copy `.env.example` to `.env`; set `OLLAMA_MODEL` to a model already installed locally. Export `REPLICATE_API_TOKEN` only when ready to request Wan animations. Keep secrets out of Git. Before each run, load the settings into your shell with `set -a; source .env; set +a` (scripts do not auto-load `.env`).

## Run

```sh
# Local script/beat map. Review and edit beats.json before proceeding.
python3 scripts/local_script.py out/my_short --topic "What happens when you swallow gum?"

# Add keyframes at out/my_short/keyframes/<shot_id>.png using local ComfyUI or assets you own.

# Paid step. Default cap is $0.50; each run needs explicit --yes.
python3 scripts/wan_clips.py out/my_short --max-cost-usd 0.50 --yes

# Existing FFmpeg assembler for silent clips
python3 scripts/assemble.py out/my_short

# Local voice, local captions, mux voice and burn captions
python3 scripts/local_tts.py out/my_short
python3 scripts/local_captions.py out/my_short
python3 scripts/finish_local.py out/my_short --captions
```

Output: `out/my_short/final_captioned.mp4`. Omit `--captions` to mux voice without burning captions.

## Studio

For the browser workspace, start the local server from the repository root:

```sh
venv/bin/python scripts/studio_server.py
```

Then open <http://127.0.0.1:8787>. The studio loads `REPLICATE_API_TOKEN` from the local `.env`, but never sends the file to the browser or writes it into job logs. It only starts a paid request after you click Generate and confirm the displayed estimate. Build final video runs TTS, captions, FFmpeg assembly, and the quality gate locally.

The cost guard reads the selected model, resolution, and duration from the catalog, refuses to run over the per-run cap, and requires `--yes`. Retries are not automatic. Check actual billing in Replicate and review factual accuracy and generated clips before publishing.

### Clip Lab models

The studio's **Remix** action is deliberately separate from scene generation because these models take an existing video rather than a storyboard frame:

- `wan-video/wan-2.7-videoedit` changes a 2–10 second clip from a natural-language instruction while preserving its movement. The catalog estimates $0.10 per output second.
- `wan-video/wan-2.2-animate-animation` copies motion from an existing clip onto a supplied character image. The catalog estimates $0.003 per source second and requires the character image.

Both actions back up the current scene clip in `versions/<job-id>/previous.mp4` before replacing it. The [Wan 2.7 VideoEdit schema](https://replicate.com/wan-video/wan-2.7-videoedit/api/schema) and [Wan 2.2 Animate schema](https://replicate.com/wan-video/wan-2.2-animate-animation/api/schema) document the provider inputs and current pricing.

## Limitations

- Wan output is 480p and is scaled to the existing vertical canvas; motion quality is below higher-cost Veo output.
- Original `scripts/keyframes.py` and `scripts/character_sheets.py` still use MuAPI. Supply existing keyframes or use local image generation to keep that stage free.
- Local TTS defaults to macOS `say`; elsewhere install Piper and provide a model path.
- This branch does not automate YouTube uploading/scheduling.

## Environment variables

See [.env.example](.env.example). The only required secret for Wan is `REPLICATE_API_TOKEN`; Ollama runs locally. See the [Wan model page](https://replicate.com/wan-video/wan-2.2-i2v-fast) for current pricing and input schema.
## Required production order

Generate one clean **portrait 9:16 keyframe per shot**. Do not crop a storyboard sheet into production keyframes.

For every Short, run narration before animation assembly so each scene is timed to its spoken beat:

```bash
python scripts/local_tts.py out/my_story
python scripts/wan_clips.py out/my_story --max-cost-usd 0.50 --yes
python scripts/assemble.py out/my_story
python scripts/local_captions.py out/my_story --model base
python scripts/finish_local.py out/my_story --captions
python scripts/quality_gate.py out/my_story
```

`quality_gate.py` refuses exports that are not 1080x1920, have missing audio, end before narration, or contain captions that do not exactly match the approved script.
