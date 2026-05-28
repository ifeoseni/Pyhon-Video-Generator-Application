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

# Try to discover ffmpeg from imageio_ffmpeg if not already present on PATH
if shutil.which("ffmpeg") is None:
    try:
        import imageio_ffmpeg
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cache_dir = os.path.join(base_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        target_ffmpeg = os.path.join(cache_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not os.path.exists(target_ffmpeg):
            bin_path = imageio_ffmpeg.get_ffmpeg_exe()
            if bin_path and os.path.exists(bin_path):
                shutil.copy2(bin_path, target_ffmpeg)
        if os.path.exists(target_ffmpeg):
            os.environ["PATH"] = cache_dir + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass

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
    """Return a simple ffmpeg filter that scales the image and trims to duration."""
    dur = max(0.01, nframes / max(1, fps))
    vf = f"[0:v]scale={w}:{h},format=yuv420p,setsar=1,trim=duration={dur},setpts=PTS-STARTPTS[v]"
    return vf


def _erase_gemini_watermark_inplace(image_path: str) -> str:
    """
    Detect and erase the visible Gemini diamond watermark (bottom-right corner)
    by inpainting the bright anomalous region with surrounding pixel values.
    Returns a path to the cleaned image (writes a _dewm copy, leaves original intact).
    """
    import numpy as np
    from PIL import Image as PILImage

    base, ext = os.path.splitext(image_path)
    out_path = base + "_dewm" + (ext or ".jpg")
    if os.path.exists(out_path):
        return out_path
    try:
        img = PILImage.open(image_path).convert("RGB")
        arr = np.array(img, dtype=np.float32)
        h, w = arr.shape[:2]

        rx0 = int(w * 0.85)
        ry0 = int(h * 0.85)
        region = arr[ry0:, rx0:].copy()
        region_gray = region.mean(axis=2)
        region_mean = region_gray.mean()
        region_std = region_gray.std()
        threshold = region_mean + max(20.0, region_std * 1.5)
        mask = region_gray > threshold

        try:
            from scipy.ndimage import binary_dilation
            if mask.any():
                mask = binary_dilation(mask, iterations=4)
            else:
                mask[-80:, -80:] = True
        except ImportError:
            if not mask.any():
                mask[-80:, -80:] = True

        for c in range(3):
            channel = region[:, :, c]
            sample_vals = channel[~mask]
            fill_val = float(np.median(sample_vals)) if sample_vals.size else float(channel.mean())
            channel[mask] = fill_val
            region[:, :, c] = channel

        arr[ry0:, rx0:] = region
        PILImage.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(out_path, format="JPEG", quality=95)
        return out_path
    except Exception:
        return image_path


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
    subtitle_text: Optional[str] = None,
    show_subtitle: bool = False,
    gemini_source: bool = False,
    audio_start: float = 0.0,
    audio_end: Optional[float] = None,
) -> None:
    # Pre-process: erase visible Gemini watermark before encoding
    if gemini_source:
        image_path = _erase_gemini_watermark_inplace(image_path)

    w, h = _even(w), _even(h)
    nframes = max(1, int(round(duration * fps)))
    vf_motion = _build_motion_filter(animation, w, h, fps, nframes)

    # Optional subtitle burn-in for this segment
    vmap = "[v]"
    if show_subtitle and subtitle_text:
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

        txt = str(subtitle_text).replace("'", "\\'").replace(":", "\\:").replace(",", "\\,")
        df = []
        df.append(f"text='{txt}'")
        if fontfile:
            ff_escaped = fontfile.replace(":", "\\\\:") if os.name == "nt" else fontfile.replace(":", "\\:")
            df.append(f"fontfile={ff_escaped}")
        df.append("fontsize=48")
        df.append("fontcolor=white")
        df.append("box=0")
        df.append("x=(w-text_w)/2")
        df.append("y=h-text_h-60")
        draw = "drawtext=" + ":".join(df)
        vf_motion = vf_motion + f";[v]{draw}[vsub]"
        vmap = "[vsub]"

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
            vmap,
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
        
        # Audio seek & trim parameters
        audio_args = []
        if audio_start > 0.0:
            audio_args.extend(["-ss", f"{audio_start:.6f}"])
        if audio_end is not None:
            audio_args.extend(["-t", f"{duration:.6f}"])

        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            image_path,
        ]
        
        # Insert audio input seeking arguments
        cmd.extend(audio_args)
        cmd.extend(["-i", audio_path])
        
        cmd.extend([
            "-filter_complex",
            f"{vf_motion};{af}",
            "-map",
            vmap,
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
        ])
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
    target_w: int = 1920,
    project_audio_path: Optional[str] = None,
) -> None:
    """Merge per-scene segments (already encoded) into a final MP4.

    Supports optional subtitle burn-in per scene (scene['subtitle'] / scene['show_subtitles'])
    and an optional logo overlay.
    """
    n = len(scene_files)
    if n == 0:
        raise ValueError("No scene files to merge")

    # Single segment: optionally overlay logo and/or burn-in subtitle
    if n == 1:
        s = scenes[0]
        show = s.get("show_subtitles") or s.get("showSubtitle") or False
        subtitle = s.get("subtitle") or s.get("text") or ""

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

        # Build command inputs
        cmd = ["ffmpeg", "-y", "-i", scene_files[0]]
        fc_parts = []
        map_label = "0:v"
        map_audio_label = "0:a"
        audio_idx = 1

        if show and subtitle:
            txt = str(subtitle).replace("'", "\\'").replace(":", "\\:").replace(",", "\\,")
            fontsize = 48
            df = []
            df.append(f"text='{txt}'")
            if fontfile:
                ff_escaped = fontfile.replace(":", "\\\\:") if os.name == "nt" else fontfile.replace(":", "\\:")
                df.append(f"fontfile={ff_escaped}")
            df.append(f"fontsize={fontsize}")
            df.append("fontcolor=white")
            df.append("box=0")
            df.append("x=(w-text_w)/2")
            df.append("y=h-text_h-60")
            draw = "drawtext=" + ":".join(df)
            fc_parts.append(f"[0:v]{draw}[vsub]")
            map_label = "[vsub]"

        if logo_path and os.path.isfile(logo_path):
            # add logo as an extra input
            cmd.extend(["-i", logo_path])
            audio_idx += 1
            x, y = {
                "bottom-right": ("main_w-overlay_w-10", "main_h-overlay_h-10"),
                "bottom-left": ("10", "main_h-overlay_h-10"),
                "top-left": ("10", "10"),
                "top-right": ("main_w-overlay_w-10", "10"),
                "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
            }.get(logo_position, ("main_w-overlay_w-10", "main_h-overlay_h-10"))
            # overlay on top of previous label (or original 0:v)
            src_label = map_label if map_label.startswith("[") else f"{map_label}"
            # ensure proper bracketed labels
            if not src_label.startswith("["):
                src_label = f"[{src_label}]"
            logo_w = int(target_w * 0.18)
            fc_parts.append(f"[1:v]scale={logo_w}:-2[logo_s]")
            fc_parts.append(f"{src_label}[logo_s]overlay={x}:{y}[vout]")
            map_label = "[vout]"

        if project_audio_path and os.path.isfile(project_audio_path):
            cmd.extend(["-i", project_audio_path])
            fc_parts.append(f"[0:a][{audio_idx - 1}:a]amix=inputs=2:duration=first:dropout_transition=3[amix]")
            map_audio_label = "[amix]"

        if not fc_parts:
            # nothing to do — copy
            shutil.copy2(scene_files[0], output_path)
            return

        fc = ";".join(fc_parts)
        enc = video_encoder or "libx264"
        cmd.extend([
            "-filter_complex",
            fc,
            "-map",
            map_label,
            "-map",
            map_audio_label,
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

    # Build concat/xfade filter chain
    cmd = ["ffmpeg", "-y"]
    for p in scene_files:
        cmd.extend(["-i", p])

    if logo_path and os.path.isfile(logo_path):
        cmd.extend(["-i", logo_path])
        logo_idx = n
    else:
        logo_idx = None

    project_audio_idx = None
    if project_audio_path and os.path.isfile(project_audio_path):
        cmd.extend(["-i", project_audio_path])
        project_audio_idx = n + (1 if logo_idx is not None else 0)

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
            # Video xfade with proper duration
            parts.append(
                f"[{v_out}][{vi}]xfade=transition={tr}:duration={trans_dur}:offset={off}[v{i}x]"
            )
            # Audio: concatenate sequentially (no crossfade) to avoid overlap
            parts.append(
                f"[{a_out}][{ai}]concat=n=2:v=0:a=1[a{i}x]"
            )
            v_out, a_out = f"v{i}x", f"a{i}x"
            cum += durations[i] - trans_dur

    fc = ";".join(parts)

    # Subtitles are burned into each per-segment file during encoding (_encode_scene).
    # Skip adding drawtext filters at merge-time to avoid timing/complexity issues.
    map_v_label = v_out
    map_a_label = a_out

    # If logo was provided, append overlay step
    if logo_idx is not None:
        x, y = {
            "bottom-right": ("main_w-overlay_w-10", "main_h-overlay_h-10"),
            "bottom-left": ("10", "main_h-overlay_h-10"),
            "top-left": ("10", "10"),
            "top-right": ("main_w-overlay_w-10", "10"),
            "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
        }.get(logo_position, ("main_w-overlay_w-10", "main_h-overlay_h-10"))
        logo_w = int(target_w * 0.18)
        fc = fc + f";[{logo_idx}:v]scale={logo_w}:-2[logo_s];[{map_v_label}][logo_s]overlay={x}:{y}[vout]"
        map_v_label = "vout"

    if project_audio_idx is not None:
        fc = fc + f";[{map_a_label}][{project_audio_idx}:a]amix=inputs=2:duration=first:dropout_transition=3[a_mix]"
        map_a_label = "a_mix"

    enc = video_encoder or "libx264"
    cmd.extend([
        "-filter_complex",
        fc,
        "-map",
        f"[{map_v_label}]",
        "-map",
        f"[{map_a_label}]",
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
                    s.get("subtitle") or s.get("text") or None,
                    bool(s.get("show_subtitles") or s.get("showSubtitle") or False),
                    bool(s.get("gemini_source", False)),
                    float(s.get("audio_start", 0.0)),
                    s.get("audio_end"),
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
            target_w,
        )

        if progress_callback:
            progress_callback(100)

        return output_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
