import urllib.parse
import os
import random
import aiofiles
import aiohttp
import asyncio
from PIL import Image, ImageDraw, ImageFont


def _make_placeholder(prompt: str, output_path: str, width: int, height: int):
    """Create a simple placeholder image with the prompt text (synchronous)."""
    bg = Image.new("RGB", (width, height), color=(30, 30, 40))
    draw = ImageDraw.Draw(bg)

    # Try to load a reasonable system font, fallback to default
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

    # Draw a subtle gradient
    for i in range(height):
        blend = int(20 + 40 * (i / max(1, height)))
        draw.line([(0, i), (width, i)], fill=(blend, blend, blend))

    # Helper to measure text size in a Pillow-version-robust way
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

    # Wrap prompt text
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

    # Draw boxed text centered
    total_h = sum(_text_size(draw, l, font)[1] for l in lines) + (len(lines) - 1) * 6
    y = int((height - total_h) / 2)
    box_margin = 20
    for line in lines:
        tw, th = _text_size(draw, line, font)
        x = int((width - tw) / 2)
        # box
        draw.rectangle([x - box_margin, y - 8, x + tw + box_margin, y + th + 8], fill=(10, 10, 12, 180))
        draw.text((x, y), line, font=font, fill=(240, 240, 245))
        y += th + 6

    bg.save(output_path)


async def generate_prompt_image(prompt: str, output_path: str, seed: int = None, width: int = 1920, height: int = 1080) -> str:
    """
    Generates an AI image using Pollinations.ai with retries and falls back to
    a local placeholder image if the service is rate-limited.
    """
    # Ensure a seed is provided so repeated calls produce different images
    if seed is None:
        seed = random.randint(0, 2 ** 31 - 1)

    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&seed={seed}"

    attempts = 0
    backoff = 1.0
    async with aiohttp.ClientSession() as session:
        while attempts < 3:
            attempts += 1
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()
                        async with aiofiles.open(output_path, mode='wb') as f:
                            await f.write(content)
                        return output_path
                    elif response.status == 429:
                        # rate limited, backoff and retry
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    else:
                        # other error
                        raise Exception(f"Failed to fetch image. Status: {response.status}")
            except aiohttp.ClientError:
                await asyncio.sleep(backoff)
                backoff *= 2

    # If we reach here, remote generation failed (likely rate limit) — create a placeholder.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _make_placeholder, prompt, output_path, width, height)
    return output_path
