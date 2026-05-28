import asyncio
import logging
import edge_tts
import os

async def generate_audio_from_text(text: str, output_path: str, voice: str = "en-US-JennyNeural") -> str:
    """
    Generates an MP3 audio file from text using edge-tts.

    Retries up to 3 times with exponential backoff on transient network failures.

    Args:
        text (str): The text to be spoken.
        output_path (str): Path where the MP3 file will be saved.
        voice (str): The MS Edge TTS voice model to use.
                     Available voices: edge-tts --list-voices
                     Good defaults:
                     - en-US-JennyNeural (Female, American)
                     - en-US-GuyNeural (Male, American)
                     - en-GB-SoniaNeural (Female, British)

    Returns:
        str: The path to the generated audio file.

    Raises:
        RuntimeError: If all 3 attempts fail.
    """
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            return output_path
        except Exception as exc:
            last_error = exc
            logging.warning(
                "edge-tts attempt %d/3 failed (voice=%s): %s",
                attempt + 1, voice, exc,
            )
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s
    raise RuntimeError(f"Audio generation failed after 3 attempts: {last_error}")
