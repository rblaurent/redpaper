"""Generate daily ComfyUI prompts via `claude -p`."""
import asyncio
import json
import logging
import os
import shutil
import subprocess
from datetime import date

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _claude_path() -> str:
    try:
        with open(os.path.join(_BASE_DIR, "config.json")) as f:
            return json.load(f).get("claude_path", "") or shutil.which("claude") or "claude"
    except Exception:
        return shutil.which("claude") or "claude"

logger = logging.getLogger(__name__)

META_PROMPT_TEMPLATE = """Today is {date}. Day-of-year: {day_of_year}.

You are a ComfyUI prompt engineer for the z-turbo (z_image_turbo_bf16) diffusion model.
Your task: write exactly ONE image generation prompt for today's wallpaper.

The desktop's thematic direction is:
---
{theme}
---

Using that as your creative foundation, generate a single specific scene for today.
Day {day_of_year} out of 365 — use the date to explore a fresh angle, sub-scene, or
moment within the theme. Never repeat yesterday.

REQUIREMENTS for z-turbo:
- Around 200-300 tokens, comma-separated keywords and short phrases — NO full sentences
- Subjects, atmosphere, mood, color palette, lighting, composition hints
- Quality boosters (pick what fits): masterpiece, best quality, ultra detailed, sharp focus, 8k uhd, cinematic, highly detailed, intricate
- Lighting (pick 1-2): golden hour, dramatic backlighting, soft diffused light, neon glow, bioluminescent, moonlit, volumetric rays, rim lighting, studio lighting

OUTPUT RULES — critical:
- Output ONLY the raw prompt text, nothing else
- No explanation, no preamble, no quotes, no markdown
- Single line only

Prompt for {date}:"""


async def generate_prompt_for_desktop(desktop, today: date) -> str | None:
    """
    Calls `claude -p` with a meta-prompt built from the desktop's theme description.
    Returns the generated ComfyUI prompt string, or None on failure.
    """
    claude = _claude_path()
    if not claude:
        logger.error("claude CLI not configured — set claude_path in config.json")
        return None

    meta = META_PROMPT_TEMPLATE.format(
        date=today.isoformat(),
        day_of_year=today.timetuple().tm_yday,
        theme=desktop.theme,
    )
    cwd = desktop.workspace_path or None

    # Pass prompt via stdin to avoid newline/length issues on Windows.
    # claude -p with no argument reads the prompt from stdin.
    # .cmd/.bat files on Windows must go through cmd /c.
    if claude.lower().endswith((".cmd", ".bat")):
        args = ["cmd", "/c", claude, "-p"]
    else:
        args = [claude, "-p"]

    def _run_claude():
        return subprocess.run(
            args,
            input=meta.encode("utf-8"),
            capture_output=True,
            timeout=60,
            cwd=cwd,
        )

    try:
        completed = await asyncio.to_thread(_run_claude)
    except subprocess.TimeoutExpired:
        logger.error("claude -p timed out for desktop %s", desktop.guid)
        return None
    except Exception as e:
        logger.error("claude -p error (%s): %s", type(e).__name__, e)
        return None

    if completed.returncode != 0:
        logger.error(
            "claude -p exit %d for %s: %s",
            completed.returncode, desktop.guid,
            completed.stderr.decode(errors="replace").strip(),
        )
        return None

    result = completed.stdout.decode(errors="replace").strip()
    if not result:
        logger.error("claude -p returned empty output for desktop %s", desktop.guid)
        return None

    # Take only the first line in case Claude added extra output
    first_line = result.splitlines()[0].strip()
    if len(first_line) > 600:
        first_line = first_line[:600]

    logger.info("AI prompt for %s: %s", desktop.guid, first_line[:80])
    return first_line


REFINE_THEME_TEMPLATE = """You are helping a user manage wallpaper themes for their desktop.

IMPORTANT — understand the two-level system:
- A THEME is a persistent creative brief written in rich prose. It defines the visual world, mood, color palette, atmosphere, and style references that should guide the desktop. It is NOT an image generation prompt — it is human-readable guidelines that will later be used as creative direction to generate a new image every day.
- A DAILY PROMPT is what gets generated each day FROM the theme: a short, keyword-heavy ComfyUI prompt for the diffusion model.

You are editing the THEME (the creative brief), not writing a daily prompt.

Current theme:
---
{current_theme}
---

User instruction: {instruction}

Rewrite the theme to reflect the instruction. Keep it as flowing prose (2–5 sentences). Describe the visual world, mood, palette, atmosphere, and any style or artistic references. Do NOT write comma-separated keywords, technical tags, or anything that looks like an image generation prompt. Output ONLY the updated theme text — no explanation, no markdown, no quotes, no preamble."""

CREATE_THEME_TEMPLATE = """You are helping a user set up a wallpaper theme for their desktop.

IMPORTANT — understand the two-level system:
- A THEME is a persistent creative brief written in rich prose. It defines the visual world, mood, color palette, atmosphere, and style references that should guide the desktop. It is NOT an image generation prompt — it is human-readable guidelines that will later be used as creative direction to generate a new image every day.
- A DAILY PROMPT is what gets generated each day FROM the theme: a short, keyword-heavy ComfyUI prompt for the diffusion model.

You are writing the THEME (the creative brief), not a daily prompt.

User request: {instruction}

Write a theme as flowing prose (2–5 sentences). Describe the visual world, mood, color palette, atmosphere, and any style or artistic references. Do NOT write comma-separated keywords, technical tags, or anything that looks like an image generation prompt. Output ONLY the theme text — no explanation, no markdown, no quotes, no preamble."""


async def refine_theme(current_theme: str | None, instruction: str) -> str | None:
    """
    Calls `claude -p` to create or update a desktop theme description.
    If current_theme is set, rewrites it per the instruction.
    If current_theme is None, generates a fresh theme from the instruction.
    Returns the updated theme string, or None on failure.
    """
    claude = _claude_path()
    if not claude:
        logger.error("claude CLI not configured — set claude_path in config.json")
        return None

    if current_theme:
        meta = REFINE_THEME_TEMPLATE.format(
            current_theme=current_theme,
            instruction=instruction,
        )
    else:
        meta = CREATE_THEME_TEMPLATE.format(instruction=instruction)

    if claude.lower().endswith((".cmd", ".bat")):
        args = ["cmd", "/c", claude, "-p"]
    else:
        args = [claude, "-p"]

    def _run_claude():
        return subprocess.run(
            args,
            input=meta.encode("utf-8"),
            capture_output=True,
            timeout=60,
        )

    try:
        completed = await asyncio.to_thread(_run_claude)
    except subprocess.TimeoutExpired:
        logger.error("claude -p timed out during theme refine")
        return None
    except Exception as e:
        logger.error("claude -p error during theme refine (%s): %s", type(e).__name__, e)
        return None

    if completed.returncode != 0:
        logger.error(
            "claude -p exit %d during theme refine: %s",
            completed.returncode,
            completed.stderr.decode(errors="replace").strip(),
        )
        return None

    result = completed.stdout.decode(errors="replace").strip()
    if not result:
        logger.error("claude -p returned empty output during theme refine")
        return None

    logger.info("Refined theme: %s", result[:80])
    return result
