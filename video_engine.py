from __future__ import annotations

import os
import numpy as np
import logging
from proglog import ProgressBarLogger

from ffmpeg_render import ffmpeg_available, scenes_eligible_for_ffmpeg, render_with_ffmpeg
from moviepy import (
    ImageClip,
    VideoFileClip,
    AudioFileClip,
    ColorClip,
    concatenate_videoclips,
    CompositeVideoClip,
    vfx,
)

# ── Available Animations & Transitions ────────────────────────────────────

ANIMATIONS = {
    "none":       "No animation — static image",
    "zoom_in":    "Slow zoom into the center",
    "zoom_out":   "Slow zoom out from the center",
    "pan_left":   "Slow horizontal pan from right to left",
    "pan_right":  "Slow horizontal pan from left to right",
    "pan_up":     "Slow vertical pan from bottom to top",
    "pan_down":   "Slow vertical pan from top to bottom",
    "ken_burns":  "Classic Ken Burns — gentle zoom with slight pan",
}

TRANSITIONS = {
    "none":        "No transition — hard cut",
    "crossfade":   "Smooth opacity crossfade",
    "fade_black":  "Fade out to black, then fade in",
    "slide_left":  "New scene slides in from the right",
    "slide_right": "New scene slides in from the left",
    "wipe_down":   "Top-to-bottom wipe reveal",
}

ORIENTATIONS = {
    "landscape": (1920, 1080),
    "portrait":  (1080, 1920),
}

# Export presets: lower resolution + fps = much faster encoding and fewer frames to composite.
RENDER_PRESETS = {
    "fast": {
        "max_side": 1280,
        "fps": 20,
        "preset": "ultrafast",
        "crf": "26",
        "audio_bitrate": "128k",
        "oversample": 1.08,
        "encode_factor": 0.22,
        "ffmpeg_encode_factor": 0.07,
        "ffmpeg_params": ["-movflags", "+faststart", "-tune", "stillimage"],
    },
    "balanced": {
        "max_side": None,
        "fps": 24,
        "preset": "veryfast",
        "crf": "23",
        "audio_bitrate": "192k",
        "oversample": 1.12,
        "encode_factor": 0.48,
        "ffmpeg_encode_factor": 0.11,
        "ffmpeg_params": ["-movflags", "+faststart"],
    },
    "high": {
        "max_side": None,
        "fps": 30,
        "preset": "medium",
        "crf": "18",
        "audio_bitrate": "256k",
        "oversample": 1.15,
        "encode_factor": 0.95,
        "ffmpeg_encode_factor": 0.22,
        "ffmpeg_params": ["-movflags", "+faststart"],
    },
}


def _dims_for_preset(base_w: int, base_h: int, preset_name: str) -> tuple[int, int]:
    cfg = RENDER_PRESETS.get(preset_name, RENDER_PRESETS["balanced"])
    cap = cfg.get("max_side")
    if not cap:
        return base_w, base_h
    if base_w >= base_h:
        if base_w <= cap:
            return base_w, base_h
        nw = cap
        nh = max(2, int(round(base_h * (cap / base_w))))
        if nh % 2:
            nh += 1
        return nw, nh
    if base_h <= cap:
        return base_w, base_h
    nh = cap
    nw = max(2, int(round(base_w * (cap / base_h))))
    if nw % 2:
        nw += 1
    return nw, nh


def estimate_output_duration_seconds(scenes: list[dict], trans_overlap: float = 0.7) -> float:
    """
    Approximate final timeline length from scene dicts (must include accurate per-scene duration).
    """
    if not scenes:
        return 0.0
    total = 0.0
    for s in scenes:
        total += float(s.get("duration", 5.0))
    fades = sum(
        1 for s in scenes[1:] if s.get("transition", "crossfade") != "none"
    )
    return max(0.1, total - fades * trans_overlap)


