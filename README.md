# ManiaStudio

ManiaStudio is a local web app for generating osu!mania beatmaps from music. Choose a key mode, target difficulty, and pattern preferences, then export a beatmap for osu!.

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

**This is currently a source-code-only repository.** Full generation also requires resources that are not included:

- Model checkpoints in `runtime/runs/`, as referenced by `control_backend.json` and `frozen_backend.json`.
- Normalization and conditioning data in `runtime/data/`.
- `node.exe`, `ffmpeg.exe`, and `ffprobe.exe` in `bin/`.

`Setup.ps1` installs Python dependencies, but does not download these additional resources. Third-party notices are preserved in `licenses/` and `runtime/third_party/`.

### Create a beatmap

1. With the required resources in place, double-click **`Start.cmd`**. First-time setup can install the Python dependencies automatically.
2. Open **http://localhost:8765** and upload music, or enter a YouTube URL and choose whether to include video.
3. Review the song metadata and add or replace background media if desired.
4. Select **4K or 7K**, a target star rating, and optional pattern preferences.
5. Generate and download the **`.osz`** package to import into osu!. A separate `.osu` download is also available.

Keep the launcher window open while using the app. Close it or press **Ctrl+C** to stop the server and its workers. Closing the browser tab alone does not stop the server.

Files remain in `workspace/` until you use **Clear history and files**. Files saved elsewhere and maps already imported into osu! are unaffected.

Difficulty and pattern controls are approximate. Generated maps still need playtesting.
