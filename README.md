# AI Video Explainer Generator

A compact, local-first tool to generate short explainer videos from AI images and TTS voiceovers.

This repository provides a FastAPI-based scene editor and a small set of engines to:

- Generate voiceover audio from text (via `edge-tts`).
- Generate images from text prompts (via Pollinations.ai fallback).
- Compose images, audio and transitions into MP4 videos (via `moviepy` or `ffmpeg`).

Features

- Web UI: editing scene cards and rendering from the browser (`/` and `/bulk`).
- API: single-scene and bulk endpoints for image/audio/video generation.
- Two rendering paths: fast FFmpeg-based assembly (recommended when `ffmpeg` is installed) and a MoviePy fallback.
- Project save/load and built-in templates.

Quick links

- Run server: `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- Web editor: `http://localhost:8000/` or `http://127.0.0.1:8000/`
- Bulk mode: `http://localhost:8000/bulk` or `http://127.0.0.1:8000/bulk`

Prerequisites

- Python 3.10+ (tested on 3.10–3.11).
- Git (optional).
- FFmpeg (strongly recommended for faster, reliable encoding). Ensure `ffmpeg` is on your `PATH`.
- A working internet connection for Pollinations image generation and external voice systems.

Python dependencies
Install the Python dependencies into a virtual environment:

```bash
python -m venv venv
# macOS / Linux
source venv/bin/activate
# Windows (PowerShell)
venv\\Scripts\\Activate.ps1
# or Git Bash / MINGW
source venv/Scripts/activate

pip install -r requirements.txt
```

If you want FFmpeg features (hardware encoding, much faster merging), install FFmpeg and verify with:

```bash
ffmpeg -version
```

How it works (high level)

- The FastAPI app (`main.py`) exposes endpoints to generate or upload assets, then assemble them into scenes.
- `audio_engine.py` uses `edge-tts` to synthesize voiceovers to MP3.
- `image_engine.py` fetches images from Pollinations.ai and falls back to a local placeholder if rate-limited.
- `video_engine.py` composes scenes with `moviepy`. When all scenes are still images, `ffmpeg_render.py` will attempt a much faster FFmpeg-based path.
- Generated files are stored under `cache/` (per-scene) and final MP4s are placed in `output/`.

Running the server (development)

```bash
# from project root
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# open http://localhost:8000/ in your browser
```

API examples

1. Generate a voiceover (async endpoint)

```bash
curl -X POST "http://localhost:8000/api/generate-audio" \\
  -F "text=Hello, this is a test voiceover" \\
  -F "voice=en-US-JennyNeural"

# Response: {"scene_id":"<id>","audio_url":"/api/media/<id>/voiceover.mp3"}
```

2. Generate an image from a prompt

```bash
curl -X POST "http://localhost:8000/api/generate-image" \\
  -F "prompt=Golden hour over a mountain lake, cinematic" \\
  -F "width=1920" -F "height=1080"
```

3. Generate an image and render a short motion video from it (single request)

```bash
curl -X POST "http://localhost:8000/api/generate-image-video" \\
  -F "prompt=A friendly robot giving a demo" \\
  -F "duration=6" \\
  -F "animation=ken_burns"

# Response contains a `video_url` such as "/api/media/<scene_id>/video.mp4"
```

4. Upload custom media for a scene (image / video / audio)

```bash
curl -X POST "http://localhost:8000/api/upload-media" \\
  -F "file=@/path/to/your/image.jpg" \\
  -F "scene_id=optional-scene-id"
```

Where files are placed

- `cache/<scene_id>/` — per-scene temporary files (image.jpg, voiceover.mp3, video.mp4, etc.)
- `output/` — final exported MP4s (one-per-rendered-job)
- `projects/` — saved project JSON files (managed by the UI and API)
- `static/` — front-end HTML/CSS/JS (editor UI)

Important implementation notes

- The app prefers FFmpeg when available (`ffmpeg_render.py`). If `ffmpeg` is missing, MoviePy is used and may be significantly slower on long videos.
- Image generation uses Pollinations.ai via a simple HTTP fetch. If the service is rate-limited, the code falls back to a local placeholder image.
- TTS uses `edge-tts` which can list available voices with `edge-tts --list-voices`.
- The server will create `cache/` and `output/` directories at runtime if they do not exist.

Security & Privacy

- Uploaded/Generated media is stored locally under `cache/`, `output/` and `static/uploads/`.
- Be careful not to commit large or sensitive media files to Git—see the included `.gitignore` which prevents common media from being added.

Troubleshooting

- If you see `FFmpeg not found` or encoding fails: install FFmpeg and ensure it is on your `PATH`.
- If image generation frequently returns placeholders: the Pollinations endpoint may be rate-limited; try again later or provide smaller images (lower width/height).

Extending the project

- Swap the image engine: replace `image_engine.generate_prompt_image` to call another image API or local diffusion service.
- Add cloud TTS: replace `audio_engine.generate_audio_from_text` with any other TTS provider that writes MP3 files.
- Add more render presets in `video_engine.RENDER_PRESETS` for quality vs speed tradeoffs.

Files of interest

- `main.py` — FastAPI app and HTTP endpoints.
- `audio_engine.py` — voice synthesis wrapper (edge-tts).
- `image_engine.py` — prompt → image (Pollinations.ai + placeholder fallback).
- `video_engine.py` — scene assembly using MoviePy.
- `ffmpeg_render.py` — fast FFmpeg-based path for still-image scenes.
- `project_manager.py` — save/load/list/delete project JSON files in `projects/`.

License & contribution
This project is provided as-is. Feel free to open issues or PRs with improvements.

If you'd like, I can add example UI screenshots, more `curl` examples, or an automated `make`/`invoke` file for common tasks.
