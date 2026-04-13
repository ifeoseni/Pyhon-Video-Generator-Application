# AI Video Explainer Generator

A compact, local-first tool to generate short explainer videos from AI images and TTS voiceovers.

This repository provides a FastAPI-based scene editor and a small set of engines to:

- Generate voiceover audio from text (via `edge-tts`).
- Generate images from text prompts using **several selectable backends** (free no-key, free-with-signup, and Google Gemini / Imagen “Nano Banana” family).
- Compose images, audio and transitions into MP4 videos (via `moviepy` or `ffmpeg`).

Features

- Web UI: editing scene cards and rendering from the browser (`/` and `/bulk`).
- **Image generator dropdown** on the Scene Editor and in Bulk step 1 — choice is sent to the API and saved with projects.
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
- A working internet connection for image APIs and TTS.

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

## Image generation (providers)

The app no longer relies on a single low-quality default. In the UI, open **Image AI** (editor) or **Image generator** (bulk) and pick a backend. Metadata is also available at `GET /api/image-providers`.

| Provider ID | Summary | How to get Key |
| --- | --- | --- |
| `pollinations` | **No API key.** Pollinations.ai — fast, inconsistent quality. | N/A |
| `stable_horde_anon` | **No API key.** Uses the anonymous `0000000000` key. | N/A |
| `stable_horde` | **Free account** on [Stable Horde](https://stablehorde.net/register). | Register at [stablehorde.net](https://stablehorde.net/register). |
| `openai` | **OpenAI (DALL-E 3)**. Very high quality. | Get a key at [platform.openai.com](https://platform.openai.com/). |
| `together` | **Together AI**. Fast (Flux, SDXL). | Register at [together.ai](https://www.together.ai/) for free credits. |
| `huggingface_flux` | **FLUX.1 Schnell** via Hugging Face. | Create a token at [hf.co/settings/tokens](https://huggingface.co/settings/tokens). |
| `deepai` | **DeepAI**. Simple draft generator. | Get a key at [deepai.org](https://deepai.org/). |
| `gemini_...` | **Google Gemini Family**. | Get a key at [aistudio.google.com](https://aistudio.google.com/). |
| `imagen_fast` | **Google Imagen 4 Fast**. Photoreal. | Same as Gemini (Google AI Studio). |

### Managing API Keys
The app allows you to use your own API keys without setting environment variables on your server:
1. In the **Scene Editor** (top right) or **Bulk Mode** (header), click the **"API Keys"** button.
2. Enter your keys for the desired services.
3. Click **"Save Keys"**.
- Keys are stored **locally in your browser's localStorage**. They are sent with each generation request but never stored permanently on the server disk.
- If you prefer, you can still use server-side environment variables (e.g., `OPENAI_API_KEY`, `TOGETHER_API_KEY`, `GEMINI_API_KEY`).

Notes:

- **Nano Banana** is Google’s name for Gemini’s built-in conversational image generation; see the [Image generation](https://ai.google.dev/gemini-api/docs/image-generation) docs. Models and availability can change — if a model ID returns 404, check Google’s model list and open an issue or PR to update `image_engine.py`.
- Google image APIs may apply **SynthID** watermarking and regional restrictions (see Google’s docs).
- Providers that require a key will **surface errors** in the UI if the key is missing or invalid. Only Pollinations keeps the silent placeholder fallback after retries.

How it works (high level)

- The FastAPI app (`main.py`) exposes endpoints to generate or upload assets, then assemble them into scenes.
- `audio_engine.py` uses `edge-tts` to synthesize voiceovers to MP3.
- `image_engine.py` routes prompts to the selected provider (`generate_prompt_image(..., provider=...)`).
- `video_engine.py` composes scenes with `moviepy`. When all scenes are still images, `ffmpeg_render.py` will attempt a much faster FFmpeg-based path.
- Generated files are stored under `cache/` (per-scene) and final MP4s are placed in `output/`.

Running the server (development)

```bash
# from project root
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# open http://localhost:8000/ in your browser
```

API examples

1. List image providers

```bash
curl -s "http://localhost:8000/api/image-providers"
```

2. Generate a voiceover (async endpoint)

```bash
curl -X POST "http://localhost:8000/api/generate-audio" \\
  -F "text=Hello, this is a test voiceover" \\
  -F "voice=en-US-JennyNeural"

# Response: {"scene_id":"<id>","audio_url":"/api/media/<id>/voiceover.mp3"}
```

3. Generate an image from a prompt (optional `provider`)

```bash
curl -X POST "http://localhost:8000/api/generate-image" \\
  -F "prompt=Golden hour over a mountain lake, cinematic" \\
  -F "width=1920" -F "height=1080" \\
  -F "provider=gemini_nano_banana_2"
```

4. Generate an image and render a short motion video from it (single request)

```bash
curl -X POST "http://localhost:8000/api/generate-image-video" \\
  -F "prompt=A friendly robot giving a demo" \\
  -F "duration=6" \\
  -F "animation=ken_burns" \\
  -F "provider=stable_horde"

# Response contains a `video_url` such as "/api/media/<scene_id>/video.mp4"
```

5. Upload custom media for a scene (image / video / audio)

```bash
curl -X POST "http://localhost:8000/api/upload-media" \\
  -F "file=@/path/to/your/image.jpg" \\
  -F "scene_id=optional-scene-id"
```

Bulk JSON (`/api/bulk-generate` `payload` field) may include `"image_provider": "imagen_fast"` next to `image_source`, `orientation`, etc.

Where files are placed

- `cache/<scene_id>/` — per-scene temporary files (image.jpg, voiceover.mp3, video.mp4, etc.)
- `output/` — final exported MP4s (one-per-rendered-job)
- `projects/` — saved project JSON files (managed by the UI and API)
- `static/` — front-end HTML/CSS/JS (editor UI)

Important implementation notes

- The app prefers FFmpeg when available (`ffmpeg_render.py`). If `ffmpeg` is missing, MoviePy is used and may be significantly slower on long videos.
- Image routing is implemented in `image_engine.py` using `aiohttp`. Pollinations is the only backend that falls back to a local placeholder after repeated failures.
- TTS uses `edge-tts` which can list available voices with `edge-tts --list-voices`.
- The server will create `cache/` and `output/` directories at runtime if they do not exist.

Security & Privacy

- Uploaded/Generated media is stored locally under `cache/`, `output/` and `static/uploads/`.
- Be careful not to commit large or sensitive media files to Git—see the included `.gitignore` which prevents common media from being added.
- **Do not commit API keys.** Use environment variables or a local `.env` loader in your shell profile.

Troubleshooting

- If you see `FFmpeg not found` or encoding fails: install FFmpeg and ensure it is on your `PATH`.
- If Pollinations often yields placeholders: pick another provider or reduce resolution; you may be rate-limited.
- If Gemini/Imagen returns errors: confirm the model is enabled for your key in Google AI Studio and that billing / quota allows image generation.

Extending the project

- Add a provider in `image_engine.py` (`_IMAGE_PROVIDER_META` + branch in `generate_prompt_image`).
- Add cloud TTS: replace `audio_engine.generate_audio_from_text` with any other TTS provider that writes MP3 files.
- Add more render presets in `video_engine.RENDER_PRESETS` for quality vs speed tradeoffs.

Files of interest

- `main.py` — FastAPI app and HTTP endpoints.
- `audio_engine.py` — voice synthesis wrapper (edge-tts).
- `image_engine.py` — prompt → image (multi-provider).
- `video_engine.py` — scene assembly using MoviePy.
- `ffmpeg_render.py` — fast FFmpeg-based path for still-image scenes.
- `project_manager.py` — save/load/list/delete project JSON files in `projects/`.

License & contribution
This project is provided as-is. Feel free to open issues or PRs with improvements.

If you'd like, I can add example UI screenshots, more `curl` examples, or an automated `make`/`invoke` file for common tasks.
