# ManiaStudio - Control Bundle

This Windows bundle includes Python, the ManiaStudio web tool, its control generation backend, the required model weights and runtime data, Node.js, FFmpeg, and ffprobe. You do not need to install Python yourself.

## Start and stop

1. Use 64-bit Windows and extract the entire `mania_studio` folder to a writable location.
2. Double-click `Start.cmd`.
3. On first launch, Python packages such as PyTorch are downloaded and installed automatically. Keep the window open during setup; internet access and several GB of free space are required. If setup is interrupted, open `Start.cmd` again to retry.
4. Use the web interface at http://localhost:8765.
5. Keep the launch window open. Close it or press Ctrl+C to stop the service and its download/generation workers. Closing the browser tab alone does not stop the service.

A compatible NVIDIA GPU can accelerate generation; CPU execution is also supported. Python itself is bundled, but third-party Python packages are intentionally not included in the ZIP. They are installed into this app's `python/Lib/site-packages` directory on first launch. After setup, local audio generation works offline; YouTube downloads require internet access. No system Python installation or PATH changes are needed.

## Generate a beatmap

Upload music or enter a YouTube URL. Choose whether to include a background video, review the metadata and background media, then select 4K or 7K, a target star rating, and optional pattern preferences. Download the generated `.osz` to import into osu!.

Use the flag menu at the top right to switch between Traditional Chinese (Taiwan) and English. Your language choice is remembered, and switching preserves the current form. The interface labels pattern preferences as **Dan preferences**.

Unselected Jack defaults to reduced-jack conditioning. Selected Jack emphasizes it. These are approximate model preferences, not guarantees of playability.

## Included model pipeline

- `runtime/runs/control_v1/control.pt`: the selected control model, which predicts key placement and long notes.
- `runtime/runs/full_epoch_large/epoch_complete.pt`: the required audio rhythm model, which predicts note onset candidates from music.

Both checkpoints are required by the control pipeline. No alternative key-placement model is included; the old `technique_adapter_v2` checkpoint and unrelated research artifacts are excluded. The bundle supports the control policy only.

`bundle_manifest.json` lists the packaged files and their SHA-256 hashes. User music, images, videos, beatmaps, history, test fixtures, and virtual environments are not included.

Your files are stored in `workspace/`. Use **Clear history and files** to remove app-managed media and generated results. Files saved elsewhere and maps already imported into osu! are unaffected.