class _WriteProgressLogger(ProgressBarLogger):
    """Maps MoviePy audio chunks + video frames to overall 36–96% progress."""

    def __init__(self, on_percent):
        super().__init__()
        self.on_percent = on_percent

    def bars_callback(self, bar, attr, value, old_value=None):
        if attr != "index":
            return
        info = self.bars.get(bar)
        if not info:
            return
        total = info.get("total")
        if not total or total <= 0:
            return
        frac = min(1.0, max(0.0, float(value) / float(total)))
        if bar == "chunk":
            p = 36 + int(3 * frac)
        elif bar == "frame_index":
            p = 40 + int(56 * frac)
        else:
            return
        if self.on_percent:
            self.on_percent(p)


def get_export_dimensions(orientation: str, preset: str) -> tuple[int, int, int]:
    """Output width, height, and fps for the given orientation and preset."""
    base_w, base_h = ORIENTATIONS.get(orientation, ORIENTATIONS["landscape"])
    w, h = _dims_for_preset(base_w, base_h, preset)
    fps = int(RENDER_PRESETS.get(preset, RENDER_PRESETS["balanced"])["fps"])
    return w, h, fps


def estimate_encode_wall_seconds(
    output_duration: float,
    preset_name: str,
    target_w: int,
    target_h: int,
    fps: int,
    scenes: list[dict],
) -> float:
    """
    Heuristic wall-clock encode time (seconds). Tuned for typical laptops; actual time varies.
    """
    cfg = RENDER_PRESETS.get(preset_name, RENDER_PRESETS["balanced"])
    ref_pixels = 1920 * 1080 * 24
    pixels_rate = (max(1, target_w) * max(1, target_h) * max(1, fps)) / ref_pixels
    motion = 1.0
    for s in scenes:
        if s.get("media_type", "image") == "image" and s.get("animation", "ken_burns") not in (
            "none",
            None,
        ):
            motion = max(motion, 1.28)

    if scenes_eligible_for_ffmpeg(scenes) and ffmpeg_available():
        ff_fac = float(cfg.get("ffmpeg_encode_factor", 0.1))
        base = 3.0 + output_duration * ff_fac * pixels_rate * motion + 2.5 * len(scenes)
        return max(6.0, base)

    base = 6.0 + output_duration * cfg["encode_factor"] * pixels_rate * motion
    return max(8.0, base)


# ── Animation Helpers ─────────────────────────────────────────────────────

