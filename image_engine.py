"""
Multi-provider async image generation for scene visuals.

Providers include free/no-key options, free-with-signup APIs, and Google Gemini /
Imagen (Nano Banana family) for higher fidelity when `GEMINI_API_KEY` is set.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import urllib.parse
from io import BytesIO
from typing import Any

import aiofiles
import aiohttp
from PIL import Image, ImageDraw, ImageFont

# Default keeps existing zero-config behaviour; users can pick higher-quality backends in the UI.
DEFAULT_IMAGE_PROVIDER = "pollinations"

# (id, display name, short description, requires_api_key, env_var_names as tuple)
_IMAGE_PROVIDER_META: list[tuple[str, str, str, bool, tuple[str, ...]]] = [
    (
        "pollinations",
        "Pollinations.ai",
        "No API key. Fast URL-based generation; quality can be inconsistent.",
        False,
        (),
    ),
    (
        "stable_horde_anon",
        "Stable Horde (Anonymous)",
        "No API key required (uses '0000000000'). Crowdsourced SD; can be slow.",
        False,
        (),
    ),
    (
        "stable_horde",
        "Stable Horde (with Key)",
        "Free account at stablehorde.net — set STABLE_HORDE_API_KEY for priority.",
        True,
        ("STABLE_HORDE_API_KEY", "AI_HORDE_API_KEY"),
    ),
    (
        "openai",
        "OpenAI (DALL-E 3)",
        "High quality native OpenAI model. Requires OPENAI_API_KEY.",
        True,
        ("OPENAI_API_KEY",),
    ),
    (
        "together",
        "Together AI (Flux / SDXL)",
        "Fast open-source models. Get a key at together.ai (TOGETHER_API_KEY).",
        True,
        ("TOGETHER_API_KEY",),
    ),
    (
        "huggingface_flux",
        "Hugging Face (FLUX.1 Schnell)",
        "Free inference tier — create a token at huggingface.co/settings/tokens (HF_TOKEN).",
        True,
        ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"),
    ),
    (
        "deepai",
        "DeepAI (text2img)",
        "Simple hosted model — free API key at deepai.org (DEEPAI_API_KEY).",
        True,
        ("DEEPAI_API_KEY",),
    ),
    (
        "gemini_nano_banana",
        "Gemini · Nano Banana (2.5 Flash Image)",
        "Google native image model — needs GEMINI_API_KEY or GOOGLE_API_KEY (AI Studio).",
        True,
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    ),
    (
        "gemini_nano_banana_2",
        "Gemini · Nano Banana 2 (3.1 Flash Image Preview)",
        "Faster Nano Banana variant for high-volume use — same Google API key.",
        True,
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    ),
    (
        "gemini_nano_banana_pro",
        "Gemini · Nano Banana Pro (3 Pro Image Preview)",
        "Higher fidelity / complex prompts — same Google API key.",
        True,
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    ),
    (
        "imagen_fast",
        "Google Imagen 4 (fast)",
        "Photoreal Imagen pipeline — same GEMINI_API_KEY / GOOGLE_API_KEY.",
        True,
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    ),
]

_VALID_IDS = {row[0] for row in _IMAGE_PROVIDER_META}


def list_image_providers() -> list[dict[str, Any]]:
    """Metadata for the editor / bulk UI and `/api/image-providers`."""
    out = []
    for pid, name, desc, needs_key, envs in _IMAGE_PROVIDER_META:
        out.append(
            {
                "id": pid,
                "name": name,
                "description": desc,
                "requires_api_key": needs_key,
                "key_env_vars": list(envs),
            }
        )
    return out


def normalize_image_provider(name: str | None) -> str:
    if not name:
        return DEFAULT_IMAGE_PROVIDER
    n = str(name).strip().lower().replace("-", "_")
    if n in _VALID_IDS:
        return n
    return DEFAULT_IMAGE_PROVIDER


def _gemini_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _first_env(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v and str(v).strip():
            return str(v).strip()
    return None


def _save_raw_image_bytes_as_jpeg(raw: bytes, output_path: str) -> None:
    im = Image.open(BytesIO(raw))
    if im.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        if im.mode == "P":
            im = im.convert("RGBA")
        if "A" in im.mode:
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
    elif im.mode != "RGB":
        im = im.convert("RGB")
    im.save(output_path, format="JPEG", quality=92)


def _make_placeholder(prompt: str, output_path: str, width: int, height: int):
    """Create a simple placeholder image with the prompt text (synchronous)."""
    bg = Image.new("RGB", (width, height), color=(30, 30, 40))
    draw = ImageDraw.Draw(bg)

    font = None
    for fpath in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            font = ImageFont.truetype(fpath, size=max(20, width // 40))
            break
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()

    for i in range(height):
        blend = int(20 + 40 * (i / max(1, height)))
        draw.line([(0, i), (width, i)], fill=(blend, blend, blend))

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
                    return (len(text) * (getattr(font_obj, "size", 12) // 2), getattr(font_obj, "size", 12))

    text = prompt or "Generated Image"
    max_w = int(width * 0.9)
    words = text.split()
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

    total_h = sum(_text_size(draw, l, font)[1] for l in lines) + (len(lines) - 1) * 6
    y = int((height - total_h) / 2)
    box_margin = 20
    for line in lines:
        tw, th = _text_size(draw, line, font)
        x = int((width - tw) / 2)
        draw.rectangle([x - box_margin, y - 8, x + tw + box_margin, y + th + 8], fill=(10, 10, 12))
        draw.text((x, y), line, font=font, fill=(240, 240, 245))
        y += th + 6

    bg.save(output_path)


def _horde_grid_dims(width: int, height: int) -> tuple[int, int]:
    """Stable Horde expects multiples of 64; cap longest side for reasonable queue times."""
    max_side = 1024
    scale = min(max_side / max(width, height, 1), 1.0)
    w = int(width * scale)
    h = int(height * scale)
    w = max(64, min(1024, (w // 64) * 64))
    h = max(64, min(1024, (h // 64) * 64))
    return w, h


def _imagen_aspect_ratio(width: int, height: int) -> str:
    r = width / max(height, 1)
    if r >= 1.55:
        return "16:9"
    if r <= 0.65:
        return "9:16"
    if r >= 1.2:
        return "4:3"
    if r <= 0.85:
        return "3:4"
    return "1:1"


async def _generate_pollinations(
    session: aiohttp.ClientSession, prompt: str, output_path: str, seed: int, width: int, height: int
) -> None:
    encoded_prompt = urllib.parse.quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}&nologo=true&seed={seed}"
    )
    attempts = 0
    backoff = 1.0
    while attempts < 3:
        attempts += 1
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.read()
                    async with aiofiles.open(output_path, mode="wb") as f:
                        await f.write(content)
                    return
                if response.status == 429:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise RuntimeError(f"Pollinations HTTP {response.status}")
        except aiohttp.ClientError:
            await asyncio.sleep(backoff)
            backoff *= 2
    raise RuntimeError("Pollinations failed after retries.")


async def _generate_stable_horde(
    session: aiohttp.ClientSession, prompt: str, output_path: str, width: int, height: int, api_key: str | None = None
) -> None:
    api_key = api_key or _first_env("STABLE_HORDE_API_KEY", "AI_HORDE_API_KEY") or "0000000000"
    w, h = _horde_grid_dims(width, height)
    payload = {
        "prompt": prompt,
        "params": {
            "width": w,
            "height": h,
            "steps": 20,
            "n": 1,
            "cfg_scale": 7.5,
            "sampler_name": "k_euler_a",
        },
        "models": ["Dreamshaper"],
        "nsfw": False,
        "trusted_workers": False,
        "r2": True,
    }
    headers = {
        "Content-Type": "application/json",
        "Client-Agent": "anonymous:0:ExplainerAI:1:https://github.com/local-explainer",
        "apikey": api_key,
    }
    async with session.post(
        "https://stablehorde.net/api/v2/generate/async",
        json=payload,
        headers=headers,
    ) as resp:
        body = await resp.text()
        if resp.status != 202:
            raise RuntimeError(f"Stable Horde submit failed ({resp.status}): {body[:400]}")
        data = json.loads(body)
        job_id = data.get("id")
        if not job_id:
            raise RuntimeError(f"Stable Horde: no job id in response: {body[:400]}")

    deadline = asyncio.get_event_loop().time() + 420.0
    check_url = f"https://stablehorde.net/api/v2/generate/check/{job_id}"
    img_url = None
    while asyncio.get_event_loop().time() < deadline:
        async with session.get(check_url, headers={"Client-Agent": headers["Client-Agent"], "apikey": api_key}) as cr:
            cj = await cr.json(content_type=None)
        if cj.get("faulted"):
            raise RuntimeError(f"Stable Horde job faulted: {cj.get('errors') or cj}")
        if cj.get("done"):
            gens = cj.get("generations") or []
            if gens and gens[0].get("img"):
                img_url = gens[0]["img"]
            break
        await asyncio.sleep(2.5)

    if not img_url:
        raise RuntimeError("Stable Horde timed out or returned no image URL.")

    async with session.get(img_url) as ir:
        if ir.status != 200:
            raise RuntimeError(f"Stable Horde image download failed: HTTP {ir.status}")
        raw = await ir.read()
    _save_raw_image_bytes_as_jpeg(raw, output_path)


async def _generate_huggingface_flux(
    session: aiohttp.ClientSession, prompt: str, output_path: str, api_key: str | None = None
) -> None:
    token = api_key or _first_env("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise RuntimeError(
            "Set HF_TOKEN (Hugging Face access token from https://huggingface.co/settings/tokens)."
        )
    model = "black-forest-labs/FLUX.1-schnell"
    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {token}"}
    # HF router accepts JSON body { "inputs": "..." } for text-to-image
    last_err = None
    for attempt in range(3):
        try:
            async with session.post(url, headers=headers, json={"inputs": prompt}, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status == 503:
                    await asyncio.sleep(5 * (attempt + 1))
                    last_err = await resp.text()
                    continue
                if resp.status != 200:
                    txt = await resp.text()
                    raise RuntimeError(f"Hugging Face HTTP {resp.status}: {txt[:500]}")
                ct = (resp.headers.get("Content-Type") or "").lower()
                raw = await resp.read()
                if "application/json" in ct:
                    info = json.loads(raw.decode(errors="replace"))
                    raise RuntimeError(f"Hugging Face returned JSON instead of image: {str(info)[:500]}")
                _save_raw_image_bytes_as_jpeg(raw, output_path)
                return
        except asyncio.TimeoutError as e:
            last_err = str(e)
            await asyncio.sleep(4)
    raise RuntimeError(f"Hugging Face generation failed: {last_err}")


async def _generate_deepai(session: aiohttp.ClientSession, prompt: str, output_path: str, api_key: str | None = None) -> None:
    key = api_key or _first_env("DEEPAI_API_KEY")
    if not key:
        raise RuntimeError("Set DEEPAI_API_KEY (free key from https://deepai.org/).")
    headers = {"Content-Type": "application/json", "api-key": key}
    async with session.post(
        "https://api.deepai.org/api/text2img",
        headers=headers,
        json={"text": prompt},
        timeout=aiohttp.ClientTimeout(total=120),
    ) as resp:
        txt = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"DeepAI HTTP {resp.status}: {txt[:400]}")
        data = json.loads(txt)
    out_url = data.get("output_url")
    if not out_url:
        raise RuntimeError(f"DeepAI: missing output_url in response: {txt[:400]}")
    async with session.get(out_url) as ir:
        if ir.status != 200:
            raise RuntimeError(f"DeepAI image fetch failed: HTTP {ir.status}")
        raw = await ir.read()
    _save_raw_image_bytes_as_jpeg(raw, output_path)


def _extract_gemini_image_bytes(data: dict) -> bytes:
    cands = data.get("candidates") or []
    for c in cands:
        content = (c or {}).get("content") or {}
        for part in content.get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if not inline:
                continue
            mime = (inline.get("mimeType") or inline.get("mime_type") or "").lower()
            b64 = inline.get("data")
            if b64 and ("image" in mime or not mime):
                return base64.b64decode(b64)
    raise RuntimeError(
        "Gemini returned no image data (safety block, unsupported model, or text-only response). "
        f"Raw keys: {list(data.keys())}"
    )


async def _generate_gemini_native_image(
    session: aiohttp.ClientSession, prompt: str, output_path: str, model: str, api_key: str | None = None
) -> None:
    key = api_key or _gemini_key()
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY (Google AI Studio).")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    params = {"key": key}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    async with session.post(
        url, params=params, json=body, timeout=aiohttp.ClientTimeout(total=180)
    ) as resp:
        txt = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"Gemini image API HTTP {resp.status}: {txt[:800]}")
        data = json.loads(txt)
    raw = _extract_gemini_image_bytes(data)
    _save_raw_image_bytes_as_jpeg(raw, output_path)


async def _generate_imagen_fast(
    session: aiohttp.ClientSession, prompt: str, output_path: str, width: int, height: int, api_key: str | None = None
) -> None:
    key = api_key or _gemini_key()
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY for Imagen.")
    model = "imagen-4.0-fast-generate-001"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict"
    ar = _imagen_aspect_ratio(width, height)
    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": ar,
            "personGeneration": "allow_adult",
        },
    }
    async with session.post(
        url, params={"key": key}, json=body, timeout=aiohttp.ClientTimeout(total=180)
    ) as resp:
        txt = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"Imagen HTTP {resp.status}: {txt[:800]}")
        data = json.loads(txt)

    preds = data.get("predictions") or []
    if not preds:
        raise RuntimeError(f"Imagen: empty predictions: {txt[:600]}")
    p0 = preds[0]
    b64 = p0.get("bytesBase64Encoded") or p0.get("bytes_base64_encoded")
    if not b64:
        # Some responses nest bytes inside 'bytesBase64Encoded' equivalent struct
        raise RuntimeError(f"Imagen: could not read image bytes from prediction keys: {list(p0.keys())}")
    raw = base64.b64decode(b64)
    _save_raw_image_bytes_as_jpeg(raw, output_path)


async def _generate_openai(
    session: aiohttp.ClientSession, prompt: str, output_path: str, width: int, height: int, api_key: str | None = None
) -> None:
    key = api_key or _first_env("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY to use DALL-E 3.")
    
    # Map dims to OpenAI supported sizes
    size = "1024x1024"
    if width > height * 1.5: size = "1792x1024"
    elif height > width * 1.5: size = "1024x1792"
    
    url = "https://api.openai.com/v1/images/generations"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": size,
    }
    async with session.post(url, headers=headers, json=body, timeout=120) as resp:
        txt = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"OpenAI HTTP {resp.status}: {txt[:500]}")
        data = json.loads(txt)
        img_url = data["data"][0]["url"]
    
    async with session.get(img_url) as ir:
        raw = await ir.read()
    _save_raw_image_bytes_as_jpeg(raw, output_path)

async def _generate_together(
    session: aiohttp.ClientSession, prompt: str, output_path: str, width: int, height: int, api_key: str | None = None
) -> None:
    key = api_key or _first_env("TOGETHER_API_KEY")
    if not key:
        raise RuntimeError("Set TOGETHER_API_KEY to use Together AI.")
    
    # Multiple of 64
    w = (width // 64) * 64
    h = (height // 64) * 64
    
    url = "https://api.together.xyz/v1/images/generations"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "prompt": prompt,
        "model": "black-forest-labs/FLUX.1-schnell-Free", # There is usually a free-tier flux model or similar
        "width": w,
        "height": h,
        "steps": 4,
        "n": 1,
    }
    # Fallback to standard model if Schnell-Free is not available
    try:
        async with session.post(url, headers=headers, json=body, timeout=60) as resp:
            if resp.status != 200:
                body["model"] = "stabilityai/stable-diffusion-xl-base-1.0"
                async with session.post(url, headers=headers, json=body, timeout=60) as resp2:
                    if resp2.status != 200:
                        txt = await resp2.text()
                        raise RuntimeError(f"Together AI failed: {txt[:500]}")
                    data = await resp2.json()
            else:
                data = await resp.json()
    except Exception as e:
         raise RuntimeError(f"Together AI API error: {str(e)}")

    img_b64 = data["data"][0]["b64_json"]
    raw = base64.b64decode(img_b64)
    _save_raw_image_bytes_as_jpeg(raw, output_path)

async def generate_prompt_image(
    prompt: str,
    output_path: str,
    seed: int | None = None,
    width: int = 1920,
    height: int = 1080,
    provider: str | None = None,
    api_key: str | None = None,
) -> str:
    """
    Generate an image for `prompt` into `output_path` using the selected provider.
    """
    pid = normalize_image_provider(provider)
    if seed is None:
        seed = random.randint(0, 2**31 - 1)

    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if pid == "pollinations":
            try:
                await _generate_pollinations(session, prompt, output_path, seed, width, height)
            except Exception:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _make_placeholder, prompt, output_path, width, height)
            return output_path
        
        if pid == "stable_horde" or pid == "stable_horde_anon":
            await _generate_stable_horde(session, prompt, output_path, width, height, api_key=api_key)
        elif pid == "openai":
            await _generate_openai(session, prompt, output_path, width, height, api_key=api_key)
        elif pid == "together":
            await _generate_together(session, prompt, output_path, width, height, api_key=api_key)
        elif pid == "huggingface_flux":
            await _generate_huggingface_flux(session, prompt, output_path, api_key=api_key)
        elif pid == "deepai":
            await _generate_deepai(session, prompt, output_path, api_key=api_key)
        elif pid == "gemini_nano_banana":
            await _generate_gemini_native_image(session, prompt, output_path, "gemini-2.5-flash-image", api_key=api_key)
        elif pid == "gemini_nano_banana_2":
            await _generate_gemini_native_image(session, prompt, output_path, "gemini-3.1-flash-image-preview", api_key=api_key)
        elif pid == "gemini_nano_banana_pro":
            await _generate_gemini_native_image(session, prompt, output_path, "gemini-3-pro-image-preview", api_key=api_key)
        elif pid == "imagen_fast":
            await _generate_imagen_fast(session, prompt, output_path, width, height, api_key=api_key)
        else:
            try:
                await _generate_pollinations(session, prompt, output_path, seed, width, height)
            except Exception:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _make_placeholder, prompt, output_path, width, height)
    return output_path
