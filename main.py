import os
import uuid
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from audio_engine import generate_audio_from_text
from image_engine import generate_prompt_image
from video_engine import (
    render_video,
    ANIMATIONS,
    TRANSITIONS,
    ORIENTATIONS,
    RENDER_PRESETS,
    get_export_dimensions,
    estimate_output_duration_seconds,
    estimate_encode_wall_seconds,
)
from project_manager import (
    save_project, load_project, list_projects, delete_project,
    list_templates, get_template,
)

# ── Configuration ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
OUTPUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"

CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# Log static dir contents for easier debugging when index doesn't load.
logging.basicConfig(level=logging.INFO)
try:
    logging.info("Static dir: %s", STATIC_DIR)
    for p in STATIC_DIR.iterdir():
        logging.info("Static file: %s", p.name)
except Exception:
    logging.exception("Failed to list static dir")

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="AI Video Explainer Generator")

# Serve static files (HTML/CSS/JS)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Track video render progress  &  bulk job progress
render_jobs: dict[str, dict] = {}


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    """Serve the Scene Editor page."""
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse(content={"error": "index.html not found in static/"}, status_code=404)


@app.get("/bulk")
async def bulk_page():
    """Serve the Bulk Mode page."""
    idx = STATIC_DIR / "bulk.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse(content={"error": "bulk.html not found in static/"}, status_code=404)


# ══════════════════════════════════════════════════════════════════════════════
#  METADATA ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/voices")
async def api_list_voices():
    """Return a curated list of high-quality voices for the dropdown."""
    voices = [
        {"id": "en-US-JennyNeural", "name": "Jenny (US Female)", "lang": "en-US"},
        {"id": "en-US-GuyNeural", "name": "Guy (US Male)", "lang": "en-US"},
        {"id": "en-US-AriaNeural", "name": "Aria (US Female)", "lang": "en-US"},
        {"id": "en-US-DavisNeural", "name": "Davis (US Male)", "lang": "en-US"},
        {"id": "en-GB-SoniaNeural", "name": "Sonia (UK Female)", "lang": "en-GB"},
        {"id": "en-GB-RyanNeural", "name": "Ryan (UK Male)", "lang": "en-GB"},
        {"id": "en-AU-NatashaNeural", "name": "Natasha (AU Female)", "lang": "en-AU"},
        {"id": "en-AU-WilliamNeural", "name": "William (AU Male)", "lang": "en-AU"},
        {"id": "en-IN-NeerjaNeural", "name": "Neerja (IN Female)", "lang": "en-IN"},
        {"id": "en-IN-PrabhatNeural", "name": "Prabhat (IN Male)", "lang": "en-IN"},
    ]
    return JSONResponse(content=voices)


@app.get("/api/animations")
async def api_list_animations():
    """Return the list of available animation types."""
    items = [{"id": k, "name": k.replace("_", " ").title(), "description": v}
             for k, v in ANIMATIONS.items()]
    return JSONResponse(content=items)


@app.get("/api/transitions")
async def api_list_transitions():
    """Return the list of available transition types."""
    items = [{"id": k, "name": k.replace("_", " ").title(), "description": v}
             for k, v in TRANSITIONS.items()]
    return JSONResponse(content=items)


@app.get("/api/orientations")
async def api_list_orientations():
    """Return available orientations."""
    items = [{"id": k, "width": v[0], "height": v[1]} for k, v in ORIENTATIONS.items()]
    return JSONResponse(content=items)


