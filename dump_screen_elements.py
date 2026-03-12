#!/usr/bin/env python3
"""
Dump all screen elements with bounding boxes from two sources:
  1. AT-SPI accessibility tree (widgets, buttons, menus, etc.)
  2. Tesseract OCR (visible text regions from screenshot)

Outputs:
  - screen_elements.json  — structured element data
  - screen_elements.png   — annotated screenshot with bounding boxes
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

OUTPUT_DIR = Path("/workspace")
SCREENSHOT = OUTPUT_DIR / "screenshot.png"


# ── AT-SPI ──────────────────────────────────────────────────────────────

def collect_atspi_elements(node, depth=0, max_depth=40) -> list[dict]:
    """Flatten the AT-SPI tree into a list of elements with bounds."""
    if node is None or depth > max_depth:
        return []

    elements: list[dict] = []

    try:
        role = node.get_role_name()
    except Exception:
        role = "unknown"

    try:
        name = node.get_name() or ""
    except Exception:
        name = ""

    try:
        text_iface = node.get_text_iface()
        if text_iface:
            cc = text_iface.get_character_count()
            text = text_iface.get_text(0, min(cc, 500))
        else:
            text = ""
    except Exception:
        text = ""

    bounds = None
    try:
        comp = node.get_component_iface()
        if comp:
            r = comp.get_extents(Atspi.CoordType.SCREEN)
            if r.width > 0 and r.height > 0 and r.x >= 0 and r.y >= 0:
                bounds = {"x": r.x, "y": r.y, "w": r.width, "h": r.height}
    except Exception:
        pass

    if bounds:
        entry = {
            "source": "atspi",
            "role": role,
            "bounds": bounds,
        }
        if name:
            entry["name"] = name
        if text:
            entry["text"] = text
        elements.append(entry)

    try:
        for i in range(node.get_child_count()):
            try:
                child = node.get_child_at_index(i)
                elements.extend(collect_atspi_elements(child, depth + 1, max_depth))
            except Exception:
                continue
    except Exception:
        pass

    return elements


def get_atspi_elements() -> list[dict]:
    desktop = Atspi.get_desktop(0)
    all_elements = []
    for i in range(desktop.get_child_count()):
        try:
            app = desktop.get_child_at_index(i)
            all_elements.extend(collect_atspi_elements(app))
        except Exception:
            continue
    return all_elements


# ── OCR ─────────────────────────────────────────────────────────────────

def take_screenshot():
    subprocess.run(
        ["import", "-window", "root", str(SCREENSHOT)],
        env={"DISPLAY": ":1", "HOME": str(Path.home())},
        check=True,
    )


def get_ocr_elements() -> list[dict]:
    """Run Tesseract TSV and parse word-level bounding boxes."""
    tsv_path = OUTPUT_DIR / "ocr_output.tsv"
    subprocess.run(
        ["tesseract", str(SCREENSHOT), str(OUTPUT_DIR / "ocr_output"),
         "-c", "tessedit_create_tsv=1"],
        capture_output=True,
    )

    elements = []
    with open(tsv_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            text = row.get("text", "").strip()
            conf = float(row.get("conf", -1))
            level = int(row.get("level", 0))
            if not text or conf < 50 or level != 5:
                continue
            elements.append({
                "source": "ocr",
                "role": "text",
                "text": text,
                "confidence": round(conf, 1),
                "bounds": {
                    "x": int(row["left"]),
                    "y": int(row["top"]),
                    "w": int(row["width"]),
                    "h": int(row["height"]),
                },
            })
    return elements


# ── Visualization ───────────────────────────────────────────────────────

def draw_boxes(atspi_elements: list[dict], ocr_elements: list[dict]):
    img = Image.open(SCREENSHOT).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    except Exception:
        font = ImageFont.load_default()

    # Draw AT-SPI elements in green
    for el in atspi_elements:
        b = el["bounds"]
        draw.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]],
                        outline="lime", width=1)
        label = f'{el["role"]}'
        if el.get("name"):
            label += f': {el["name"][:30]}'
        draw.text((b["x"] + 2, b["y"] - 11), label, fill="lime", font=font)

    # Draw OCR elements in cyan
    for el in ocr_elements:
        b = el["bounds"]
        draw.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]],
                        outline="cyan", width=1)

    out = OUTPUT_DIR / "screen_elements.png"
    img.save(out)
    return out


# ── Main ────────────────────────────────────────────────────────────────

def main():
    print("Taking screenshot...")
    take_screenshot()

    print("Collecting AT-SPI elements...")
    atspi_elements = get_atspi_elements()
    print(f"  Found {len(atspi_elements)} AT-SPI elements with bounds")

    print("Running OCR...")
    ocr_elements = get_ocr_elements()
    print(f"  Found {len(ocr_elements)} OCR text regions (conf >= 50)")

    result = {
        "screen_size": {"width": 1280, "height": 720},
        "atspi_elements": atspi_elements,
        "ocr_elements": ocr_elements,
        "total": len(atspi_elements) + len(ocr_elements),
    }

    json_path = OUTPUT_DIR / "screen_elements.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"Wrote {result['total']} elements to {json_path}")

    print("Drawing annotated screenshot...")
    img_path = draw_boxes(atspi_elements, ocr_elements)
    print(f"Wrote annotated image to {img_path}")


if __name__ == "__main__":
    main()
