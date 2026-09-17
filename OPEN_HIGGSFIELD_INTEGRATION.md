# Studio improvements from OpenHiggsfield

The linked project is a free self-hosted generation studio. It still requires the user's own generation platform key, so hosting the interface is free while model usage remains provider-billed.

This project adopts the useful workflow ideas without copying source code because the repository has no visible license file:

- `config/model_catalog.json` is the single source of truth for Wan 3 settings and input roles.
- `scripts/run_manifest.py` creates a resumable scene ledger so completed clips are skipped and failed scenes can be retried individually.
- Wan generation remains explicitly portrait-first and uses a start-frame role for every scene.
- Local narration, captions, assembly, and quality checks remain free.

## Built-in local studio

The project now includes its own browser studio. It keeps the Replicate credential on the local server and provides project selection, missing-scene generation, live logs, and a gallery for finished exports:

```bash
python scripts/studio_server.py
```

Open `http://127.0.0.1:8787`. Generation still uses Replicate billing; the interface itself has no subscription cost.

Run the ledger before generating clips:

```bash
python scripts/run_manifest.py out/my_story --model wan3
```

The studio’s gallery and run lifecycle are good future UI additions, but they do not reduce generation charges. The cost saving comes from local processing, scene reuse, strict retries, and avoiding duplicate requests.
