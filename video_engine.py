import os
import numpy as np
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


# ── Animation Helpers ─────────────────────────────────────────────────────

def _apply_animation(clip, animation: str, target_w: int, target_h: int):
    """Apply a motion animation to an image clip. The clip is slightly
    oversized so the motion doesn't reveal edges, then cropped back."""
    if animation == "none" or clip is None:
        return clip

    duration = clip.duration
    # Oversample factor so panning/zooming doesn't show black edges
    scale = 1.15

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


# ── Scene Builder ─────────────────────────────────────────────────────────

def build_scene_clip(scene: dict, target_w: int, target_h: int) -> object:
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
        clip = _apply_animation(clip, animation, target_w, target_h)

    if audio is not None:
        clip = clip.with_audio(audio)

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
    fps: int = 24,
    progress_callback=None,
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
        fps (int): Frames per second.
        progress_callback: Optional callable(percent: int).

    Returns:
        str: Path to the rendered video file.
    """
    if not scenes:
        raise ValueError("At least one scene is required to render a video.")

    target_w, target_h = ORIENTATIONS.get(orientation, ORIENTATIONS["landscape"])

    if progress_callback:
        progress_callback(5)

    # Build all scene clips
    clips = []
    for i, scene in enumerate(scenes):
        clip = build_scene_clip(scene, target_w, target_h)
        clips.append(clip)
        if progress_callback:
            progress_callback(5 + int((i + 1) / len(scenes) * 35))

    if progress_callback:
        progress_callback(40)

    # Apply transitions
    trans_dur = 0.7
    if len(clips) == 1:
        final = clips[0]
    else:
        composed = [clips[0]]
        for i in range(1, len(clips)):
            transition = scenes[i].get("transition", "crossfade")
            if transition == "none":
                composed.append(clips[i])
            else:
                clips[i] = clips[i].with_effects([vfx.CrossFadeIn(trans_dur)])
                composed.append(clips[i])

        final = concatenate_videoclips(
            composed, method="compose",
            padding=-trans_dur if any(s.get("transition", "crossfade") != "none" for s in scenes[1:]) else 0
        )

    if progress_callback:
        progress_callback(50)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    final.write_videofile(
        output_path,
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        threads=8,  # Increased threads to accelerate rendering
        preset="ultrafast",  # Massive encoding speed boost
        bitrate="5000k",
    )

    if progress_callback:
        progress_callback(95)

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