# ══════════════════════════════════════════════════════════════════════════════
#  SCENE ASSET ENDPOINTS (single-scene operations)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/generate-audio")
async def api_generate_audio(
    text: str = Form(...),
    voice: str = Form("en-US-JennyNeural"),
    scene_id: str = Form(None),
):
    """Generate voiceover audio from text using edge-tts."""
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Text is required.")

    scene_id = scene_id or str(uuid.uuid4())
    scene_dir = CACHE_DIR / scene_id
    scene_dir.mkdir(exist_ok=True)
    audio_path = scene_dir / "voiceover.mp3"

    try:
        await generate_audio_from_text(text.strip(), str(audio_path), voice=voice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio generation failed: {str(e)}")

    return JSONResponse(content={
        "scene_id": scene_id,
        "audio_url": f"/api/media/{scene_id}/voiceover.mp3",
    })


@app.post("/api/generate-image")
async def api_generate_image(
    prompt: str = Form(...),
    scene_id: str = Form(None),
    width: int = Form(1920),
    height: int = Form(1080),
):
    """Generate an AI image from a text prompt using Pollinations.ai."""
    if not prompt or not prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required.")

    scene_id = scene_id or str(uuid.uuid4())
    scene_dir = CACHE_DIR / scene_id
    scene_dir.mkdir(exist_ok=True)
    image_path = scene_dir / "image.jpg"

    try:
        await generate_prompt_image(prompt.strip(), str(image_path), width=width, height=height)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

    return JSONResponse(content={
        "scene_id": scene_id,
        "image_url": f"/api/media/{scene_id}/image.jpg",
    })


@app.post("/api/generate-image-video")
async def api_generate_image_video(
    prompt: str = Form(...),
    scene_id: str = Form(None),
    width: int = Form(1920),
    height: int = Form(1080),
    duration: float = Form(5.0),
    animation: str = Form("ken_burns"),
):
    """Generate an AI image then render a short motion video from it (MP4).

    Returns a `video_url` pointing to `/api/media/{scene_id}/video.mp4`.
    """
    if not prompt or not prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required.")

    scene_id = scene_id or str(uuid.uuid4())
    scene_dir = CACHE_DIR / scene_id
    scene_dir.mkdir(exist_ok=True)
    image_path = scene_dir / "image.jpg"
    video_path = scene_dir / "video.mp4"

    try:
        await generate_prompt_image(prompt.strip(), str(image_path), width=width, height=height)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

    # Determine orientation from dims
    orientation = "portrait" if height > width else "landscape"

    # Render motion video from the generated image in a thread to avoid blocking
    loop = asyncio.get_running_loop()
    scenes = [
        {
            "media_path": str(image_path),
            "media_type": "image",
            "animation": animation,
            "duration": float(duration),
            "volume": 1.0,
            "mute_audio": True,
        }
    ]
    try:
        await loop.run_in_executor(None, render_video, scenes, str(video_path), orientation)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Video generation failed: {str(e)}")

    return JSONResponse(content={
        "scene_id": scene_id,
        "video_url": f"/api/media/{scene_id}/video.mp4",
    })


@app.post("/api/upload-media")
async def api_upload_media(
    file: UploadFile = File(...),
    scene_id: str = Form(None),
):
    """Upload a custom image or video file for a scene."""
    scene_id = scene_id or str(uuid.uuid4())
    scene_dir = CACHE_DIR / scene_id
    scene_dir.mkdir(exist_ok=True)

    ext = Path(file.filename).suffix.lower()
    allowed_image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    allowed_video_exts = {".mp4", ".webm", ".avi", ".mov", ".mkv"}
    allowed_audio_exts = {".mp3", ".wav", ".m4a", ".ogg"}

    if ext in allowed_image_exts:
        media_type = "image"
        save_name = f"image{ext}"
    elif ext in allowed_video_exts:
        media_type = "video"
        save_name = f"video{ext}"
    elif ext in allowed_audio_exts:
        media_type = "audio"
        save_name = f"voiceover{ext}"  # Saving as voiceover.ext so it gets picked up automatically by audio loaders
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    save_path = scene_dir / save_name
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    return JSONResponse(content={
        "scene_id": scene_id,
        "media_url": f"/api/media/{scene_id}/{save_name}",
        "media_type": media_type,
    })


@app.post("/api/upload-logo")
async def api_upload_logo(file: UploadFile = File(...)):
    """Upload a logo image that will be applied to rendered videos.

    Saves the logo into the static/uploads directory and returns a public URL.
    """
    uploads_dir = STATIC_DIR / "uploads"
    uploads_dir.mkdir(exist_ok=True)

    ext = Path(file.filename).suffix.lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise HTTPException(status_code=400, detail="Unsupported logo file type.")

    fname = f"logo_{uuid.uuid4().hex}{ext}"
    save_path = uploads_dir / fname
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    return JSONResponse(content={"url": f"/static/uploads/{fname}"})


@app.get("/api/media/{scene_id}/{filename}")
async def get_media(scene_id: str, filename: str):
    """Serve a media file from the cache."""
    file_path = CACHE_DIR / scene_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(str(file_path))


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER ENDPOINT (enhanced — now accepts animation, transition, orientation, volume)
# ══════════════════════════════════════════════════════════════════════════════

def _find_media(scene_dir: Path, preferred_type: str = None):
    """Find the media file in a scene cache directory."""
    if preferred_type == "video":
        for ext in [".mp4", ".webm", ".avi", ".mov", ".mkv"]:
            candidate = scene_dir / f"video{ext}"
            if candidate.exists():
                return str(candidate), "video"

    for ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
        candidate = scene_dir / f"image{ext}"
        if candidate.exists():
            return str(candidate), "image"

    if preferred_type != "video":
        for ext in [".mp4", ".webm", ".avi", ".mov", ".mkv"]:
            candidate = scene_dir / f"video{ext}"
            if candidate.exists():
                return str(candidate), "video"

    return None, None

def _find_audio(scene_dir: Path):
    for ext in [".mp3", ".wav", ".m4a", ".ogg"]:
        candidate = scene_dir / f"voiceover{ext}"
        if candidate.exists():
            return candidate
    return None


def _normalize_render_preset(name: Optional[str]) -> str:
    n = (name or "balanced").lower().strip()
    if n not in RENDER_PRESETS:
        return "balanced"
    return n


def _resolve_scenes_for_render(scenes_data: list[dict]) -> list[dict]:
    """Build scene dicts for video_engine plus per-scene duration for ETA estimates."""
    from moviepy import AudioFileClip

    scenes = []
    for i, s in enumerate(scenes_data):
        scene_dir = CACHE_DIR / s["scene_id"]
        audio_path = _find_audio(scene_dir)
        media_path, actual_type = _find_media(scene_dir, s.get("media_type", "image"))

        if not media_path:
            raise FileNotFoundError(f"No media found for scene {i + 1} (id: {s['scene_id']})")

        mute_audio = s.get("mute_audio", False)
        if not audio_path and not mute_audio:
            raise FileNotFoundError(f"No audio found for scene {i + 1} (id: {s['scene_id']})")

        dur = 5.0
        if audio_path and not mute_audio:
            ac = AudioFileClip(str(audio_path))
            dur = float(ac.duration)
            ac.close()

        scenes.append({
            "media_path": media_path,
            "audio_path": str(audio_path) if audio_path else None,
            "media_type": actual_type or "image",
            "animation": s.get("animation", "ken_burns"),
            "transition": s.get("transition", "crossfade"),
            "volume": float(s.get("volume", 1.0)),
            "mute_audio": mute_audio,
            "duration": dur,
            "subtitle": s.get("subtitle") or s.get("subtitleOverride") or None,
            "show_subtitles": bool(s.get("show_subtitles") or s.get("showSubtitles")),
        })
    return scenes


def _run_render(job_id: str, scenes: list[dict], orientation: str, preset: str, use_hw_accel: bool = False, logo_url: Optional[str] = None, logo_position: str = "bottom-right"):
    """Background task: renders the video and updates job status."""
    try:
        render_jobs[job_id]["status"] = "rendering"

        output_path = str(OUTPUT_DIR / f"{job_id}.mp4")

        def progress_cb(pct: int):
            render_jobs[job_id]["progress"] = int(pct)

        # Map public logo URL to filesystem path for ffmpeg to read.
        logo_path_fs = None
        try:
            if logo_url and logo_url.startswith("/static/"):
                logo_path_fs = str((BASE_DIR / logo_url.lstrip("/"))).replace("\\", "/")
                if not (BASE_DIR / logo_url.lstrip("/")).exists():
                    logo_path_fs = None
        except Exception:
            logo_path_fs = None

        render_video(
            scenes,
            output_path,
            orientation=orientation,
            preset=preset,
            progress_callback=progress_cb,
            use_hw_accel=use_hw_accel,
            logo_path=logo_path_fs,
            logo_position=logo_position,
        )

        render_jobs[job_id]["status"] = "done"
        render_jobs[job_id]["progress"] = 100
        render_jobs[job_id]["output_url"] = f"/api/download/{job_id}"

    except Exception as e:
        render_jobs[job_id]["status"] = "error"
        render_jobs[job_id]["error"] = str(e)


@app.post("/api/render")
async def api_render_video(
    background_tasks: BackgroundTasks,
    scenes: str = Form(...),
    orientation: str = Form("landscape"),
    render_preset: str = Form("balanced"),
    use_hw_accel: bool = Form(False),
    logo_url: Optional[str] = Form(None),
    logo_position: str = Form("bottom-right"),
):
    """
    Start a video render job.

    `scenes` is a JSON string:
    [
        {
            "scene_id": "...",
            "media_type": "image",
            "animation": "ken_burns",
            "transition": "crossfade",
            "volume": 1.0,
            "mute_audio": false
        }
    ]
    """
    try:
        scenes_data = json.loads(scenes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid scenes JSON.")

    if not scenes_data:
        raise HTTPException(status_code=400, detail="At least one scene is required.")

    if orientation not in ORIENTATIONS:
        orientation = "landscape"

    preset = _normalize_render_preset(render_preset)

    try:
        resolved = _resolve_scenes_for_render(scenes_data)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    tw, th, eff_fps = get_export_dimensions(orientation, preset)
    out_dur = estimate_output_duration_seconds(resolved)
    encode_est = estimate_encode_wall_seconds(
        out_dur, preset, tw, th, eff_fps, resolved
    )
    setup_est = 12.0
    total_est = int(max(15, round(setup_est + encode_est)))

    job_id = str(uuid.uuid4())
    import time

    render_jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "start_time": time.time(),
        "output_duration_seconds": round(out_dur, 1),
        "estimated_total_seconds": total_est,
        "render_preset": preset,
    }

    background_tasks.add_task(_run_render, job_id, resolved, orientation, preset, use_hw_accel, logo_url, logo_position)

    return JSONResponse(
        content={
            "job_id": job_id,
            "output_duration_seconds": round(out_dur, 1),
            "estimated_render_seconds": total_est,
            "render_preset": preset,
        }
    )


@app.get("/api/render-status/{job_id}")
async def api_render_status(job_id: str):
    """Check the status of a render job."""
    if job_id not in render_jobs:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    job = render_jobs[job_id]
    
    import time

    st = job.get("start_time")
    prog = job.get("progress", 0) / 100.0
    status = job.get("status")
    est_total = float(job.get("estimated_total_seconds") or 0)

    if status in {"done", "error"}:
        job["eta_seconds"] = 0
    elif st is not None and prog >= 0.995:
        job["eta_seconds"] = 0
    elif st is not None and status not in {"done", "error"}:
        elapsed = time.time() - float(st)
        if prog >= 0.04:
            by_rate = (elapsed / prog) - elapsed
        else:
            by_rate = max(0.0, est_total - elapsed) if est_total else 90.0
        cap = (est_total * 2.5 + 120) if est_total else 3600.0
        job["eta_seconds"] = max(0, int(min(by_rate, cap)))
    else:
        job["eta_seconds"] = max(0, int(est_total)) if est_total else 0

    return JSONResponse(content=job)


@app.get("/api/download/{job_id}")
async def api_download(job_id: str):
    """Download the rendered video."""
    file_path = OUTPUT_DIR / f"{job_id}.mp4"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Video not ready yet.")
    return FileResponse(
        str(file_path),
        media_type="video/mp4",
        filename="explainer_video.mp4",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  BULK GENERATION ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

async def _bulk_generate_pipeline(job_id: str, bulk_data: dict):
    """
    Async pipeline for bulk generation:
    1. Generate audio for all scenes
    2. Generate AI images (if requested)
    3. Render final video
    """
    try:
        import time
        render_jobs[job_id]["status"] = "generating_audio"
        render_jobs[job_id]["progress"] = 5
        if "start_time" not in render_jobs[job_id]:
            render_jobs[job_id]["start_time"] = time.time()

        scenes_input = bulk_data["scenes"]
        orientation = bulk_data.get("orientation", "landscape")
        default_voice = bulk_data.get("default_voice", "en-US-JennyNeural")
        image_source = bulk_data.get("image_source", "ai")
        preset = _normalize_render_preset(bulk_data.get("render_preset"))
        use_hw_accel = bool(bulk_data.get("use_hw_accel", False))
        target_w, target_h = ORIENTATIONS.get(orientation, (1920, 1080))

        scene_ids = []
        total = len(scenes_input)

        # Step 1: Generate audio for all scenes
        for i, scene in enumerate(scenes_input):
            # Use provided scene_id from frontend, or generate new
            scene_id = scene.get("scene_id")
            if not scene_id:
                scene_id = str(uuid.uuid4())
            scene_ids.append(scene_id)
            scene_dir = CACHE_DIR / scene_id
            scene_dir.mkdir(exist_ok=True)

            mute_audio = scene.get("mute_audio", False)
            narration = scene.get("narration", "").strip()

            existing_audio = _find_audio(scene_dir)
            if narration and not mute_audio and not existing_audio:
                voice = scene.get("voice", default_voice)
                audio_path = scene_dir / "voiceover.mp3"
                await generate_audio_from_text(narration, str(audio_path), voice=voice)

            pct = 5 + int((i + 1) / total * 30)
            render_jobs[job_id]["progress"] = pct
            render_jobs[job_id]["current_step"] = f"Audio {i+1}/{total}"

        # Step 2: Generate images
        render_jobs[job_id]["status"] = "generating_images"
        render_jobs[job_id]["progress"] = 35

        for i, scene in enumerate(scenes_input):
            scene_id = scene_ids[i]
            scene_dir = CACHE_DIR / scene_id

            # Check if media was pre-uploaded/pre-generated
            existing_media, _ = _find_media(scene_dir, "image")
            if not existing_media and image_source == "ai":
                prompt = scene.get("image_prompt", "").strip()
                if prompt:
                    image_path = scene_dir / "image.jpg"
                    await generate_prompt_image(prompt, str(image_path), width=target_w, height=target_h)

            pct = 35 + int((i + 1) / total * 25)
            render_jobs[job_id]["progress"] = pct
            render_jobs[job_id]["current_step"] = f"Image {i+1}/{total}"

        # Step 3: Render video
        render_jobs[job_id]["status"] = "rendering"
        render_jobs[job_id]["progress"] = 60
        render_jobs[job_id]["current_step"] = "Rendering video…"

        from moviepy import AudioFileClip

        render_scenes = []
        for i, scene in enumerate(scenes_input):
            scene_id = scene_ids[i]
            scene_dir = CACHE_DIR / scene_id
            audio_path = _find_audio(scene_dir)

            media_path, actual_type = _find_media(scene_dir, "image")

            if not media_path:
                raise FileNotFoundError(f"No media found for scene {i + 1}")

            mute_audio = scene.get("mute_audio", False)
            dur = 5.0
            if audio_path and not mute_audio:
                ac = AudioFileClip(str(audio_path))
                dur = float(ac.duration)
                ac.close()

            render_scenes.append({
                "media_path": media_path,
                "audio_path": str(audio_path) if audio_path else None,
                "media_type": actual_type or "image",
                "animation": scene.get("animation", "ken_burns"),
                "transition": scene.get("transition", "crossfade"),
                "volume": float(scene.get("volume", 1.0)),
                "mute_audio": mute_audio,
                "duration": dur,
                "subtitle": scene.get("subtitle") or scene.get("subtitleOverride") or None,
                "show_subtitles": bool(scene.get("show_subtitles") or scene.get("showSubtitles")),
            })

        output_path = str(OUTPUT_DIR / f"{job_id}.mp4")

        tw, th, eff_fps = get_export_dimensions(orientation, preset)
        out_dur = estimate_output_duration_seconds(render_scenes)
        enc_est = estimate_encode_wall_seconds(
            out_dur, preset, tw, th, eff_fps, render_scenes
        )
        elapsed = time.time() - render_jobs[job_id]["start_time"]
        render_jobs[job_id]["output_duration_seconds"] = round(out_dur, 1)
        render_jobs[job_id]["estimated_total_seconds"] = int(
            max(elapsed + 15, elapsed + enc_est + 8)
        )
        render_jobs[job_id]["render_preset"] = preset

        def progress_cb(pct):
            render_jobs[job_id]["progress"] = 60 + int(pct * 0.4)

        render_video(
            render_scenes,
            output_path,
            orientation=orientation,
            preset=preset,
            progress_callback=progress_cb,
            use_hw_accel=use_hw_accel,
        )

        render_jobs[job_id]["status"] = "done"
        render_jobs[job_id]["progress"] = 100
        render_jobs[job_id]["output_url"] = f"/api/download/{job_id}"
        render_jobs[job_id]["scene_ids"] = scene_ids
        render_jobs[job_id]["current_step"] = "Complete!"

    except Exception as e:
        logging.exception("Bulk pipeline failed for job %s", job_id)
        render_jobs[job_id]["status"] = "error"
        render_jobs[job_id]["error"] = str(e)


@app.post("/api/bulk-generate")
async def api_bulk_generate(
    background_tasks: BackgroundTasks,
    payload: str = Form(...),
):
    """
    Bulk generate a video from a JSON payload of all scenes.

    Payload format:
    {
        "orientation": "landscape",
        "default_voice": "en-US-JennyNeural",
        "image_source": "ai",
        "scenes": [
            {
                "narration": "...",
                "image_prompt": "...",
                "animation": "ken_burns",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": false
            }
        ]
    }
    """
    try:
        bulk_data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    if not bulk_data.get("scenes"):
        raise HTTPException(status_code=400, detail="At least one scene is required.")

    job_id = str(uuid.uuid4())
    import time

    n = len(bulk_data["scenes"])
    img_extra = 40 * n if bulk_data.get("image_source", "ai") == "ai" else 8 * n
    rough_total = max(90, 25 * n + img_extra + 45 * n)

    render_jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "current_step": "Queued",
        "start_time": time.time(),
        "estimated_total_seconds": rough_total,
    }

    # Schedule the async pipeline in the background on the running loop.
    asyncio.create_task(_bulk_generate_pipeline(job_id, bulk_data))

    return JSONResponse(
        content={
            "job_id": job_id,
            "estimated_total_seconds": rough_total,
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PROJECT MANAGEMENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/projects")
async def api_list_projects():
    """List all saved projects."""
    return JSONResponse(content=list_projects())


@app.get("/api/projects/{project_id}")
async def api_get_project(project_id: str):
    """Load a specific project."""
    project = load_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return JSONResponse(content=project)


@app.post("/api/projects/save")
async def api_save_project(payload: str = Form(...)):
    """Save a project (create or update)."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON.")
    project = save_project(data)
    return JSONResponse(content=project)


@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: str):
    """Delete a project."""
    deleted = delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found.")
    return JSONResponse(content={"deleted": True})


@app.get("/api/templates")
async def api_list_templates():
    """List available starter templates."""
    return JSONResponse(content=list_templates())


@app.get("/api/templates/{template_id}")
async def api_get_template(template_id: str):
    """Get a full template by ID."""
    tmpl = get_template(template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found.")
    return JSONResponse(content=tmpl)


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
