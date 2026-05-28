# Fixes to Apply

## 1. Audio Merging Issue (video_engine.py)
The audio is not properly merging between scenes. Fix the transition audio handling:

In `_apply_transition()` function, when applying transitions, ensure audio from the first clip is preserved and the second clip's audio is properly attached after the transition.

**Issue**: When using `without_audio()` on transitions, the audio from the second scene is lost.

**Fix**: Preserve audio timing and ensure proper concatenation with audio overlap handling.

## 2. Add Scene Button at Bottom (static/index.html & static/app.js)
Make it easier to add scenes without scrolling up.

**Changes needed**:
- Add a floating "Add Scene" button at the bottom of the scene list
- Show/hide it based on whether there are scenes
- Bind click event to same `addScene()` function

## 3. Video Watermark Removal Checkbox (static/index.html & static/app.js)
Reuse the Gemini watermark checkbox for other video watermarks (like Veo).

**Changes needed**:
- Rename checkbox label to be more generic: "Remove watermark from this media"
- Add support for `video_watermark_source` flag in scene data
- Pass this flag to video_engine.py for processing

## 4. Image Replacement Issue (main.py & static/app.js)
When users replace/switch images, old images still appear in final render.

**Root cause**: Old image files remain in cache directory with same filename pattern.

**Fix**:
- When uploading new image to same scene, delete old image files first
- Clear old watermark-removed copies (`_dewm.jpg`)
- Ensure scene state reflects the new media path

**Implementation**:
- In `api_upload_media()`: Before saving new image, delete existing image files in that scene directory
- In frontend: When uploading new media, clear the old preview and update scene state

## Files to Modify:
1. `video_engine.py` - Fix audio merging in transitions
2. `static/index.html` - Add bottom "Add Scene" button
3. `static/app.js` - Bind bottom button, improve watermark checkbox label, fix image replacement
4. `main.py` - Clean up old images before uploading new ones
