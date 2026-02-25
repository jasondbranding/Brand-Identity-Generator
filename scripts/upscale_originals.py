#!/usr/bin/env python3
"""
upscale_originals.py — Re-render mockup originals to high-resolution using Nano Banana.

Usage:
    cd ~/brand-identity-generator
    source .venv/bin/activate
    python scripts/upscale_originals.py [--all] [--file wall_logo_original.jpg]

For each image in mockups/originals/, sends it to Nano Banana (gemini-3-pro-image-preview)
with an upscale/enhance prompt, then overwrites the original file with the high-res result.

Saves a backup to mockups/originals/_backup/ before overwriting.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from rich.console import Console
from rich.rule import Rule

load_dotenv()
console = Console()

ORIGINALS_DIR = Path("mockups/originals")
BACKUP_DIR    = ORIGINALS_DIR / "_backup"
IMAGE_EXTS    = {".png", ".jpg", ".jpeg", ".webp"}

# Model ladder: Nano Banana Pro first, fallback to Nano Banana
MODELS = [
    "gemini-3-pro-image-preview",   # Nano Banana Pro — best quality
    "gemini-2.5-flash-image",       # Nano Banana — fast fallback
]

UPSCALE_PROMPT = """\
You are a professional photo retoucher and mockup artist.

Task: Re-render this mockup image at ultra-high resolution (4K quality).

Rules:
1. Keep the EXACT same composition, framing, and camera angle.
2. Keep the EXACT same placeholder logo/artwork — same shape, same position, same size.
3. Enhance to photorealistic quality: sharpen details, improve material textures \
(fabric weave, metal finish, paper grain, acrylic clarity, screen pixels, etc.).
4. Improve lighting quality — make shadows softer and more realistic, enhance reflections.
5. Do NOT change colors, layout, or design elements.
6. Do NOT add new elements or remove existing ones.
7. Output a single high-resolution image. No borders, no captions, no watermarks.

The output should look like a professional studio-quality product mockup photo."""


def upscale_image(image_path: Path, api_key: str) -> bytes | None:
    """Send image to Nano Banana for upscale/re-render. Returns PNG bytes or None."""
    client = genai.Client(api_key=api_key)

    img_bytes = image_path.read_bytes()
    ext       = image_path.suffix.lower()
    mime_map  = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".png": "image/png",  ".webp": "image/webp"}
    mime_type = mime_map.get(ext, "image/jpeg")

    parts = [
        types.Part.from_text(text=UPSCALE_PROMPT),
        types.Part.from_text(text="MOCKUP IMAGE TO RE-RENDER:"),
        types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
        types.Part.from_text(text=(
            "Now output the re-rendered high-resolution version of this mockup. "
            "Same composition, same placeholder logo, dramatically improved quality. "
            "Output image only."
        )),
    ]

    for model in MODELS:
        try:
            response = client.models.generate_content(
                model=model,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )
            for candidate in response.candidates or []:
                for part in candidate.content.parts or []:
                    if hasattr(part, "inline_data") and part.inline_data:
                        data = part.inline_data.data
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        return data
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ("not found", "permission", "not supported", "invalid")):
                console.print(f"  [dim]  {model} unavailable, trying next…[/dim]")
                continue
            console.print(f"  [yellow]  Error: {e}[/yellow]")
            return None

    return None


def process_file(image_path: Path, api_key: str, dry_run: bool = False) -> bool:
    size_kb = image_path.stat().st_size / 1024
    console.print(f"\n  [bold]{image_path.name}[/bold]  [dim]({size_kb:.0f}KB)[/dim]")

    if dry_run:
        console.print("  [dim]  → dry-run, skipping[/dim]")
        return True

    # Backup original
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / image_path.name
    if not backup_path.exists():
        shutil.copy2(image_path, backup_path)
        console.print(f"  [dim]  Backed up → {backup_path}[/dim]")

    console.print("  [dim]  Sending to Nano Banana…[/dim]")
    t0 = time.time()
    result = upscale_image(image_path, api_key)

    if result:
        # Save as PNG (higher quality for AI-generated output)
        out_path = image_path.with_suffix(".png")
        out_path.write_bytes(result)
        new_kb = len(result) / 1024
        elapsed = time.time() - t0
        console.print(
            f"  [green]✓ Done[/green]  "
            f"{size_kb:.0f}KB → [bold]{new_kb:.0f}KB[/bold]  "
            f"[dim]({elapsed:.1f}s)[/dim]"
        )
        # Remove old .jpg if we wrote .png
        if out_path != image_path and image_path.exists():
            image_path.unlink()
            console.print(f"  [dim]  Replaced {image_path.name} → {out_path.name}[/dim]")
        return True
    else:
        console.print(f"  [red]✗ Failed — original unchanged[/red]")
        return False


def main():
    parser = argparse.ArgumentParser(description="Upscale mockup originals with Nano Banana")
    parser.add_argument("--all",      action="store_true", help="Process all images in originals/")
    parser.add_argument("--low-res",  action="store_true", help="Process only low-res images (<200KB)")
    parser.add_argument("--file",     type=str, default=None, help="Process a specific filename")
    parser.add_argument("--dry-run",  action="store_true", help="List files without processing")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[red]Error: GEMINI_API_KEY not set in .env[/red]")
        sys.exit(1)

    if not ORIGINALS_DIR.exists():
        console.print(f"[red]Error: {ORIGINALS_DIR} not found[/red]")
        sys.exit(1)

    # Collect files to process
    all_files = sorted(
        p for p in ORIGINALS_DIR.iterdir()
        if p.suffix.lower() in IMAGE_EXTS
        and not p.name.startswith(".")
        and p.parent == ORIGINALS_DIR  # skip _backup/
    )

    if args.file:
        target = ORIGINALS_DIR / args.file
        if not target.exists():
            console.print(f"[red]File not found: {target}[/red]")
            sys.exit(1)
        files = [target]
    elif args.low_res:
        files = [f for f in all_files if f.stat().st_size < 200 * 1024]
    elif args.all:
        files = all_files
    else:
        parser.print_help()
        console.print("\n[yellow]Tip: use --low-res to process only files under 200KB[/yellow]")
        console.print("\nFiles in originals/:")
        for f in all_files:
            kb = f.stat().st_size / 1024
            flag = " ← low-res" if kb < 200 else ""
            console.print(f"  {f.name:<45} {kb:>6.0f}KB{flag}")
        sys.exit(0)

    console.print(Rule("[bold cyan]Nano Banana Upscaler[/bold cyan]"))
    console.print(f"  Processing [bold]{len(files)}[/bold] file(s)…")

    ok = fail = 0
    for f in files:
        success = process_file(f, api_key, dry_run=args.dry_run)
        if success:
            ok += 1
        else:
            fail += 1
        if f != files[-1]:
            time.sleep(2)  # brief pause between API calls

    console.print(Rule())
    console.print(f"  Done: [green]{ok} succeeded[/green]  [red]{fail} failed[/red]")
    if BACKUP_DIR.exists():
        console.print(f"  Backups saved in: {BACKUP_DIR}")


if __name__ == "__main__":
    main()
