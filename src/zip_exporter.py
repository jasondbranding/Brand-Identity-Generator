"""
zip_exporter.py — Bundle brand identity assets into a ZIP file.

Creates organized ZIP with:
  logo/         — logo.png, logo_white.png, logo_black.png, logo_transparent.png, logo.svg
  palette/      — palette.png, shades.png
  pattern/      — pattern.png
  mockups/      — all composited mockup images
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import List, Optional

import logging

logger = logging.getLogger(__name__)


def create_brand_identity_zip(
    brand_name: str,
    output_dir: Path,
    logo_paths: Optional[dict] = None,
    palette_png: Optional[Path] = None,
    shades_png: Optional[Path] = None,
    pattern_path: Optional[Path] = None,
    mockup_paths: Optional[List[Path]] = None,
    svg_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Bundle all brand identity assets into a ZIP file.

    Args:
        brand_name:   Brand name for the ZIP filename
        output_dir:   Directory to write the ZIP file
        logo_paths:   Dict of logo variants: {"logo": Path, "logo_white": Path, ...}
        palette_png:  Path to palette strip PNG
        shades_png:   Path to shade scale PNG
        pattern_path: Path to pattern tile PNG
        mockup_paths: List of composited mockup Paths
        svg_path:     Path to SVG logo

    Returns:
        Path to created ZIP file, or None on failure.
    """
    try:
        import re
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", brand_name.lower().strip())[:30]
        zip_path = output_dir / f"{safe_name}_brand_identity.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Logo variants
            if logo_paths:
                for key, p in logo_paths.items():
                    if p and Path(p).exists() and Path(p).stat().st_size > 100:
                        zf.write(p, f"logo/{Path(p).name}")

            # SVG
            if svg_path and svg_path.exists():
                zf.write(svg_path, f"logo/{svg_path.name}")

            # Palette
            if palette_png and Path(palette_png).exists():
                zf.write(palette_png, f"palette/{Path(palette_png).name}")
            if shades_png and Path(shades_png).exists():
                zf.write(shades_png, f"palette/{Path(shades_png).name}")

            # Pattern
            if pattern_path and Path(pattern_path).exists():
                zf.write(pattern_path, f"pattern/{Path(pattern_path).name}")

            # Mockups
            if mockup_paths:
                for mp in mockup_paths:
                    if mp and mp.exists() and mp.stat().st_size > 100:
                        zf.write(mp, f"mockups/{mp.name}")

        if zip_path.exists() and zip_path.stat().st_size > 100:
            logger.info(f"ZIP created: {zip_path.name} ({zip_path.stat().st_size // 1024} KB)")
            return zip_path

    except Exception as e:
        logger.warning(f"ZIP creation failed: {e}")

    return None
