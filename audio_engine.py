import asyncio
import edge_tts
import os

async def generate_audio_from_text(text: str, output_path: str, voice: str = "en-US-JennyNeural") -> str:
    """
    Generates an MP3 audio file from text using edge-tts.
    
    Args:
        text (str): The text to be spoken.
        output_path (str): Path where the MP3 file will be saved.
        voice (str): The MS Edge TTS voice model description to use.
                     Available voices can be found using edge-tts --list-voices
                     Good defaults: 
                     - en-US-JennyNeural (Female, American)
                     - en-US-GuyNeural (Male, American)
                     - en-GB-SoniaNeural (Female, British)
    
    Returns:
        str: The path to the generated audio file.
    """
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
    return output_path
