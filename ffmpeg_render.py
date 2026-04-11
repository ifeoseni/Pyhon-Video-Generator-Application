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
import logging
import concurrent.futures
import urllib.parse
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


def _detect_hw_encoder() -> Optional[str]:
    """Try to detect a reasonable hardware h264 encoder available to ffmpeg."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=4)
        text = (out.stdout or "") + (out.stderr or "")
        t = text.lower()
        # Common encoders (prefer nvenc -> qsv -> vaapi -> amf -> videotoolbox)
        candidates = [
            "h264_nvenc",
            "hevc_nvenc",
            "h264_qsv",
            "h264_vaapi",
            "h264_amf",
            "h264_videotoolbox",
        ]
        for c in candidates:
            if c in t:
                return c
    except Exception:
        pass
    return None


DEFAULT_HW_ENCODER = _detect_hw_encoder()


def scenes_eligible_for_ffmpeg(scenes: list[dict]) -> bool:
    """Return True if all scenes are simple still-image scenes suitable for ffmpeg path."""
    if not scenes:
        return False
    for s in scenes:
        mt = s.get("media_type", "image")
        # allow either explicit 'image' or missing media_type
        if mt not in ("image", "img", "photo"):
            return False
    return True


def _even(x: int) -> int:
    x = int(x)
    return x + (x % 2)


def _build_motion_filter(animation: str, w: int, h: int, fps: int, nframes: int) -> str:
    """Return a simple ffmpeg filter that scales the image and trims to duration.

    For now this produces a static scaled image clip. More sophisticated
    zoom/pan can be added later.
    """
    dur = max(0.01, nframes / max(1, fps))
    # scale to exact resolution and label as [v]
    vf = f"[0:v]scale={w}:{h},format=yuv420p,setsar=1,trim=duration={dur},setpts=PTS-STARTPTS[v]"
    return vf


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
    video_encoder: Optional[str] = None,
) -> None:
    w, h = _even(w), _even(h)
    nframes = max(1, int(round(duration * fps)))
    vf_motion = _build_motion_filter(animation, w, h, fps, nframes)

    if mute or not audio_path or not os.path.isfile(audio_path):
        dur_s = f"{max(0.04, duration):.6f}"
        enc = video_encoder or "libx264"
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
            enc,
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
        enc = video_encoder or "libx264"
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
            enc,
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
    if r.returncode != 0 and video_encoder is not None:
        logging.warning("Hardware encoder %s failed for %s, falling back to libx264", video_encoder, image_path)
        enc2 = "libx264"
        cmd2 = [str(x) for x in cmd]
        try:
            for i, v in enumerate(cmd2):
                if v == video_encoder:
                    cmd2[i] = enc2
                    break
        except Exception:
            pass
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=max(300, int(duration * 30) + 120))
        if r2.returncode != 0:
            err = (r2.stderr or r2.stdout or "")[-4000:]
            raise RuntimeError(f"FFmpeg scene encode failed after fallback: {err}")
        return
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
    video_encoder: Optional[str] = None,
    logo_path: Optional[str] = None,
    logo_position: str = "bottom-right",
) -> None:
    """Merge per-scene segments (already encoded) into a final MP4.

    Supports optional subtitle burn-in per scene (scene['subtitle'] / scene['show_subtitles'])
    and an optional logo overlay.
    """
    n = len(scene_files)
    if n == 0:
        raise ValueError("No scene files to merge")

    # Single segment: optionally overlay logo and/or draw subtitle
    if n == 1:
        if logo_path and os.path.isfile(logo_path):
            cmd = ["ffmpeg", "-y", "-i", scene_files[0], "-i", logo_path]
            x, y = {
                "bottom-right": ("main_w-overlay_w-10", "main_h-overlay_h-10"),
                "bottom-left": ("10", "main_h-overlay_h-10"),
                "top-left": ("10", "10"),
                "top-right": ("main_w-overlay_w-10", "10"),
                "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
            }.get(logo_position, ("main_w-overlay_w-10", "main_h-overlay_h-10"))
            fc = f"[0:v][1:v]overlay={x}:{y}[vout]"
            enc = video_encoder or "libx264"
            cmd.extend([
                "-filter_complex",
                fc,
                "-map",
                "[vout]",
                "-map",
                "0:a",
                "-c:v",
                enc,
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
            ])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
            if r.returncode != 0 and video_encoder is not None:
                logging.warning("Single-segment merge with hw encoder %s failed, retrying with libx264", video_encoder)
                cmd2 = [str(x) for x in cmd]
                try:
                    for i, v in enumerate(cmd2):
                        if v == video_encoder:
                            cmd2[i] = "libx264"
                            break
                except Exception:
                    pass
                r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=7200)
                if r2.returncode != 0:
                    err = (r2.stderr or r2.stdout or "")[-4000:]
                    raise RuntimeError(f"FFmpeg merge failed after fallback: {err}")
                return
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "")[-4000:]
                raise RuntimeError(f"FFmpeg merge failed: {err}")
            return
        else:
            shutil.copy2(scene_files[0], output_path)
            return

    # Build concat/xfade filter chain
    cmd = ["ffmpeg", "-y"]
    for p in scene_files:
        cmd.extend(["-i", p])

    if logo_path and os.path.isfile(logo_path):
        cmd.extend(["-i", logo_path])
        logo_idx = n
    else:
        logo_idx = None

    parts: list[str] = []
    v_out, a_out = "0:v", "0:a"
    cum = durations[0]
    start_times = [0.0] * n

    # Compute start times for subtitles/enable expressions
    for i in range(1, n):
        trans = (scenes[i].get("transition") or "crossfade").lower()
        if trans == "none":
            start_times[i] = cum
            cum += durations[i]
        else:
            start_times[i] = max(0.0, cum - trans_dur)
            cum += durations[i] - trans_dur

    # Build xfade/concat parts while keeping track of labels
    v_out, a_out = "0:v", "0:a"
    cum = durations[0]
    for i in range(1, n):
        vi, ai = f"{i}:v", f"{i}:a"
        trans = (scenes[i].get("transition") or "crossfade").lower()
        if trans == "none":
            parts.append(f"[{v_out}][{a_out}][{vi}][{ai}]concat=n=2:v=1:a=1[v{i}c][a{i}c]")
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

    # Append subtitle drawtext filters if present per-scene
    # Chain drawtext filters sequentially so each operates on previous v label
    sub_label = v_out
    sub_idx = 0
    # choose a font if available
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    fontfile = None
    for fp in font_candidates:
        if os.path.isfile(fp):
            fontfile = fp.replace('\\', '/')
            break

    for i in range(n):
        s = scenes[i]
        show = s.get("show_subtitles") or s.get("showSubtitle") or False
        subtitle = s.get("subtitle") or s.get("text") or ""
        if show and subtitle:
            # escape single quotes
            txt = str(subtitle).replace("'", "\\'")
            st = start_times[i]
            et = st + float(durations[i])
            fontsize = max(18, int(min(48, 0.04 * (os.path.getsize(scene_files[i]) if os.path.exists(scene_files[i]) else 100000) ** 0.3)))
            # Reasonable default: 36
            fontsize = 36
            df = []
            df.append(f"text='{txt}'")
            if fontfile:
                df.append(f"fontfile='{fontfile}'")
            df.append(f"fontsize={fontsize}")
            df.append("fontcolor=white")
            df.append("box=1")
            df.append("boxcolor=black@0.6")
            df.append("boxborderw=10")
            df.append("x=(w-text_w)/2")
            df.append("y=h-text_h-60")
            df.append(f"enable='between(t,{st:.3f},{et:.3f})'")
            draw = "drawtext=" + ":".join(df)
            next_label = f"vsub{sub_idx}"
            fc = fc + f";[{sub_label}]{draw}[{next_label}]"
            sub_label = next_label
            sub_idx += 1

    map_v_label = sub_label

    # If logo was provided, append overlay step
    if logo_idx is not None:
        x, y = {
            "bottom-right": ("main_w-overlay_w-10", "main_h-overlay_h-10"),
            "bottom-left": ("10", "main_h-overlay_h-10"),
            "top-left": ("10", "10"),
            "top-right": ("main_w-overlay_w-10", "10"),
            "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
        }.get(logo_position, ("main_w-overlay_w-10", "main_h-overlay_h-10"))
        fc = fc + f";[{map_v_label}][{logo_idx}:v]overlay={x}:{y}[vout]"
        map_v_label = "vout"

    enc = video_encoder or "libx264"
    cmd.extend([
        "-filter_complex",
        fc,
        "-map",
        f"[{map_v_label}]",
        "-map",
        f"[{a_out}]",
        "-c:v",
        enc,
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
    ])

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if r.returncode != 0 and video_encoder is not None:
        logging.warning("Merge with hardware encoder %s failed, retrying with libx264", video_encoder)
        cmd2 = [str(x) for x in cmd]
        try:
            for i, v in enumerate(cmd2):
                if v == video_encoder:
                    cmd2[i] = "libx264"
                    break
        except Exception:
            pass
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=7200)
        if r2.returncode != 0:
            err = (r2.stderr or r2.stdout or "")[-4000:]
            raise RuntimeError(f"FFmpeg merge failed after fallback: {err}")
        return
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
    use_hw_accel: bool = False,
    hw_encoder: Optional[str] = None,
    logo_path: Optional[str] = None,
    logo_position: str = "bottom-right",
) -> str:
    """
    Full render: per-scene FFmpeg encode, then xfade/concat merge.
    """
    if not scenes_eligible_for_ffmpeg(scenes):
        raise ValueError("FFmpeg renderer only supports image scenes.")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cpu = os.cpu_count() or 4
    n = len(scenes)
    concurrency = min(n, max(1, cpu // 2))
    threads_per_process = max(1, cpu // max(1, concurrency))

    enc_preset = str(pconf.get("preset", "veryfast"))
    crf = str(pconf.get("crf", "23"))
    audio_br = str(pconf.get("audio_bitrate", "192k"))
    trans_dur = 0.7
    tmp = tempfile.mkdtemp(prefix="explainer_ffmpeg_")
    scene_files: list[str] = [None] * n
    durations: list[float] = [0.0] * n

    video_encoder: Optional[str] = None
    if use_hw_accel:
        video_encoder = hw_encoder or DEFAULT_HW_ENCODER

    try:
        futures = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as exc:
            for i, s in enumerate(scenes):
                img = s["media_path"]
                mute = s.get("mute_audio", False)
                ap = s.get("audio_path")
                dur = float(s.get("duration", 5.0))
                vol = float(s.get("volume", 1.0))
                anim = s.get("animation", "ken_burns")

                out_seg = os.path.join(tmp, f"seg_{i:04d}.mp4")
                scene_files[i] = out_seg
                durations[i] = dur

                fut = exc.submit(
                    _encode_scene,
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
                    threads_per_process,
                    video_encoder,
                )
                futures[fut] = i

            completed = 0
            for fut in concurrent.futures.as_completed(futures):
                idx = futures[fut]
                try:
                    fut.result()
                except Exception:
                    logging.exception("FFmpeg scene encode failed for segment %s", idx)
                    raise
                completed += 1
                if progress_callback:
                    progress_callback(5 + int(75 * (completed) / n))

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
            threads_per_process,
            durations,
            video_encoder,
            logo_path,
            logo_position,
        )

        if progress_callback:
            progress_callback(100)

        return output_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
