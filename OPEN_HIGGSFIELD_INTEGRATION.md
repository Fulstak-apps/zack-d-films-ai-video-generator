# Studio improvements from OpenHiggsfield

The linked project is a free self-hosted generation studio. It still requires the user's own generation platform key, so hosting the interface is free while model usage remains provider-billed. This branch keeps the original pipeline intact and adds an original local studio around it.

This project adopts the useful workflow ideas without copying source code because the repository has no visible license file. Replicate is used as a model backend, with each model kept behind the inputs it actually supports:

- `config/model_catalog.json` is the single source of truth for the supported Wan 3, Wan 2.2 Fast, Wan 2.7 VideoEdit, and Wan 2.2 Animate settings and input roles.
- `scripts/run_manifest.py` creates a resumable scene ledger so completed clips are skipped and failed scenes can be retried individually.
- Wan scene generation remains explicitly portrait-first and uses a start-frame role when the selected model requires one.
- The Clip Lab exposes Wan 2.7 VideoEdit for instruction-based edits and Wan 2.2 Animate for character motion transfer; those workflows require an existing video and are not incorrectly presented as text-to-video settings.
- Local narration, captions, assembly, and quality checks remain free.

## Built-in local studio

The project now includes its own browser studio. It keeps the Replicate credential on the local server and provides project selection, missing-scene generation, live logs, and a gallery for finished exports:

```bash
venv/bin/python scripts/studio_server.py
```

Open `http://127.0.0.1:8787`. Generation still uses Replicate billing; the interface itself has no subscription cost.

Run the ledger before generating clips:

```bash
python scripts/run_manifest.py out/my_story --model wan3
```

The studio supports:

- storyboard cards with search and ready/missing/image filters;
- scene prompt, narration, camera-move, and portrait start-frame editing;
- frame reuse from another project and safe single-scene regeneration;
- Wan 3 at 480p/720p/1080p and Wan 2.2 Fast at 480p for scene generation;
- Clip Lab remixing with Wan 2.7 VideoEdit and Wan 2.2 Animate, including model-specific reference inputs and cost estimates;
- a hard estimated-spend cap and an explicit confirmation before paid generation;
- local TTS, Whisper captions, FFmpeg assembly, quality gating, activity logs, favorites, downloads, and finished-film playback;
- browser access restricted to the local server, with `.env` and source files kept out of the media route.

The interface does not reduce generation charges. The cost saving comes from local processing, scene reuse, strict retries, and avoiding duplicate requests. Wan 3 is priced per second on its Replicate model page; Wan 2.2 Fast is modeled as a per-clip estimate. Provider pricing can change, so review the estimate and Replicate billing before production runs.
