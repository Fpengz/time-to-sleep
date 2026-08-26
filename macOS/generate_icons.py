#!/usr/bin/env python3
"""
Time-to-Sleep macOS App Icon and Menu Icon Generator

Generates high-resolution macOS Big Sur / Sonoma style squircle icons,
builds the AppIcon.iconset, compiles AppIcon.icns with iconutil, and
creates template MenuBar icons.
"""

import argparse
import os
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFilter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
BRAIN_DIR = "/Users/zhoufuwang/.gemini/antigravity-cli/brain/c4c8a874-533e-445a-a251-ea8348bb0edf"

CONCEPTS = {
    "1": {
        "name": "observatory_lunar_gauge",
        "title": "Observatory Lunar Gauge (Recommended)",
        "source": os.path.join(BRAIN_DIR, "app_icon_observatory_lunar_gauge_1787679882667.jpg"),
        "crop": (188, 186, 834, 832),
        "radius": 140,
    },
    "2": {
        "name": "celestial_chronometer",
        "title": "Celestial Chronometer",
        "source": os.path.join(BRAIN_DIR, "app_icon_celestial_chronometer_1787679901512.jpg"),
        "crop": (111, 111, 911, 911),
        "radius": 170,
    },
    "3": {
        "name": "minimal_astral_radar",
        "title": "Minimal Astral Radar",
        "source": os.path.join(BRAIN_DIR, "app_icon_minimal_astral_radar_1787679918804.jpg"),
        "crop": (191, 188, 833, 834),
        "radius": 140,
    },
    "4": {
        "name": "observatory_dark_glass",
        "title": "Observatory Dark Glass",
        "source": os.path.join(BRAIN_DIR, "app_icon_observatory_dark_glass_1787679935486.jpg"),
        "crop": (106, 107, 915, 914),
        "radius": 170,
    },
}


def create_squircle_mask(size, radius):
    scale = 4
    mask_size = (size[0] * scale, size[1] * scale)
    mask = Image.new("L", mask_size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (mask_size[0] - 1, mask_size[1] - 1)], radius=radius * scale, fill=255)
    return mask.resize(size, Image.Resampling.LANCZOS)


def generate_app_icon(concept_key="1", custom_img_path=None):
    if custom_img_path:
        img_path = custom_img_path
        crop_box = (0, 0, 1024, 1024)
        radius = 185
    else:
        concept = CONCEPTS.get(concept_key, CONCEPTS["1"])
        img_path = concept["source"]
        crop_box = concept["crop"]
        radius = concept["radius"]

    print(f"🎨 Generating macOS App Icon using Concept {concept_key} ({img_path})...")

    img = Image.open(img_path).convert("RGBA")
    cropped = img.crop(crop_box).resize((824, 824), Image.Resampling.LANCZOS)
    mask = create_squircle_mask((824, 824), radius)
    cropped.putalpha(mask)

    # Standard macOS 1024x1024 canvas with subtle shadow
    canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    shadow_mask = mask.resize((824, 824), Image.Resampling.LANCZOS)
    shadow = Image.new("RGBA", (824, 824), (0, 0, 0, 95))
    shadow.putalpha(shadow_mask)
    shadow_canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    shadow_canvas.paste(shadow, (100, 118))
    shadow_canvas = shadow_canvas.filter(ImageFilter.GaussianBlur(radius=22))

    canvas.alpha_composite(shadow_canvas)
    canvas.paste(cropped, (100, 100), cropped)

    # Save master icon.png in macOS/
    icon_png_path = os.path.join(SCRIPT_DIR, "icon.png")
    cropped.save(icon_png_path, "PNG")
    print(f"  ✓ Saved squircle icon to {icon_png_path}")

    # Generate .iconset
    iconset_dir = os.path.join(SCRIPT_DIR, "AppIcon.iconset")
    os.makedirs(iconset_dir, exist_ok=True)
    sizes = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for filename, sz in sizes:
        resized = canvas.resize((sz, sz), Image.Resampling.LANCZOS)
        resized.save(os.path.join(iconset_dir, filename), "PNG")
    print(f"  ✓ Generated AppIcon.iconset files in {iconset_dir}")

    # Compile with iconutil
    icns_path = os.path.join(SCRIPT_DIR, "AppIcon.icns")
    res = subprocess.run(["iconutil", "-c", "icns", iconset_dir, "-o", icns_path], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"  ✓ Compiled AppIcon.icns successfully ({os.path.getsize(icns_path):,} bytes)")
    else:
        print(f"  ✗ Error compiling AppIcon.icns: {res.stderr}", file=sys.stderr)


def generate_menu_icon(variant="lunar_gauge"):
    print("🌙 Generating macOS Menu Bar Template Icon...")
    size = 256
    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)

    # Outer arc
    d.arc([24, 24, 232, 232], start=45, end=315, fill=255, width=20)
    # Dot at top-right
    d.ellipse([186, 44, 210, 68], fill=255)
    # Crescent moon inside
    moon = Image.new("L", (size, size), 0)
    dm = ImageDraw.Draw(moon)
    dm.ellipse([64, 60, 188, 184], fill=255)
    dm.ellipse([92, 48, 208, 164], fill=0)

    import numpy as np

    arr = np.maximum(np.array(img), np.array(moon))
    v_mask = Image.fromarray(arr)

    v = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    black = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    v.paste(black, (0, 0), v_mask)

    menu_icon_path = os.path.join(SCRIPT_DIR, "MenuIcon.png")
    v.resize((32, 32), Image.Resampling.LANCZOS).save(menu_icon_path, "PNG")
    print(f"  ✓ Saved MenuIcon.png (32x32 template) to {menu_icon_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate Time-to-Sleep macOS App Icons")
    parser.add_argument("--concept", choices=["1", "2", "3", "4"], default="1", help="Choose design concept (1-4)")
    parser.add_argument("--custom-image", help="Path to custom 1024x1024 icon image")
    parser.add_argument("--menu-only", action="store_true", help="Generate MenuIcon.png only")
    args = parser.parse_args()

    if not args.menu_only:
        generate_app_icon(concept_key=args.concept, custom_img_path=args.custom_image)
    generate_menu_icon()
    print("\n✨ All macOS icons generated successfully!")


if __name__ == "__main__":
    main()
