"""
Fast video assembly using FFmpeg (no per-frame Python compositing).

Used when every scene is a still image + optional audio. Falls back to MoviePy
if FFmpeg is missing or an error occurs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

# xfade transition names supported by libavfilter
_XFADE_TRANSITION = {
    "crossfade": "fade",
    "fade_black": "fade",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "wipe_down": "wipedown",
}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def scenes_eligible_for_ffmpeg(scenes: list[dict]) -> bool:
    return bool(scenes) and all(
        s.get("media_type", "image") == "image" for s in scenes
    )


def _even(n: int) -> int:
    return n if n % 2 == 0 else n + 1


def _build_motion_filter(
    animation: str,
    w: int,
    h: int,
    fps: int,
    nframes: int,
) -> str:
    """
    Video filter after decoded image: scale+pad to WxH, optional zoompan.
    Input label [0:v], output [v].
    """
    w, h = _even(w), _even(h)
    base = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    )
    anim = (animation or "none").lower()
    if anim in ("none", ""):
        return f"[0:v]{base},format=yuv420p[v]"

    bw = _even(int(w * 1.18))
    bh = _even(int(h * 1.18))
    pre = f"[0:v]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh}:(iw-ow)/2:(ih-oh)/2"
    d = max(1, nframes)
    dm = max(1, d - 1)

    if anim == "ken_burns":
        z = f"1+0.08*on/{dm}"
        x = f"iw/2-(iw/zoom/2)+0.02*iw*on/{dm}"
        y = f"ih/2-(ih/zoom/2)"
    elif anim == "zoom_in":
        z = f"1+0.12*on/{dm}"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif anim == "zoom_out":
        z = f"1.12-0.12*on/{dm}"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif anim == "pan_left":
        z = "1"
        x = f"(iw-ow)*on/{dm}"
        y = f"(ih-oh)/2"
    elif anim == "pan_right":
        z = "1"
        x = f"(iw-ow)*(1-on/{dm})"
        y = f"(ih-oh)/2"
    elif anim == "pan_up":
        z = "1"
        x = f"(iw-ow)/2"
        y = f"(ih-oh)*on/{dm}"
    elif anim == "pan_down":
        z = "1"
        x = f"(iw-ow)/2"
        y = f"(ih-oh)*(1-on/{dm})"
    else:
        return f"[0:v]{base},format=yuv420p[v]"

    zp = (
        f"{pre},zoompan=z='{z}':x='{x}':y='{y}':d={d}:s={w}x{h}:fps={fps},"
        f"format=yuv420p[v]"
    )
    return zp


def _encode_scene(
    image_path: str,
    audio_path: Optional[str],
    duration: float,
    mute: bool,
    volume: float,
    animation: str,
    w: int,
    h: int,
    fps: int,
    out_mp4: str,
    preset: str,
    crf: str,
    audio_bitrate: str,
    threads: int,
) -> None:
    w, h = _even(w), _even(h)
    nframes = max(1, int(round(duration * fps)))
    vf_motion = _build_motion_filter(animation, w, h, fps, nframes)

    if mute or not audio_path or not os.path.isfile(audio_path):
        # Silent audio for exact duration
        dur_s = f"{max(0.04, duration):.6f}"
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            image_path,
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=stereo,atrim=0:{dur_s},asetpts=N/SR/TB",
            "-filter_complex",
            f"{vf_motion};[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=44100[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            crf,
            "-tune",
            "stillimage",
            "-threads",
            str(threads),
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
    else:
        vol = max(0.0, min(3.0, float(volume)))
        af = f"[1:a]volume={vol},aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=44100[a]"
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            image_path,
            "-i",
            audio_path,
            "-filter_complex",
            f"{vf_motion};{af}",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            crf,
            "-tune",
            "stillimage",
            "-threads",
            str(threads),
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
    cmd.append(out_mp4)
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(300, int(duration * 30) + 120),
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[-4000:]
        raise RuntimeError(f"FFmpeg scene encode failed: {err}")


def _merge_scenes(
    scene_files: list[str],
    scenes: list[dict],
    output_path: str,
    trans_dur: float,
    preset: str,
    crf: str,
    audio_bitrate: str,
    threads: int,
    durations: list[float],
) -> None:
    n = len(scene_files)
    if n == 1:
        shutil.copy2(scene_files[0], output_path)
        return

    cmd = ["ffmpeg", "-y"]
    for p in scene_files:
        cmd.extend(["-i", p])

    parts: list[str] = []
    v_out, a_out = "0:v", "0:a"
    cum = durations[0]

    for i in range(1, n):
        vi, ai = f"{i}:v", f"{i}:a"
        trans = (scenes[i].get("transition") or "crossfade").lower()
        if trans == "none":
            parts.append(
                f"[{v_out}][{a_out}][{vi}][{ai}]concat=n=2:v=1:a=1[v{i}c][a{i}c]"
            )
            v_out, a_out = f"v{i}c", f"a{i}c"
            cum += durations[i]
        else:
            tr = _XFADE_TRANSITION.get(trans, "fade")
            off = max(0.0, cum - trans_dur)
            parts.append(
                f"[{v_out}][{vi}]xfade=transition={tr}:duration={trans_dur}:offset={off}[v{i}x];"
                f"[{a_out}][{ai}]acrossfade=d={trans_dur}[a{i}x]"
            )
            v_out, a_out = f"v{i}x", f"a{i}x"
            cum += durations[i] - trans_dur

    fc = ";".join(parts)
    cmd.extend(
        [
            "-filter_complex",
            fc,
            "-map",
            f"[{v_out}]",
            "-map",
            f"[{a_out}]",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            crf,
            "-threads",
            str(threads),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            output_path,
        ]
    )
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[-4000:]
        raise RuntimeError(f"FFmpeg merge failed: {err}")


def render_with_ffmpeg(
    scenes: list[dict],
    output_path: str,
    target_w: int,
    target_h: int,
    fps: int,
    pconf: dict,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> str:
    """
    Full render: per-scene FFmpeg encode, then xfade/concat merge.
    """
    if not scenes_eligible_for_ffmpeg(scenes):
        raise ValueError("FFmpeg renderer only supports image scenes.")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    thread_n = min(16, max(2, (os.cpu_count() or 4) * 2))
    enc_preset = str(pconf.get("preset", "veryfast"))
    crf = str(pconf.get("crf", "23"))
    audio_br = str(pconf.get("audio_bitrate", "192k"))
    trans_dur = 0.7
    tmp = tempfile.mkdtemp(prefix="explainer_ffmpeg_")
    scene_files: list[str] = []
    durations: list[float] = []

    try:
        n = len(scenes)
        for i, s in enumerate(scenes):
            img = s["media_path"]
            mute = s.get("mute_audio", False)
            ap = s.get("audio_path")
            dur = float(s.get("duration", 5.0))
            vol = float(s.get("volume", 1.0))
            anim = s.get("animation", "ken_burns")

            out_seg = os.path.join(tmp, f"seg_{i:04d}.mp4")
            _encode_scene(
                img,
                ap if ap and os.path.isfile(str(ap)) else None,
                dur,
                mute,
                vol,
                anim,
                target_w,
                target_h,
                fps,
                out_seg,
                enc_preset,
                crf,
                audio_br,
                thread_n,
            )
            scene_files.append(out_seg)
            durations.append(dur)

            if progress_callback:
                progress_callback(5 + int(75 * (i + 1) / n))

        if progress_callback:
            progress_callback(80)

        _merge_scenes(
            scene_files,
            scenes,
            output_path,
            trans_dur,
            enc_preset,
            crf,
            audio_br,
            thread_n,
            durations,
        )

        if progress_callback:
            progress_callback(100)

        return output_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
