#!/usr/bin/env python3
"""
label_tool.py v2 — 3-zone mockup labeler

Scans mockups/processed/ directly and labels 3 zones per mockup:
  LOGO    (#FF00FF)  — where the brand logo goes
  TEXT    (#00FFFF)  — where the brand name / text goes
  SURFACE (#FFFF00)  — where the brand color / pattern goes

Only queues mockups that are missing at least one zone.
All saved zones are displayed simultaneously on the image.

Controls:
  Click + drag   Draw rectangle for the active zone
  S              Save current zone → advance to next zone (or next mockup)
  R              Redo — clear current drawing, draw again
  N              Skip this entire mockup (no zones saved)
  Q              Quit and save progress

Usage:
  python label_tool.py
  python label_tool.py --processed-dir mockups/processed --metadata mockups/metadata.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import tkinter as tk
except ImportError:
    print("Error: tkinter not available.")
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    print("Error: Pillow not installed.  Run: pip install Pillow")
    sys.exit(1)


# ── Zone definitions ──────────────────────────────────────────────────────────
#   (metadata_key, display_label, fill_rgba, outline_rgba, hex_for_tk)

ZONES: List[Tuple[str, str, Tuple[int, int, int, int], Tuple[int, int, int, int], str]] = [
    ("logo_area",    "LOGO",    (255,   0, 255,  72), (255,   0, 255, 255), "#FF00FF"),
    ("text_area",    "TEXT",    (  0, 255, 255,  72), (  0, 255, 255, 255), "#00FFFF"),
    ("surface_area", "SURFACE", (255, 255,   0,  72), (255, 255,   0, 255), "#FFFF00"),
]

IMAGE_EXTS       = {".png", ".jpg", ".jpeg", ".webp"}
MAX_CANVAS_W     = 1200
MAX_CANVAS_H     = 800
OUTLINE_PX       = 2

DEFAULT_PROCESSED = Path("mockups/processed")
DEFAULT_METADATA  = Path("mockups/metadata.json")


# ── LabelTool ─────────────────────────────────────────────────────────────────

class LabelTool:
    def __init__(
        self,
        root: tk.Tk,
        processed_dir: Path,
        metadata_path: Path,
    ) -> None:
        self.root          = root
        self.processed_dir = processed_dir
        self.metadata_path = metadata_path

        # Persistent data
        self.metadata: Dict = {}

        # Navigation
        self.queue:            List[str] = []
        self.total:            int = 0
        self.mockup_idx:       int = 0

        # Per-mockup state
        # zone_rects: key → (x, y, w, h) in original image pixels
        self.zone_rects:       Dict[str, Tuple[int, int, int, int]] = {}
        self.current_zone_idx: int = 0

        # Image display
        self.orig_image: Optional[Image.Image] = None
        self.scale:      float = 1.0
        self.offset_x:   int = 0
        self.offset_y:   int = 0
        self.disp_w:     int = 0
        self.disp_h:     int = 0
        self.tk_image:   Optional[ImageTk.PhotoImage] = None

        # Drawing state
        self.drag_start: Optional[Tuple[int, int]] = None
        self.drag_end:   Optional[Tuple[int, int]] = None

        self._load_metadata()
        self._build_queue()
        self._setup_ui()
        self.root.after(10, self._load_mockup)

    # ── Metadata ──────────────────────────────────────────────────────────────

    def _load_metadata(self) -> None:
        if self.metadata_path.exists():
            with open(self.metadata_path, encoding="utf-8") as f:
                self.metadata = json.load(f)
        else:
            self.metadata = {}

    def _save_metadata(self) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)

    # ── Queue ─────────────────────────────────────────────────────────────────

    def _build_queue(self) -> None:
        """
        Scan processed_dir for image files.
        Include a mockup only if it is missing at least one zone.
        """
        all_files = sorted(
            p for p in self.processed_dir.iterdir()
            if p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")
        )
        zone_keys = [z[0] for z in ZONES]
        queue: List[str] = []
        for p in all_files:
            name = p.name
            info = self.metadata.get(name, {})
            missing = any(not info.get(key) for key in zone_keys)
            if missing:
                queue.append(name)
        self.queue = queue
        self.total = len(queue)

    # ── UI setup ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self.root.title("Mockup Zone Labeler v2")
        self.root.resizable(False, False)
        self.root.configure(bg="#111111")

        # ── Top bar: filename + progress ──────────────────────────────────────
        top = tk.Frame(self.root, bg="#111111", pady=8)
        top.pack(fill=tk.X)

        self.lbl_filename = tk.Label(
            top, text="",
            fg="#e8e8e8", bg="#111111",
            font=("Helvetica", 13, "bold"),
            anchor="w", padx=14,
        )
        self.lbl_filename.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.lbl_progress = tk.Label(
            top, text="",
            fg="#666666", bg="#111111",
            font=("Helvetica", 11),
            padx=14,
        )
        self.lbl_progress.pack(side=tk.RIGHT)

        tk.Frame(self.root, height=1, bg="#222222").pack(fill=tk.X)

        # ── Zone indicator bar ────────────────────────────────────────────────
        zone_bar = tk.Frame(self.root, bg="#161616", pady=10)
        zone_bar.pack(fill=tk.X)

        # spacer left
        tk.Label(zone_bar, text="", bg="#161616", width=4).pack(side=tk.LEFT)

        self.zone_label_widgets: List[tk.Label] = []
        for i, (key, label, fill_rgba, outline_rgba, hex_col) in enumerate(ZONES):
            if i > 0:
                tk.Label(
                    zone_bar, text="  ·  ",
                    fg="#333333", bg="#161616",
                    font=("Helvetica", 13),
                ).pack(side=tk.LEFT)
            lbl = tk.Label(
                zone_bar, text=f"● {label}",
                fg="#444444", bg="#161616",
                font=("Helvetica", 13, "bold"),
                padx=10,
            )
            lbl.pack(side=tk.LEFT)
            self.zone_label_widgets.append(lbl)

        tk.Frame(self.root, height=1, bg="#222222").pack(fill=tk.X)

        # ── Canvas ────────────────────────────────────────────────────────────
        self.canvas = tk.Canvas(
            self.root,
            width=MAX_CANVAS_W, height=MAX_CANVAS_H,
            bg="#1a1a1a", cursor="crosshair",
            highlightthickness=0,
        )
        self.canvas.pack()

        self.canvas.bind("<ButtonPress-1>",  self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Key>",               self._on_key)

        tk.Frame(self.root, height=1, bg="#222222").pack(fill=tk.X)

        # ── Status bar ────────────────────────────────────────────────────────
        bottom = tk.Frame(self.root, bg="#111111", pady=7)
        bottom.pack(fill=tk.X)

        self.lbl_status = tk.Label(
            bottom, text=self._hint(),
            fg="#555555", bg="#111111",
            font=("Helvetica", 11),
            anchor="w", padx=14,
        )
        self.lbl_status.pack(side=tk.LEFT)

    # ── Zone indicator ────────────────────────────────────────────────────────

    def _update_zone_bar(self) -> None:
        zone_keys = [z[0] for z in ZONES]
        for i, (key, label, fill_rgba, outline_rgba, hex_col) in enumerate(ZONES):
            lbl = self.zone_label_widgets[i]
            if key in self.zone_rects:
                lbl.config(text=f"✓  {label}", fg=hex_col)
            elif i == self.current_zone_idx:
                lbl.config(text=f"▶  {label}", fg=hex_col)
            else:
                lbl.config(text=f"●  {label}", fg="#444444")

    # ── Navigation ────────────────────────────────────────────────────────────

    def _load_mockup(self) -> None:
        """Load the mockup at current mockup_idx and set starting zone."""
        if self.mockup_idx >= len(self.queue):
            self._show_done()
            return

        filename = self.queue[self.mockup_idx]
        img_path = self.processed_dir / filename

        if not img_path.exists():
            # File disappeared — skip silently
            self.mockup_idx += 1
            self._load_mockup()
            return

        # Header
        self.lbl_filename.config(text=filename)
        self.lbl_progress.config(
            text=f"{self.mockup_idx + 1} / {self.total}  mockups"
        )

        # Load image
        self.orig_image = Image.open(img_path).convert("RGBA")
        iw, ih = self.orig_image.size
        scale = min(MAX_CANVAS_W / iw, MAX_CANVAS_H / ih, 1.0)
        self.scale    = scale
        self.disp_w   = int(iw * scale)
        self.disp_h   = int(ih * scale)
        self.offset_x = (MAX_CANVAS_W - self.disp_w) // 2
        self.offset_y = (MAX_CANVAS_H - self.disp_h) // 2

        # Pre-load any existing zones from metadata
        info = self.metadata.get(filename, {})
        self.zone_rects = {}
        for key, _label, _f, _o, _h in ZONES:
            saved = info.get(key)
            if saved and isinstance(saved, dict):
                self.zone_rects[key] = (
                    saved["x"], saved["y"], saved["w"], saved["h"]
                )

        # Start from first missing zone
        self.current_zone_idx = 0
        for i, (key, _label, _f, _o, _h) in enumerate(ZONES):
            if key not in self.zone_rects:
                self.current_zone_idx = i
                break

        # Clear draw state
        self.drag_start = None
        self.drag_end   = None

        self._update_zone_bar()
        self._redraw()
        self._set_hint()

    def _advance_zone(self) -> None:
        """After saving a zone, move to next missing zone or next mockup."""
        zone_keys = [z[0] for z in ZONES]

        # Find next missing zone after current
        next_zone = None
        for i, key in enumerate(zone_keys):
            if i > self.current_zone_idx and key not in self.zone_rects:
                next_zone = i
                break

        if next_zone is not None:
            self.current_zone_idx = next_zone
            self.drag_start = None
            self.drag_end   = None
            self._update_zone_bar()
            self._redraw()
            self._set_hint()
        else:
            # All zones done → next mockup
            self.mockup_idx += 1
            self.root.after(300, self._load_mockup)

    def _show_done(self) -> None:
        self.canvas.delete("all")
        self.canvas.create_text(
            MAX_CANVAS_W // 2, MAX_CANVAS_H // 2,
            text="✓  All mockups labeled",
            fill="#4caf50",
            font=("Helvetica", 26, "bold"),
        )
        self.lbl_filename.config(text="Done")
        self.lbl_progress.config(
            text=f"{self.total} / {self.total}  mockups",
            fg="#4caf50",
        )
        self.lbl_status.config(text="  [Q] Quit", fg="#555555")
        for lbl in self.zone_label_widgets:
            lbl.config(fg="#333333")

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        if self.orig_image is None:
            return

        try:
            disp = self.orig_image.copy()
            if disp.mode != "RGBA":
                disp = disp.convert("RGBA")
            disp = disp.resize((self.disp_w, self.disp_h), Image.LANCZOS)
            overlay = Image.new("RGBA", (self.disp_w, self.disp_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Draw all saved zones
            for i, (key, _label, fill_rgba, outline_rgba, _hex) in enumerate(ZONES):
                if key not in self.zone_rects:
                    continue
                ox, oy, ow, oh = self.zone_rects[key]
                # Convert original coords → display coords
                px0 = round(ox * self.scale)
                py0 = round(oy * self.scale)
                px1 = round((ox + ow) * self.scale)
                py1 = round((oy + oh) * self.scale)
                draw.rectangle([px0, py0, px1, py1], fill=fill_rgba)
                for t in range(OUTLINE_PX):
                    draw.rectangle(
                        [px0 + t, py0 + t, px1 - t, py1 - t],
                        outline=outline_rgba,
                    )

            # Draw current drag rect (active zone color)
            if self.drag_start and self.drag_end:
                zone_fill    = ZONES[self.current_zone_idx][2]
                zone_outline = ZONES[self.current_zone_idx][3]

                x0c, y0c = self.drag_start
                x1c, y1c = self.drag_end
                px0 = max(0, min(x0c - self.offset_x, self.disp_w))
                py0 = max(0, min(y0c - self.offset_y, self.disp_h))
                px1 = max(0, min(x1c - self.offset_x, self.disp_w))
                py1 = max(0, min(y1c - self.offset_y, self.disp_h))

                if px0 != px1 and py0 != py1:
                    rx0, ry0 = min(px0, px1), min(py0, py1)
                    rx1, ry1 = max(px0, px1), max(py0, py1)
                    draw.rectangle([rx0, ry0, rx1, ry1], fill=zone_fill)
                    for t in range(OUTLINE_PX):
                        draw.rectangle(
                            [rx0 + t, ry0 + t, rx1 - t, ry1 - t],
                            outline=zone_outline,
                        )

            disp = Image.alpha_composite(disp, overlay)
            self.tk_image = ImageTk.PhotoImage(disp.convert("RGB"))
            self.canvas.image = self.tk_image  # prevent garbage collection
            self.canvas.delete("all")
            self.canvas.create_image(
                self.offset_x, self.offset_y,
                anchor=tk.NW,
                image=self.tk_image,
            )
        except Exception as exc:
            import traceback
            print(f"[label_tool] _redraw error: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    # ── Mouse events ─────────────────────────────────────────────────────────

    def _on_press(self, event: tk.Event) -> None:
        self.drag_start = (event.x, event.y)
        self.drag_end   = None

    def _on_drag(self, event: tk.Event) -> None:
        self.drag_end = (event.x, event.y)
        self._redraw()

    def _on_release(self, event: tk.Event) -> None:
        self.drag_end = (event.x, event.y)
        self._redraw()

    # ── Key events ────────────────────────────────────────────────────────────

    def _on_key(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        if key == "s":
            self._action_save()
        elif key == "r":
            self._action_redo()
        elif key == "n":
            self._action_skip()
        elif key == "q":
            self._save_metadata()
            self.root.destroy()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _action_save(self) -> None:
        if self.mockup_idx >= len(self.queue):
            return

        if not (self.drag_start and self.drag_end):
            self._set_status("  ⚠  Draw a rectangle first, then press S", "#e07040")
            self.root.after(2000, self._set_hint)
            return

        filename = self.queue[self.mockup_idx]
        orig_w, orig_h = self.orig_image.size

        x0 = (self.drag_start[0] - self.offset_x) / self.scale
        y0 = (self.drag_start[1] - self.offset_y) / self.scale
        x1 = (self.drag_end[0]   - self.offset_x) / self.scale
        y1 = (self.drag_end[1]   - self.offset_y) / self.scale

        rx = max(0.0, min(min(x0, x1), orig_w))
        ry = max(0.0, min(min(y0, y1), orig_h))
        rw = min(abs(x1 - x0), orig_w - rx)
        rh = min(abs(y1 - y0), orig_h - ry)

        zone_key   = ZONES[self.current_zone_idx][0]
        zone_label = ZONES[self.current_zone_idx][1]
        zone_hex   = ZONES[self.current_zone_idx][4]

        rect = (round(rx), round(ry), round(rw), round(rh))
        self.zone_rects[zone_key] = rect

        # Persist immediately
        if filename not in self.metadata:
            self.metadata[filename] = {}
        self.metadata[filename][zone_key] = {
            "x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3],
        }
        self._save_metadata()

        self._update_zone_bar()
        self._set_status(
            f"  ✓  {zone_label} saved  ({rect[2]}×{rect[3]} px)  →  next zone",
            zone_hex,
        )
        self.root.after(600, self._advance_zone)

    def _action_redo(self) -> None:
        """Clear current drag and let user draw again."""
        self.drag_start = None
        self.drag_end   = None
        self._redraw()
        self._set_hint()

    def _action_skip(self) -> None:
        """Skip entire mockup, no zones saved."""
        if self.mockup_idx < len(self.queue):
            self.mockup_idx += 1
            self._load_mockup()

    # ── Status helpers ────────────────────────────────────────────────────────

    def _hint(self) -> str:
        if self.mockup_idx >= len(self.queue):
            return "  [Q] Quit"
        label = ZONES[self.current_zone_idx][1]
        hex_col = ZONES[self.current_zone_idx][4]
        return (
            f"  Draw  {label}  area"
            "    ▸  [S] Save zone"
            "    ▸  [R] Redo"
            "    ▸  [N] Skip mockup"
            "    ▸  [Q] Quit"
        )

    def _set_hint(self) -> None:
        if self.mockup_idx >= len(self.queue):
            return
        hex_col = ZONES[self.current_zone_idx][4]
        self.lbl_status.config(text=self._hint(), fg="#555555")

    def _set_status(self, text: str, color: str) -> None:
        self.lbl_status.config(text=text, fg=color)


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="3-zone mockup labeler — labels LOGO, TEXT, SURFACE areas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Scans --processed-dir for images, queues those missing any zone.\n\n"
            "Controls:\n"
            "  Click + drag   Draw rectangle for the active zone\n"
            "  S              Save zone & advance\n"
            "  R              Redo current drawing\n"
            "  N              Skip this mockup\n"
            "  Q              Quit and save"
        ),
    )
    parser.add_argument(
        "--processed-dir",
        default=str(DEFAULT_PROCESSED),
        metavar="PATH",
        help=f"Directory of processed mockup images  (default: {DEFAULT_PROCESSED})",
    )
    parser.add_argument(
        "--metadata",
        default=str(DEFAULT_METADATA),
        metavar="PATH",
        help=f"Path to metadata.json  (default: {DEFAULT_METADATA})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    processed_dir = Path(args.processed_dir)
    metadata_path = Path(args.metadata)

    if not processed_dir.exists():
        print(f"Error: processed directory not found: {processed_dir}")
        print("Pass --processed-dir PATH to specify a different location.")
        sys.exit(1)

    root = tk.Tk()
    app  = LabelTool(root, processed_dir=processed_dir, metadata_path=metadata_path)

    if not app.queue:
        root.destroy()
        print("Nothing to label — all mockups in the processed dir already have all 3 zones.")
        sys.exit(0)

    print(f"Queued {app.total} mockup(s) to label in {processed_dir}")
    root.mainloop()


if __name__ == "__main__":
    main()
