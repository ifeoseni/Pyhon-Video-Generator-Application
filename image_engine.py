import urllib.parse
import os
import aiofiles
import aiohttp

async def generate_prompt_image(prompt: str, output_path: str, seed: int = None, width: int = 1920, height: int = 1080) -> str:
    """
    Generates an AI image using the free Pollinations.ai API and saves it.
    
    Args:
        prompt (str): The description of the image.
        output_path (str): File path to save the generated image (e.g., .jpg).
        seed (int): Optional seed for deterministic generation.
        width (int): Image width.
        height (int): Image height.
        
    Returns:
        str: Output path where the image is saved.
    """
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"
    
    if seed is not None:
        url += f"&seed={seed}"
        
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                content = await response.read()
                async with aiofiles.open(output_path, mode='wb') as f:
                    await f.write(content)
                return output_path
            else:
                raise Exception(f"Failed to fetch image. Status: {response.status}")
