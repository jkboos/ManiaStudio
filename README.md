# ManiaStudio

ManiaStudio is a local web app for generating osu!mania beatmaps from music. Choose a key mode, target difficulty, and pattern preferences, then export a beatmap for osu!.

This repository contains the web tool and its integration with a separate generation engine. It does not include model-training or research code.

## Features

- **4K and 7K generation**, with taps and long notes.
- **Target star rating and pattern preferences:** Speed, Stamina, Tech, Jack, Stream, and LN. Reduced-jack conditioning is the default unless Jack is selected.
- **Audio uploads** in MP3, WAV, OGG, and FLAC formats.
- **YouTube downloads** with or without video, automatic cover images, and song metadata.
- **Background images and videos**, including local uploads and previews. Video downloads prefer silent H.264 MP4 up to 720p and 30 fps; images use the highest available resolution among the checked candidates.
- **Editable metadata**, including Unicode and romanized titles, artist, creator, difficulty name, source, and tags.
- **Validated `.osu` and `.osz` exports**, with music, images, and optional video.
- **Generation history and cleanup** for app-managed files.

## Usage

### Requirements

Windows and Python 3.11 (64-bit, with the Python launcher). A compatible NVIDIA GPU can accelerate generation; CPU execution is also supported.

**This is currently a web-tool source repository.** Full generation also requires components that are not included:

- The generation engine in `runtime/`, including its `portable_generate.py` entry point and inference dependencies.
- Matching model checkpoints and conditioning data in `runtime/runs/` and `runtime/data/`, as referenced by the backend manifests.
- `node.exe`, `ffmpeg.exe`, and `ffprobe.exe` in `bin/`.

`Setup.ps1` installs Python dependencies, but does not download these additional components. External binary notices are preserved in `licenses/`; the generation engine must retain its own third-party notices.

### Create a beatmap

1. With the required resources in place, double-click **`Start.cmd`**. First-time setup can install the Python dependencies automatically.
2. Open **http://localhost:8765** and upload music, or enter a YouTube URL and choose whether to include video.
3. Review the song metadata and add or replace background media if desired.
4. Select **4K or 7K**, a target star rating, and optional pattern preferences.
5. Generate and download the **`.osz`** package to import into osu!. A separate `.osu` download is also available.

Keep the launcher window open while using the app. Close it or press **Ctrl+C** to stop the server and its workers. Closing the browser tab alone does not stop the server.

Files remain in `workspace/` until you use **Clear history and files**. Files saved elsewhere and maps already imported into osu! are unaffected.

Difficulty and pattern controls are approximate. Generated maps still need playtesting.
