# YouTube Explainer Video Generator

This project will set up a web-based application aimed at generating high-quality YouTube explainer videos. It uses entirely free, open-source, or no-registration tools to ensure you can create content without watermarks or subscription fees.

## User Review Required

> [!NOTE]
> I have selected **FastAPI** with a **Vanilla HTML/JS/CSS** frontend for the app to give you maximum flexibility and a rich, interactive web application feel. 
> 
> For **AI Image Generation**, the plan uses **Pollinations.ai**, a completely free and unlimited API that generates AI images without needing API keys. 
> For **Voiceovers**, we will use **edge-tts**, which provides access to Microsoft's high-quality neural voices natively from Python, entirely for free.
> 
> Please review this plan. If it looks good, I will proceed with creating the files and installing the dependencies in a new workspace on your Desktop.

## Proposed Changes

### Core Configuration
#### [NEW] requirements.txt
Contains necessary Python dependencies: `fastapi`, `uvicorn`, `moviepy`, `edge-tts`, `requests`, `python-multipart`, `aiofiles`.

### Backend Engine
#### [NEW] main.py
FastAPI application that serves the static files and exposes endpoints for generating audio, generating images, uploading files, and rendering the final video.

#### [NEW] audio_engine.py
Wraps `edge-tts` to take a given text and output an MP3 file seamlessly to the server's cache folder.

#### [NEW] image_engine.py
Responsible for making requests to the free AI generation API (`pollinations.ai`) and downloading the resulting images, or saving any custom images you upload from the frontend.

#### [NEW] video_engine.py
Uses `moviepy` to:
1. Take a list of scenes (each with an image/video and an audio track).
2. Calculate the duration of each scene based accurately on its voiceover audio length.
3. Apply smooth transitions and stitch the scenes together.
4. Export the final 1080p high-quality MP4 file.

### Frontend Interface
#### [NEW] static/index.html
A responsive single-page layout. Will feature a workspace area where you can add multiple "scenes," paste text for each, and click to generate assets individually or all at once. Includes a built-in Usage Guide for users to easily understand the tool.

#### [NEW] static/style.css
Premium, sleek modern web design with a dynamic dark-mode aesthetic to make the tool look highly professional. Designed to be extremely beautiful, intuitive, and easy to use.

#### [NEW] static/app.js
Handles the dynamic logic: communicating with the backend, dynamic scene insertion/deletion, swapping out images from the interface, and triggering the final video generation process.

## Verification Plan

### Automated Tests
- Because this is a GUI and media-focused app, automated unit tests will be skipped for the initial build to ensure rapid development.

### Manual Verification
- We will start the FastAPI server locally.
- Access the web interface, and create a 2-scene sequence.
- Generate voiceover and AI images using the free providers.
- Render the sequence and verify that the final output `output.mp4` download successfully and plays smoothly with matching audio.
