"""
Project Manager — JSON-based persistence for ExplainerAI projects.
Handles save, load, list, delete, and built-in starter templates.
"""
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── Directory setup ───────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = BASE_DIR / "projects"
PROJECTS_DIR.mkdir(exist_ok=True)


# ── Built-in Templates ───────────────────────────────────────────────────

TEMPLATES = [
    {
        "id": "product_explainer",
        "name": "Product Explainer",
        "description": "5-scene structure: Hook → Problem → Solution → Features → Call to Action",
        "orientation": "landscape",
        "default_voice": "en-US-JennyNeural",
        "scenes": [
            {
                "narration": "Have you ever struggled with [problem]? You're not alone — millions face this challenge every day.",
                "image_prompt": "A person looking frustrated at their desk, cinematic lighting, modern office",
                "animation": "zoom_in",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "The problem is that traditional solutions are slow, expensive, and complicated. Most people give up before they even start.",
                "image_prompt": "Cluttered chaotic workspace with scattered papers and old technology, dark moody atmosphere",
                "animation": "pan_left",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "Introducing [Product] — a smarter, faster way to [solve the problem]. Built for real people with real needs.",
                "image_prompt": "Sleek futuristic product interface glowing on a holographic display, clean minimalist design",
                "animation": "ken_burns",
                "transition": "fade_black",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "With features like [Feature 1], [Feature 2], and [Feature 3], you'll save time and get better results every single day.",
                "image_prompt": "Abstract visualization of three connected features as glowing nodes, tech style, blue and purple palette",
                "animation": "zoom_out",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "Ready to get started? Visit [website] today and join thousands of happy users who have already made the switch.",
                "image_prompt": "Happy diverse group of people celebrating success, confetti, bright uplifting lighting",
                "animation": "pan_right",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
        ],
    },
    {
        "id": "tutorial_howto",
        "name": "Tutorial / How-To",
        "description": "4-scene structure: Introduction → Step 1 → Step 2 → Conclusion",
        "orientation": "landscape",
        "default_voice": "en-US-GuyNeural",
        "scenes": [
            {
                "narration": "In this tutorial, I'll show you how to [task] in just a few simple steps. Let's get started!",
                "image_prompt": "A clean tutorial title card with text overlay effect, modern flat design, gradient background",
                "animation": "zoom_in",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "Step one: [Describe the first step in detail]. Make sure to pay attention to [important detail].",
                "image_prompt": "Step by step instruction diagram, numbered step 1 highlighted, clean infographic style",
                "animation": "pan_right",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "Step two: [Describe the second step]. This is where most people make mistakes, so take your time here.",
                "image_prompt": "Step by step instruction diagram, numbered step 2 highlighted, attention arrow pointer, infographic style",
                "animation": "pan_left",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "And that's it! You've successfully learned how to [task]. If this was helpful, like and subscribe for more tutorials.",
                "image_prompt": "Success celebration with checkmark, thumbs up icon, modern flat illustration, bright green accents",
                "animation": "ken_burns",
                "transition": "fade_black",
                "volume": 1.0,
                "mute_audio": False,
            },
        ],
    },
    {
        "id": "listicle",
        "name": "Listicle / Top Items",
        "description": "6-scene structure: Intro → Item 1 → Item 2 → Item 3 → Item 4 → Outro",
        "orientation": "landscape",
        "default_voice": "en-GB-SoniaNeural",
        "scenes": [
            {
                "narration": "Here are the top [number] [things] you need to know in [year]. Let's count them down!",
                "image_prompt": "Exciting top list title card with countdown numbers, bold typography, dark gradient background with neon accents",
                "animation": "zoom_in",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "Number one: [Item Name]. [Explain why this item is important and what makes it stand out.]",
                "image_prompt": "Bold number 1 with dramatic lighting, award trophy, premium gold and dark theme",
                "animation": "ken_burns",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "Number two: [Item Name]. [Describe this item's key features and benefits.]",
                "image_prompt": "Bold number 2 floating in mid-air, silver metallic finish, studio lighting",
                "animation": "pan_left",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "Number three: [Item Name]. [Share interesting facts or statistics about this item.]",
                "image_prompt": "Bold number 3 with sparkle effects, bronze metallic finish, cinematic backdrop",
                "animation": "pan_right",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "Number four: [Item Name]. [Explain what makes this a must-know item on the list.]",
                "image_prompt": "Bold number 4 with glowing neon outline, futuristic tech aesthetic, dark background",
                "animation": "zoom_out",
                "transition": "crossfade",
                "volume": 1.0,
                "mute_audio": False,
            },
            {
                "narration": "That wraps up our list! Which one was your favorite? Let us know in the comments and don't forget to subscribe!",
                "image_prompt": "Animated subscribe button with bell icon, social media engagement graphics, bright vibrant colors",
                "animation": "ken_burns",
                "transition": "fade_black",
                "volume": 1.0,
                "mute_audio": False,
            },
        ],
    },
]


# ── Helper functions ──────────────────────────────────────────────────────

def _project_path(project_id: str) -> Path:
    return PROJECTS_DIR / f"{project_id}.json"


def list_templates() -> list[dict]:
    """Return the list of built-in templates (metadata only, no full scenes for listing)."""
    return [
        {"id": t["id"], "name": t["name"], "description": t["description"],
         "scene_count": len(t["scenes"]), "orientation": t["orientation"]}
        for t in TEMPLATES
    ]


def get_template(template_id: str) -> dict | None:
    """Return a full template by ID."""
    for t in TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


def save_project(project_data: dict) -> dict:
    """
    Save a project. If 'id' is provided and exists, update it.
    Otherwise create a new project.

    Returns the saved project dict.
    """
    project_id = project_data.get("id") or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Load existing to preserve created_at
    existing_path = _project_path(project_id)
    if existing_path.exists():
        with open(existing_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        created_at = existing.get("created_at", now)
    else:
        created_at = now

    project = {
        "id": project_id,
        "name": project_data.get("name", "Untitled Project"),
        "created_at": created_at,
        "updated_at": now,
        "orientation": project_data.get("orientation", "landscape"),
        "default_voice": project_data.get("default_voice", "en-US-JennyNeural"),
        "image_source": project_data.get("image_source", "ai"),
        "scenes": project_data.get("scenes", []),
    }

    with open(_project_path(project_id), "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)

    return project


def load_project(project_id: str) -> dict | None:
    """Load a project by ID. Returns None if not found."""
    path = _project_path(project_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_projects() -> list[dict]:
    """List all saved projects (metadata only)."""
    projects = []
    for f in sorted(PROJECTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                projects.append({
                    "id": data["id"],
                    "name": data.get("name", "Untitled"),
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "orientation": data.get("orientation", "landscape"),
                    "scene_count": len(data.get("scenes", [])),
                })
        except (json.JSONDecodeError, KeyError):
            continue
    return projects


def delete_project(project_id: str) -> bool:
    """Delete a project file. Returns True if deleted."""
    path = _project_path(project_id)
    if path.exists():
        path.unlink()
        return True
    return False