def _apply_animation(
    clip, animation: str, target_w: int, target_h: int, oversample: float = 1.15
):
    """Apply a motion animation to an image clip. The clip is slightly
    oversized so the motion doesn't reveal edges, then cropped back."""
    if animation == "none" or clip is None:
        return clip

    duration = clip.duration
    scale = oversample

    ow = int(target_w * scale)
    oh = int(target_h * scale)
    clip = clip.resized((ow, oh))

    # MoviePy v2 transform() expects func(get_frame, t) -> numpy frame
    from PIL import Image as PILImage

    if animation == "zoom_in":
        def _zoom_in(get_frame, t):
            progress = t / max(duration, 0.01)
            z = 1.0 + 0.12 * progress
            frame = get_frame(t)
            h, w = frame.shape[:2]
            nw, nh = int(w / z), int(h / z)
            x1, y1 = (w - nw) // 2, (h - nh) // 2
            cropped = frame[y1:y1+nh, x1:x1+nw]
            return np.array(PILImage.fromarray(cropped).resize((target_w, target_h), PILImage.BILINEAR))
        clip = clip.transform(_zoom_in, keep_duration=True)

    elif animation == "zoom_out":
        def _zoom_out(get_frame, t):
            progress = t / max(duration, 0.01)
            z = 1.12 - 0.12 * progress
            frame = get_frame(t)
            h, w = frame.shape[:2]
            nw, nh = int(w / z), int(h / z)
            x1, y1 = (w - nw) // 2, (h - nh) // 2
            cropped = frame[y1:y1+nh, x1:x1+nw]
            return np.array(PILImage.fromarray(cropped).resize((target_w, target_h), PILImage.BILINEAR))
        clip = clip.transform(_zoom_out, keep_duration=True)

    elif animation == "pan_left":
        def _pan_left(get_frame, t):
            progress = t / max(duration, 0.01)
            frame = get_frame(t)
            h, w = frame.shape[:2]
            max_off = w - target_w
            x1 = int(max_off * (1 - progress))
            cropped = frame[0:target_h, x1:x1+target_w]
            if cropped.shape[1] < target_w or cropped.shape[0] < target_h:
                return np.array(PILImage.fromarray(frame).resize((target_w, target_h), PILImage.BILINEAR))
            return cropped
        clip = clip.transform(_pan_left, keep_duration=True)

    elif animation == "pan_right":
        def _pan_right(get_frame, t):
            progress = t / max(duration, 0.01)
            frame = get_frame(t)
            h, w = frame.shape[:2]
            max_off = w - target_w
            x1 = int(max_off * progress)
            cropped = frame[0:target_h, x1:x1+target_w]
            if cropped.shape[1] < target_w or cropped.shape[0] < target_h:
                return np.array(PILImage.fromarray(frame).resize((target_w, target_h), PILImage.BILINEAR))
            return cropped
        clip = clip.transform(_pan_right, keep_duration=True)

    elif animation == "pan_up":
        def _pan_up(get_frame, t):
            progress = t / max(duration, 0.01)
            frame = get_frame(t)
            h, w = frame.shape[:2]
            max_off = h - target_h
            y1 = int(max_off * (1 - progress))
            cropped = frame[y1:y1+target_h, 0:target_w]
            if cropped.shape[1] < target_w or cropped.shape[0] < target_h:
                return np.array(PILImage.fromarray(frame).resize((target_w, target_h), PILImage.BILINEAR))
            return cropped
        clip = clip.transform(_pan_up, keep_duration=True)

    elif animation == "pan_down":
        def _pan_down(get_frame, t):
            progress = t / max(duration, 0.01)
            frame = get_frame(t)
            h, w = frame.shape[:2]
            max_off = h - target_h
            y1 = int(max_off * progress)
            cropped = frame[y1:y1+target_h, 0:target_w]
            if cropped.shape[1] < target_w or cropped.shape[0] < target_h:
                return np.array(PILImage.fromarray(frame).resize((target_w, target_h), PILImage.BILINEAR))
            return cropped
        clip = clip.transform(_pan_down, keep_duration=True)

    elif animation == "ken_burns":
        def _ken_burns(get_frame, t):
            progress = t / max(duration, 0.01)
            z = 1.0 + 0.08 * progress
            x_drift = 0.02 * progress
            frame = get_frame(t)
            h, w = frame.shape[:2]
            nw, nh = int(w / z), int(h / z)
            x_off = int((w - nw) * (0.5 + x_drift))
            y_off = (h - nh) // 2
            cropped = frame[y_off:y_off+nh, x_off:x_off+nw]
            return np.array(PILImage.fromarray(cropped).resize((target_w, target_h), PILImage.BILINEAR))
        clip = clip.transform(_ken_burns, keep_duration=True)

    # Final safety resize
    clip = clip.resized((target_w, target_h))
    return clip


