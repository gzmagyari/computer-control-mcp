# Screenshot Format & Size Optimization

Benchmark results for full-screen (1920x1080) capture with different format, quality, and color mode combinations.

## Quick Recommendations

| Use Case | Settings | Size | Notes |
|----------|----------|------|-------|
| **Smallest possible** | `webp`, grayscale, q=30 | **59 KB** | Good for bandwidth-limited MCP calls |
| **Best balance (color)** | `webp`, color, q=30 | **67 KB** | 6x smaller than PNG, color preserved |
| **Good quality color** | `webp`, color, q=70 | **92 KB** | Barely noticeable quality loss |
| **Default (no options)** | `png`, color | **420 KB** | Lossless, largest |

## Key Takeaways

- **WebP is the clear winner** — 4-7x smaller than PNG for color, 2-3x smaller than JPEG
- **Grayscale saves ~10-15%** over color in webp/jpeg (worth it if color isn't needed)
- **Black & white ("bw") is a trap** — it actually produces *much larger* files (700KB-1.5MB) because dithering creates noisy patterns that compress poorly
- **Quality below 30 has diminishing returns** — q=30 webp color is already only 67 KB
- **PNG ignores quality setting** — it's always lossless

## Full Benchmark (1920x1080, sorted by size)

```
Format  Color       Quality    Size
──────  ──────────  ───────    ─────────
webp    grayscale   q=30        59.0 KB
webp    color       q=30        66.5 KB
webp    grayscale   q=50        69.3 KB
webp    grayscale   q=70        77.9 KB
webp    color       q=50        80.2 KB
webp    grayscale   q=80        89.2 KB
webp    color       q=70        92.0 KB
jpeg    grayscale   q=30        97.9 KB
webp    color       q=80       107.7 KB
jpeg    color       q=30       113.1 KB
webp    grayscale   q=90       117.4 KB
jpeg    grayscale   q=50       126.6 KB
jpeg    color       q=50       144.9 KB
webp    color       q=90       147.1 KB
jpeg    grayscale   q=70       160.4 KB
png     bw          q=n/a      178.3 KB
jpeg    color       q=70       183.1 KB
jpeg    grayscale   q=80       188.5 KB
png     grayscale   q=n/a      198.7 KB
jpeg    color       q=80       217.1 KB
jpeg    grayscale   q=90       251.4 KB
jpeg    color       q=90       292.5 KB
png     color       q=n/a      420.2 KB
jpeg    bw          q=30       670.6 KB  ← avoid
webp    bw          q=30       794.6 KB  ← avoid
jpeg    bw          q=50       840.0 KB  ← avoid
webp    bw          q=50       885.1 KB  ← avoid
```

## MCP Tool Usage

The format/quality/color options apply to both the MCP Image object returned to the agent AND the file saved to disk (when `save_to_downloads=True`). This means the agent receives the optimized image directly — a webp q=30 screenshot sends only 67 KB over MCP instead of 420 KB PNG.

```python
# Smallest color screenshot (67 KB vs 420 KB default)
take_screenshot(image_format="webp", quality=30)

# Smallest grayscale (59 KB)
take_screenshot(image_format="webp", quality=30, color_mode="grayscale")

# Good quality for visual inspection (92 KB)
take_screenshot(image_format="webp", quality=70)

# Window-only (even smaller due to smaller capture area)
take_screenshot(title_pattern="Notepad", image_format="webp", quality=30)

# Also save to disk
take_screenshot(image_format="webp", quality=30, save_to_downloads=True)
```