# Helper: robust text measurement (Pillow compatibility)
def _text_size(draw_obj, text, font_obj):
    try:
        return draw_obj.textsize(text, font=font_obj)
    except Exception:
        try:
            bbox = draw_obj.textbbox((0, 0), text, font=font_obj)
            return (bbox[2] - bbox[0], bbox[3] - bbox[1])
        except Exception:
            try:
                return font_obj.getsize(text)
            except Exception:
                return (len(text) * (getattr(font_obj, "size", 16) // 2), getattr(font_obj, "size", 16))


def _make_subtitle_clip(text: str, target_w: int, duration: float, font_size: int = 36):
    """Render subtitles into a transparent ImageClip using PIL and return an ImageClip sized to target_w."""
    from PIL import Image as PILImage, ImageDraw, ImageFont

    # Try to load a reasonable system font, fallback to default
    font = None
    for fpath in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            font = ImageFont.truetype(fpath, size=font_size)
            break
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()

    # Prepare a drawing surface to measure text
    measure_img = PILImage.new("RGBA", (target_w, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(measure_img)
    max_w = int(target_w * 0.9)

    # Simple word-wrap
    words = str(text).split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        tw, th = _text_size(draw, test, font)
        if tw <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    # Height calculations
    line_heights = [_text_size(draw, l, font)[1] for l in lines] or [font_size]
    padding = 12
    gap = 6
    total_h = sum(line_heights) + (len(lines) - 1) * gap + padding * 2

    # Create subtitle image
    img = PILImage.new("RGBA", (target_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = int(target_w * 0.05)

    # Draw lines centered
    y = padding
    for i, line in enumerate(lines):
        tw, th = _text_size(draw, line, font)
        x = (target_w - tw) // 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += th + gap

    arr = np.array(img)
    clip = ImageClip(arr).with_duration(duration).with_position(("center", "bottom"))
    return clip


# ── Scene Builder ─────────────────────────────────────────────────────────

def build_scene_clip(
    scene: dict, target_w: int, target_h: int, oversample: float = 1.15
) -> object:
    """
    Build a single scene clip from a scene dictionary.

    Args:
        scene (dict): A dictionary containing:
            - 'media_path': Path to the image or video file.
            - 'audio_path': Path to the audio (voiceover) MP3, or None.
            - 'media_type': 'image' or 'video'.
            - 'animation': Animation name (for images). Default 'ken_burns'.
            - 'duration': Optional forced duration in seconds (used when no audio).
            - 'volume': Audio volume 0.0–2.0. Default 1.0.
            - 'mute_audio': If True, no audio is attached.
        target_w (int): Target width.
        target_h (int): Target height.

    Returns:
        A moviepy clip for the scene with audio attached.
    """
    mute_audio = scene.get("mute_audio", False)
    volume = float(scene.get("volume", 1.0))
    audio = None
    duration = scene.get("duration", 5.0)  # default 5s if no audio

    audio_path = scene.get("audio_path")
    if audio_path and os.path.exists(audio_path) and not mute_audio:
        audio = AudioFileClip(audio_path)
        duration = audio.duration
        if volume != 1.0:
            audio = audio.with_effects([vfx.MultiplyVolume(volume)])

    media_path = scene["media_path"]
    media_type = scene.get("media_type", "image")
    animation = scene.get("animation", "ken_burns")

    if media_type == "video":
        clip = VideoFileClip(media_path)
        if clip.duration < duration:
            clip = clip.with_effects([vfx.Loop(duration=duration)])
        else:
            clip = clip.subclipped(0, duration)
        clip = clip.resized((target_w, target_h))
    else:
        clip = (
            ImageClip(media_path)
            .with_duration(duration)
        )
        clip = _apply_animation(clip, animation, target_w, target_h, oversample=oversample)

    if audio is not None:
        clip = clip.with_audio(audio)

    # Overlay subtitles when requested
    try:
        if bool(scene.get("show_subtitles")) and scene.get("subtitle"):
                subtext = str(scene.get("subtitle") or "")
                if subtext.strip():
                    orig = clip
                    subclip = _make_subtitle_clip(subtext, target_w, clip.duration)
                    comp = CompositeVideoClip([orig, subclip], size=(target_w, target_h))
                    # Preserve audio from the original clip when compositing
                    if getattr(orig, "audio", None):
                        comp = comp.with_audio(orig.audio)
                    clip = comp.with_duration(orig.duration)
    except Exception:
        # Non-fatal: if subtitle rendering fails, continue without subtitles
        pass

    return clip


# ── Transition Helpers ────────────────────────────────────────────────────

def _apply_transition(clip_a, clip_b, transition: str, trans_dur: float = 0.7):
    """Apply a transition between two clips, returning a composed list."""
    if transition == "none":
        return [clip_a, clip_b]

    if transition == "crossfade":
        clip_b = clip_b.with_effects([vfx.CrossFadeIn(trans_dur)])
        return [clip_a, clip_b]

    if transition == "fade_black":
        clip_a = clip_a.with_effects([vfx.CrossFadeOut(trans_dur)])
        clip_b = clip_b.with_effects([vfx.CrossFadeIn(trans_dur)])
        return [clip_a, clip_b]

    if transition == "slide_left":
        w = clip_b.w
        def slide_pos(t):
            progress = min(t / trans_dur, 1.0) if trans_dur > 0 else 1.0
            return (int(w * (1 - progress)), 0)
        clip_b_sliding = clip_b.with_position(slide_pos).with_start(clip_a.duration - trans_dur)
        composite = CompositeVideoClip([clip_a, clip_b_sliding], size=(clip_a.w, clip_a.h))
        composite = composite.with_duration(clip_a.duration)
        remaining = clip_b.subclipped(trans_dur) if clip_b.duration > trans_dur else None
        if remaining:
            return [composite, remaining]
        return [composite]

    if transition == "slide_right":
        w = clip_b.w
        def slide_pos(t):
            progress = min(t / trans_dur, 1.0) if trans_dur > 0 else 1.0
            return (int(-w * (1 - progress)), 0)
        clip_b_sliding = clip_b.with_position(slide_pos).with_start(clip_a.duration - trans_dur)
        composite = CompositeVideoClip([clip_a, clip_b_sliding], size=(clip_a.w, clip_a.h))
        composite = composite.with_duration(clip_a.duration)
        remaining = clip_b.subclipped(trans_dur) if clip_b.duration > trans_dur else None
        if remaining:
            return [composite, remaining]
        return [composite]

    if transition == "wipe_down":
        clip_b = clip_b.with_effects([vfx.CrossFadeIn(trans_dur)])
        return [clip_a, clip_b]

    # Fallback: crossfade
    clip_b = clip_b.with_effects([vfx.CrossFadeIn(trans_dur)])
    return [clip_a, clip_b]


# ── Main Render Function ─────────────────────────────────────────────────

def render_video(
    scenes: list[dict],
    output_path: str,
    orientation: str = "landscape",
    fps: int | None = None,
    progress_callback=None,
    preset: str = "balanced",
    use_hw_accel: bool = False,
    logo_path: str | None = None,
    logo_position: str = "bottom-right",
) -> str:
    """
    Render the full explainer video from a list of scenes.

    Args:
        scenes (list[dict]): Scene dicts with keys:
            - 'media_path', 'audio_path', 'media_type'
            - 'animation' (str), 'transition' (str)
            - 'volume' (float 0.0-2.0), 'mute_audio' (bool)
        output_path (str): Where to write the final MP4 file.
        orientation (str): 'landscape' or 'portrait'.
        fps (int | None): Override frames per second; default comes from `preset`.
        progress_callback: Optional callable(percent: int 0–100).
        preset (str): 'fast' | 'balanced' | 'high' — resolution, fps, and encoder settings.

    Still-image scenes use **FFmpeg** (much faster) when `ffmpeg` is on PATH; video clips
    or failures fall back to MoviePy.

    Returns:
        str: Path to the rendered video file.
    """
    if not scenes:
        raise ValueError("At least one scene is required to render a video.")

    pconf = RENDER_PRESETS.get(preset, RENDER_PRESETS["balanced"])
    base_w, base_h = ORIENTATIONS.get(orientation, ORIENTATIONS["landscape"])
    target_w, target_h = _dims_for_preset(base_w, base_h, preset)
    eff_fps = int(fps if fps is not None else pconf["fps"])

    if scenes_eligible_for_ffmpeg(scenes) and ffmpeg_available():
        try:
            if progress_callback:
                progress_callback(1)
            return render_with_ffmpeg(
                scenes,
                output_path,
                target_w,
                target_h,
                eff_fps,
                pconf,
                progress_callback,
                use_hw_accel=use_hw_accel,
                hw_encoder=None,
                logo_path=logo_path,
                logo_position=logo_position,
            )
        except Exception:
            pass
    oversample = float(pconf["oversample"])
    thread_n = min(16, max(2, (os.cpu_count() or 4) * 2))

    if progress_callback:
        progress_callback(2)

    # Build all scene clips
    clips = []
    n = len(scenes)
    for i, scene in enumerate(scenes):
        clip = build_scene_clip(scene, target_w, target_h, oversample=oversample)
        clips.append(clip)
        if progress_callback:
            progress_callback(2 + int((i + 1) / n * 33))

    if progress_callback:
        progress_callback(36)

    # Apply transitions
    trans_dur = 0.7
    if len(clips) == 1:
        final = clips[0]
    else:
        composed = [clips[0]]
        need_negative_padding = False
        for i in range(1, len(clips)):
            transition = scenes[i].get("transition", "crossfade")
            prev = composed[-1]
            curr = clips[i]
            if transition == "none":
                composed.append(curr)
            elif transition in ("slide_left", "slide_right", "wipe_down"):
                parts = _apply_transition(prev, curr, transition, trans_dur)
                # replace last with the first returned part and append any remaining parts
                composed[-1] = parts[0]
                if len(parts) > 1:
                    composed.extend(parts[1:])
            else:
                # Use crossfade style (works for crossfade, fade_black and other simple fades)
                need_negative_padding = True
                prev = prev.with_effects([vfx.CrossFadeOut(trans_dur)])
                curr = curr.with_effects([vfx.CrossFadeIn(trans_dur)])
                composed[-1] = prev
                composed.append(curr)

        final = concatenate_videoclips(
            composed,
            method="compose",
            padding=-trans_dur if need_negative_padding else 0,
        )

    if progress_callback:
        progress_callback(36)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    ffmpeg_params = list(pconf.get("ffmpeg_params") or [])
    ffmpeg_params = [x for x in ffmpeg_params if x is not None]
    crf = str(pconf.get("crf", "23"))
    ffmpeg_params = ["-crf", crf] + ffmpeg_params

    vid_logger = _WriteProgressLogger(progress_callback) if progress_callback else None

    # MoviePy: overlay logo when ffmpeg path isn't used
    if logo_path and os.path.isfile(logo_path):
        try:
            logo_clip = ImageClip(logo_path).with_duration(final.duration)
            # Scale logo if it's too wide
            max_logo_w = int(final.w * 0.18)
            if getattr(logo_clip, "w", 0) > max_logo_w:
                logo_clip = logo_clip.resized(width=max_logo_w)

            def _pos_for(position: str):
                if position == "bottom-right":
                    return lambda t: (final.w - logo_clip.w - 10, final.h - logo_clip.h - 10)
                if position == "bottom-left":
                    return lambda t: (10, final.h - logo_clip.h - 10)
                if position == "top-left":
                    return lambda t: (10, 10)
                if position == "top-right":
                    return lambda t: (final.w - logo_clip.w - 10, 10)
                if position == "center":
                    return lambda t: ((final.w - logo_clip.w) // 2, (final.h - logo_clip.h) // 2)
                return lambda t: (final.w - logo_clip.w - 10, final.h - logo_clip.h - 10)

            pos_fn = _pos_for(logo_position)
            comp = CompositeVideoClip([final, logo_clip.with_position(pos_fn)], size=(final.w, final.h))
            if getattr(final, "audio", None):
                comp = comp.with_audio(final.audio)
            final = comp
        except Exception:
            logging.exception("Failed to overlay logo via MoviePy")

    final.write_videofile(
        output_path,
        fps=eff_fps,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate=pconf.get("audio_bitrate", "192k"),
        threads=thread_n,
        preset=pconf["preset"],
        bitrate=None,
        ffmpeg_params=ffmpeg_params,
        logger=vid_logger if vid_logger is not None else "bar",
    )

    if progress_callback:
        progress_callback(98)

    # Clean up
    for clip in clips:
        try:
            clip.close()
        except Exception:
            pass
    try:
        final.close()
    except Exception:
        pass

    if progress_callback:
        progress_callback(100)

    return output_path
