"""Compose the e-ink frame from one or more recent birds and dither it to the
Spectra-6 6-color palette.

- 1 bird  -> full-bleed plate with a caption bar (common + scientific + time).
- 2..N    -> a 2-column grid of cells, each a plate + a small common-name strip.

Kept free of hardware dependencies so it runs anywhere (laptop dry-runs).
A "bird" is a dict: {common, scientific, when, plate_path (Path | None)}.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# Waveshare 7.3" E6 (Spectra 6) palette: black, white, red, yellow, blue, green.
SPECTRA6_PALETTE = [
    (0, 0, 0),        # black
    (255, 255, 255),  # white
    (255, 0, 0),      # red
    (255, 255, 0),    # yellow
    (0, 0, 255),      # blue
    (0, 255, 0),      # green
]

_CREAM = (245, 240, 225)


def _palette_image() -> Image.Image:
    pal_img = Image.new("P", (1, 1))
    flat: list[int] = []
    for r, g, b in SPECTRA6_PALETTE:
        flat += [r, g, b]
    flat += [0, 0, 0] * (256 - len(SPECTRA6_PALETTE))
    pal_img.putpalette(flat)
    return pal_img


_FONT_WARNED = False


def _font(fonts_dir: Path, size: int) -> ImageFont.ImageFont:
    candidates = [
        fonts_dir / "caption.ttf",                                    # bundled (preferred)
        Path("/System/Library/Fonts/Supplemental/Georgia.ttf"),       # macOS dev box
        Path("/Library/Fonts/Georgia.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),     # Linux (fonts-dejavu)
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                # OSError (bad font) or ImportError (Pillow built without/can't
                # load libfreetype) — try the next candidate, then warn below.
                continue
    # No scalable font anywhere: Pillow's bitmap default ignores `size`, so text
    # renders tiny and unscalable. Warn once so this never hides silently again.
    global _FONT_WARNED
    if not _FONT_WARNED:
        _FONT_WARNED = True
        print("[renderer] WARNING: no scalable TTF font found; using Pillow's "
              "fixed bitmap font (text will be tiny). Bundle one at "
              "wall-node/fonts/caption.ttf or `apt install fonts-dejavu`.")
    return ImageFont.load_default()


def _fit_font(draw, text, fonts_dir, max_width, start_size, min_size=10):
    """Largest font (<= start_size) whose text fits max_width, else min_size."""
    size = start_size
    while size > min_size:
        font = _font(fonts_dir, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _font(fonts_dir, min_size)


def _fit_font_box(draw, text, fonts_dir, max_width, max_height, min_size=10):
    """Largest font whose *rendered* text fits both max_width and max_height.

    Sizes by the actual glyph bounding box (not the nominal point size), so the
    text fills the available height regardless of the font's internal metrics —
    i.e. as large as possible within a fixed-height caption bar.
    """
    size = max(min_size + 1, int(max_height * 1.7))
    while size > min_size:
        font = _font(fonts_dir, size)
        b = draw.textbbox((0, 0), text, font=font)
        if (b[2] - b[0]) <= max_width and (b[3] - b[1]) <= max_height:
            return font
        size -= 2
    return _font(fonts_dir, min_size)


def _trim_to_subject(img: Image.Image, *, erode: int = 7, density: float = 0.04,
                     pad_frac: float = 0.06, max_cut: float = 0.34) -> Image.Image:
    """Crop a plate's empty cream margin down to the illustration.

    Audubon plates vary: some birds fill the sheet, others sit in a big cream
    field with engraved captions, plate numbers, and a ragged scan edge. We
    build a content mask (saturated *or* dark pixels), erode it to remove thin
    features (the scan-edge frame, caption text, specks), then keep the band of
    rows/columns whose content density clears a threshold. A `max_cut` clamp
    guarantees we never shave more than that fraction off any one side, so a
    full-sheet composition is left essentially intact and we can't over-crop a
    bird. Returns the original if the mask is empty.
    """
    img = img.convert("RGB")
    W, Hh = img.size
    _, S, V = img.convert("HSV").split()
    mask = ImageChops.lighter(S.point(lambda p: 255 if p > 55 else 0),
                              V.point(lambda p: 255 if p < 160 else 0))
    mask = mask.filter(ImageFilter.MinFilter(erode))
    col = list(mask.resize((W, 1), Image.BOX).get_flattened_data())
    row = list(mask.resize((1, Hh), Image.BOX).get_flattened_data())
    cs = [i for i, v in enumerate(col) if v > 255 * density]
    rs = [i for i, v in enumerate(row) if v > 255 * density]
    if not cs or not rs:
        return img
    l, r, t, b = cs[0], cs[-1], rs[0], rs[-1]
    pw, ph = round(pad_frac * W), round(pad_frac * Hh)
    l, t = max(0, l - pw), max(0, t - ph)
    r, b = min(W, r + pw), min(Hh, b + ph)
    # Clamp: never cut more than max_cut off any single side.
    l, t = min(l, int(W * max_cut)), min(t, int(Hh * max_cut))
    r, b = max(r, int(W * (1 - max_cut))), max(b, int(Hh * (1 - max_cut)))
    return img.crop((l, t, r, b))


def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale + center-crop so the image fills WxH without distortion."""
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    new = img.resize((round(img.width * scale), round(img.height * scale)))
    left = (new.width - w) // 2
    top = (new.height - h) // 2
    return new.crop((left, top, left + w, top + h))


# --- Subject-aware cropping -------------------------------------------------
# Precomputed (offline, via tools/compute_crops.py using rembg salient-object
# segmentation) bounding box per plate, so we crop to the bird instead of a
# blind center-crop. crops.json: {"boxes": {"<filename>": [x, y, w, h]}}.
_CROPS_PATH = Path(__file__).resolve().parent / "crops.json"
_CROPS_CACHE: dict | None = None


def _crops() -> dict:
    global _CROPS_CACHE
    if _CROPS_CACHE is None:
        try:
            _CROPS_CACHE = json.loads(_CROPS_PATH.read_text()).get("boxes", {})
        except Exception:
            _CROPS_CACHE = {}
    return _CROPS_CACHE


def _subject_box(plate_path, img: Image.Image):
    """Cached subject box [x, y, w, h] for this plate, clamped to the image, or
    None if there's no cached box (caller falls back)."""
    box = _crops().get(Path(plate_path).name)
    if not box:
        return None
    x, y, w, h = box
    x = max(0, min(int(x), img.width - 1))
    y = max(0, min(int(y), img.height - 1))
    w = max(1, min(int(w), img.width - x))
    h = max(1, min(int(h), img.height - y))
    return (x, y, w, h)


def _expand_to_aspect(box, W, H, target_w, target_h):
    """Grow a subject box outward to the target aspect (never shrink, so the
    subject is never clipped), centered and clamped to the image."""
    x, y, w, h = box
    ar = target_w / target_h
    cx, cy = x + w / 2, y + h / 2
    if w / h < ar:
        w = h * ar
    else:
        h = w / ar
    w, h = min(w, W), min(h, H)
    cx = min(max(cx, w / 2), W - w / 2)
    cy = min(max(cy, h / 2), H - h / 2)
    return (round(cx - w / 2), round(cy - h / 2), round(w), round(h))


def _smart_fill(plate_path, img: Image.Image, w: int, h: int) -> Image.Image:
    """Frame the plate's subject into WxH without distortion.

    Expand the cached subject box to WxH's aspect and crop. If that box reached
    the exact target aspect (the subject was small enough to grow around), resize
    to fill. If it couldn't — a tall/wide subject that hit the image edge — the
    cropped region is off-aspect, so *contain* it (preserve proportions, pad with
    white) rather than stretch it. Falls back to a center cover-crop when no box
    is cached."""
    img = img.convert("RGB")
    box = _subject_box(plate_path, img)
    if box is None:
        return _fit_cover(img, w, h)
    ex, ey, ew, eh = _expand_to_aspect(box, img.width, img.height, w, h)
    crop = img.crop((ex, ey, ex + ew, ey + eh))
    if abs(crop.width / crop.height - w / h) < 0.02:
        return crop.resize((w, h))                       # reached target aspect: fill
    # Off-aspect: contain on white so the whole subject shows, undistorted.
    scale = min(w / crop.width, h / crop.height)
    fitted = crop.resize((max(1, round(crop.width * scale)),
                          max(1, round(crop.height * scale))))
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
    return canvas


def _no_plate_panel(width, height, fonts_dir) -> Image.Image:
    panel = Image.new("RGB", (width, height), _CREAM)
    draw = ImageDraw.Draw(panel)
    msg = "No plate"
    font = _font(fonts_dir, max(14, height // 8))
    bbox = draw.textbbox((0, 0), msg, font=font)
    draw.text(((width - (bbox[2] - bbox[0])) // 2, (height - (bbox[3] - bbox[1])) // 2),
              msg, fill=(120, 110, 90), font=font)
    return panel


def _compose_single(width, height, bird, fonts_dir, caption_scale=1.0) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    # Single-row name bar (names sit side by side, not stacked), so it can stay
    # short while the text is large. Scales with caption_scale, capped at 1/4.
    caption_h = min(int(max(52, height // 10) * caption_scale), height // 4)
    art_h = height - caption_h

    plate = bird.get("plate_path")
    if plate and Path(plate).exists():
        canvas.paste(_smart_fill(plate, Image.open(plate), width, art_h), (0, 0))
    else:
        canvas.paste(_no_plate_panel(width, art_h, fonts_dir), (0, 0))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, art_h, width, height], fill=(0, 0, 0))

    common = (bird.get("common") or "").strip()
    sci = (bird.get("scientific") or "").strip()
    when = bird.get("when")
    has_common = bool(common) and common.lower() != sci.lower()

    # Line 1 = common name (large). Line 2 = scientific name (+ time). When there
    # is no distinct common name, the scientific name becomes the title and the
    # second line is just the time — so the name is never printed twice.
    title = common if has_common else sci
    if has_common:
        subtitle = f"{sci}   ·   {when}" if when else sci
    else:
        subtitle = str(when) if when else ""

    # Horizontal layout: common name large on the left, scientific name smaller
    # and right-aligned, both vertically centered — uses the panel's width
    # instead of stacking the two lines vertically. Reserve the scientific name's
    # width on the right first so the common name can't overrun it.
    pad, gap = 24, 24
    if subtitle:
        sci_font = _fit_font_box(draw, subtitle, fonts_dir, (width - 2 * pad) * 2 // 5,
                                 caption_h * 50 // 100, min_size=12)
        sci_w = draw.textlength(subtitle, font=sci_font)
    else:
        sci_font, sci_w = None, 0
    name_avail = width - 2 * pad - (sci_w + gap if sci_font else 0)
    # Fill ~84% of the bar height so the name is as large as the bar allows.
    name_font = _fit_font_box(draw, title, fonts_dir, name_avail,
                              caption_h * 84 // 100, min_size=18)

    nb = draw.textbbox((0, 0), title, font=name_font)
    ny = art_h + (caption_h - (nb[3] - nb[1])) // 2 - nb[1]
    draw.text((pad, ny), title, fill=(255, 255, 255), font=name_font)
    if sci_font:
        sb = draw.textbbox((0, 0), subtitle, font=sci_font)
        sy = art_h + (caption_h - (sb[3] - sb[1])) // 2 - sb[1]
        draw.text((width - pad - sci_w, sy), subtitle, fill=(220, 220, 220), font=sci_font)
    return canvas


def _draw_name_bar(canvas, x0, y0, w, h, names, fonts_dir) -> None:
    """One shared caption bar listing all bird names, centered, 1–2 lines."""
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([x0, y0, x0 + w, y0 + h], fill=(0, 0, 0))
    sep = "   ·   "
    text = sep.join(names)
    max_w = w - 28

    font = _fit_font(draw, text, fonts_dir, max_w, min(30, h * 3 // 5), min_size=12)
    lines = [text]
    if draw.textlength(text, font=font) > max_w:
        mid = (len(names) + 1) // 2  # balance names across two lines
        lines = [sep.join(names[:mid]), sep.join(names[mid:])]
        widest = max(lines, key=len)
        font = _fit_font(draw, widest, fonts_dir, max_w, min(24, h * 2 // 5), min_size=12)

    line_h = font.size + 4
    ty = y0 + (h - line_h * len(lines)) // 2
    for line in lines:
        lw = draw.textlength(line, font=font)
        draw.text((x0 + (w - lw) // 2, ty), line, fill=(255, 255, 255), font=font)
        ty += line_h


def compose_birds(width, height, birds, fonts_dir, trim=True, caption_scale=1.0) -> Image.Image:
    """Compose 1..N birds into a single RGB frame (caller dithers via to_panel).

    Multiple birds: plates trimmed to their illustration and grouped centered in
    the upper area, with one shared name bar listing all of them along the
    bottom. `trim` toggles the margin crop. `caption_scale` enlarges the
    single-bird name bar.
    """
    birds = list(birds)
    if not birds:
        return Image.new("RGB", (width, height), (255, 255, 255))
    if len(birds) == 1:
        return _compose_single(width, height, birds[0], fonts_dir, caption_scale)

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    bar_h = max(56, height // 8)
    art_h = height - bar_h
    gap, vpad = 16, 12

    # Open plates and note each one's aspect ratio (default for missing plates).
    plates: list[Image.Image | None] = []
    aspects: list[float] = []
    for bird in birds:
        plate = bird.get("plate_path")
        if plate and Path(plate).exists():
            im = Image.open(plate)
            if trim:
                box = _subject_box(plate, im)        # precomputed rembg box
                if box is not None:
                    x, y, w, h = box
                    im = im.convert("RGB").crop((x, y, x + w, y + h))
                else:
                    im = _trim_to_subject(im)         # fallback: density trim
            plates.append(im)
            aspects.append(im.width / im.height)
        else:
            plates.append(None)
            aspects.append(0.7)  # typical tall Audubon-plate aspect

    # Scale every plate to one shared height so they line up; cap that height so
    # the packed row fits the panel width, then center the block both ways.
    n = len(birds)
    avail_w = width - gap * (n - 1) - 2 * vpad
    row_h = int(min(art_h - 2 * vpad, avail_w / max(sum(aspects), 0.01)))
    row_h = max(1, row_h)

    sized = []
    for im, aspect in zip(plates, aspects):
        w_i = max(1, int(row_h * aspect))
        sized.append(im.resize((w_i, row_h)) if im is not None
                     else _no_plate_panel(w_i, row_h, fonts_dir))

    total_w = sum(s.width for s in sized) + gap * (n - 1)
    x = (width - total_w) // 2
    y = (art_h - row_h) // 2
    for s in sized:
        canvas.paste(s, (x, y))
        x += s.width + gap

    names = [b.get("common") or b.get("scientific") or "" for b in birds]
    _draw_name_bar(canvas, 0, art_h, width, bar_h, names, fonts_dir)
    return canvas


# --- kachō-e cutout collage --------------------------------------------------
# Transparent kachō-e cutouts (wall-node/cutouts/, built by tools/kachoe/) are
# nested into an organic cluster, AvianVisitors-style: each bird spirals out from
# the centre and lands at the closest position where its silhouette doesn't
# collide with an already-placed one, so wings cradle tails instead of bboxes
# touching. Ported from their apt.js maskPack; the collision grid is vectorised
# with numpy so it's fast enough on the Pi Zero W (armv6l). Sized by recency
# (most-recent bird largest), on a flat white ground that dithers cleanly on the
# 6-colour panel. Returns None if numpy is missing or no bird has a cutout, so
# the caller can fall back to the plate renderer.


def _slugify(sci: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sci.lower()).strip("-")


def cutout_for(cutouts_dir: Path, scientific: str, pose: int) -> Path | None:
    """Path to a species' cutout for a pose (1 perched, 2 flight), or None."""
    slug = _slugify(scientific)
    name = f"{slug}.png" if pose == 1 else f"{slug}-{pose}.png"
    path = cutouts_dir / name
    return path if path.exists() else None


def _pick_pose(cutouts_dir: Path, scientific: str, fly_prob: float) -> int:
    """Perched by default; rarely flight (fly_prob) when a flight cutout exists.
    Deterministic per species so the same bird doesn't flip pose between
    refreshes within its window."""
    if fly_prob > 0 and cutout_for(cutouts_dir, scientific, 2) is not None:
        h = int(hashlib.sha1(scientific.lower().encode()).hexdigest()[:8], 16)
        if (h % 1000) / 1000.0 < fly_prob:
            return 2
    return 1


def _dilate(np, mask, k: int):
    """4-connected dilation by k cells, growing the array by k on every side so
    the gap sits *around* the silhouette."""
    if k <= 0:
        return mask
    mh, mw = mask.shape
    out = np.zeros((mh + 2 * k, mw + 2 * k), dtype=bool)
    out[k:k + mh, k:k + mw] = mask
    for _ in range(k):
        out[1:, :] |= out[:-1, :]
        out[:-1, :] |= out[1:, :]
        out[:, 1:] |= out[:, :-1]
        out[:, :-1] |= out[:, 1:]
    return out


def _grid_masks(np, tile, stride: int, pad: int):
    """Build a tile's collision mask (at grid resolution, from its alpha) and a
    pad-dilated stamp mask. Recomputed whenever the tile is resized."""
    mw = max(1, int(round(tile["fullW"] / stride)))
    mh = max(1, int(round(tile["fullH"] / stride)))
    alpha = tile["img"].getchannel("A").resize((mw, mh), Image.BOX)
    arr = np.frombuffer(alpha.tobytes(), dtype=np.uint8).reshape(mh, mw) > 40
    tile["gm"] = arr
    tile["gmp"] = _dilate(np, arr, pad)


def _mask_pack(np, tiles, W, H, xbias, ybias, pad, stride):
    """Assign each tile an (x, y) top-left so silhouettes nest without colliding.
    Largest first from the centre; each subsequent tile spirals out on elliptical
    rings to the closest free spot near the cluster's centre of mass."""
    GW, GH = W // stride + 2, H // stride + 2
    grid = np.zeros((GH, GW), dtype=bool)
    for t in tiles:
        _grid_masks(np, t, stride, pad)
    tiles.sort(key=lambda t: -(t["fullW"] * t["fullH"]))

    seed = [0x9E3779B9]

    def rnd():
        seed[0] = (seed[0] * 16807) % 2147483647
        return seed[0] / 2147483647

    cx, cy = W / 2, H / 2
    placed = []
    for i, t in enumerate(tiles):
        gm = t["gm"]
        mh, mw = gm.shape

        def collide(px, py):
            gx, gy = int(px // stride), int(py // stride)
            if gx < 0 or gy < 0 or gx + mw > GW or gy + mh > GH:
                return True
            return bool(np.any(grid[gy:gy + mh, gx:gx + mw] & gm))

        def stamp(px, py):
            gmp = t["gmp"]
            ph, pw = gmp.shape
            gx = int(px // stride) - pad
            gy = int(py // stride) - pad
            gx0, gy0 = max(0, gx), max(0, gy)
            gx1, gy1 = min(GW, gx + pw), min(GH, gy + ph)
            if gx1 <= gx0 or gy1 <= gy0:
                return
            grid[gy0:gy1, gx0:gx1] |= gmp[gy0 - gy:gy1 - gy, gx0 - gx:gx1 - gx]

        if i == 0:
            t["x"], t["y"] = cx - t["fullW"] / 2, cy - t["fullH"] / 2
            stamp(t["x"], t["y"])
            placed.append(t)
            continue

        comX = comY = comW = 0.0
        for p in placed:
            a = p["fullW"] * p["fullH"]
            comX += (p["x"] + p["fullW"] / 2) * a
            comY += (p["y"] + p["fullH"] / 2) * a
            comW += a
        comX /= comW
        comY /= comW

        best, best_cost = None, math.inf
        step = max(stride, min(t["fullW"], t["fullH"]) * 0.05)
        max_r = max(W, H)
        found_ring = -1.0
        phase = rnd() * math.tau
        r = 0.0
        while r <= max_r:
            if found_ring >= 0 and r > found_ring + step * 2:
                break
            samples = max(36, int(r / 1.6))
            for k in range(samples):
                theta = phase + (k / samples) * math.tau
                px = cx + r * xbias * math.cos(theta) - t["fullW"] / 2
                py = cy + r * ybias * math.sin(theta) - t["fullH"] / 2
                if px < 0 or py < 0 or px + t["fullW"] > W or py + t["fullH"] > H:
                    continue
                if collide(px, py):
                    continue
                dxx = px + t["fullW"] / 2 - comX
                dyy = py + t["fullH"] / 2 - comY
                cost = math.hypot(dxx / xbias, dyy / ybias) + rnd() * step * 0.5
                if cost < best_cost:
                    best_cost, best = cost, (px, py)
            if best is not None and found_ring < 0:
                found_ring = r
            r += step
        if best is not None:
            t["x"], t["y"] = best
            stamp(*best)
        else:
            t["x"], t["y"] = -99999, -99999  # couldn't fit; hide rather than overlap
        placed.append(t)
    return placed


def _cluster_bounds(placed):
    L = T = math.inf
    R = B = -math.inf
    for t in placed:
        if t["x"] < -1000:
            continue
        L, T = min(L, t["x"]), min(T, t["y"])
        R, B = max(R, t["x"] + t["fullW"]), max(B, t["y"] + t["fullH"])
    return L, T, R, B


def _draw_collage_names(canvas, x0, y0, w, h, names, fonts_dir) -> None:
    """Small dark name strip centered in the bottom band, on the existing
    (white) ground — no bar, to keep the clean kachō-e look. Wraps to two lines
    if one won't fit at a legible size."""
    if not names:
        return
    draw = ImageDraw.Draw(canvas)
    sep = "   ·   "
    text = sep.join(names)
    max_w = w - 32
    font = _fit_font(draw, text, fonts_dir, max_w, int(h * 0.62), min_size=11)
    lines = [text]
    if draw.textlength(text, font=font) > max_w:
        mid = (len(names) + 1) // 2  # balance names across two lines
        lines = [sep.join(names[:mid]), sep.join(names[mid:])]
        widest = max(lines, key=len)
        font = _fit_font(draw, widest, fonts_dir, max_w, int(h * 0.46), min_size=11)
    line_h = font.size + 3
    ty = y0 + (h - line_h * len(lines)) // 2
    for line in lines:
        lw = draw.textlength(line, font=font)
        draw.text((x0 + (w - lw) // 2, ty), line, fill=(20, 20, 20), font=font)
        ty += line_h


def compose_collage(width, height, birds, cutouts_dir, *, bg=(255, 255, 255),
                    fly_prob=0.12, budget_frac=0.5, recency_decay=0.78,
                    min_area_frac=0.02, ellipse_bias=2.0, pad=3,
                    grid_stride=4, fonts_dir=None, show_names=True,
                    caption_scale=1.0) -> Image.Image | None:
    """Nest each bird's transparent cutout into a single RGB frame. `birds` is in
    recency order (most recent first); the most recent renders largest. With
    show_names, a small name strip is drawn along the bottom (the cluster packs
    above it). Returns None if numpy is unavailable or no bird has a cutout
    (caller falls back)."""
    try:
        import numpy as np
    except ImportError:
        return None

    cutouts_dir = Path(cutouts_dir)
    if fonts_dir is not None:
        fonts_dir = Path(fonts_dir)
    tiles = []
    names = []
    for rank, b in enumerate(birds):
        sci = (b.get("scientific") or "").strip()
        if not sci:
            continue
        pose = _pick_pose(cutouts_dir, sci, fly_prob)
        path = cutout_for(cutouts_dir, sci, pose)
        if path is None:
            continue
        img = Image.open(path).convert("RGBA")
        tiles.append({"img": img, "ar": img.width / img.height,
                      "score": recency_decay ** rank})
        common = (b.get("common") or "").strip()
        names.append(f"{common} ({sci})"
                     if common and common.lower() != sci.lower() else sci)
    if not tiles:
        return None

    # Reserve a thin band at the bottom for the names; the cluster packs in the
    # area above it so birds never overlap the text.
    cap_h = 0
    if show_names and fonts_dir is not None and names:
        cap_h = min(int(max(30, height // 14) * caption_scale), height // 5)
    pack_h = height - cap_h

    vp = width * pack_h
    budget, min_area = vp * budget_frac, vp * min_area_frac
    score_sum = sum(t["score"] for t in tiles) or 1.0
    for t in tiles:
        t["area"] = max(min_area, budget * t["score"] / score_sum)
    # Flooring rare birds may push the total over budget; squeeze it back out of
    # the larger tiles so the floor stays intact.
    area_sum = sum(t["area"] for t in tiles)
    if area_sum > budget:
        fixed = sum(t["area"] for t in tiles if t["area"] <= min_area + 1e-9)
        flex = area_sum - fixed
        shrink = min(1.0, max(0.0, budget - fixed) / flex) if flex > 0 else 1.0
        for t in tiles:
            if t["area"] > min_area + 1e-9:
                t["area"] *= shrink
    for t in tiles:
        t["fullW"] = math.sqrt(t["area"] * t["ar"])
        t["fullH"] = t["fullW"] / t["ar"]

    xbias, ybias = ellipse_bias, 1.0
    placed = _mask_pack(np, tiles, width, pack_h, xbias, ybias, pad, grid_stride)
    # Scale-to-fit: shrink + repack until every tile lands on screen.
    L, T, R, B = _cluster_bounds(placed)
    for _ in range(10):
        missing = any(t["x"] < -1000 for t in placed)
        overflow = L < 0 or T < 0 or R > width or B > pack_h
        if not missing and not overflow:
            break
        scale = 0.93
        if overflow:
            sx = (width * 0.96) / max(R - L, width * 0.96)
            sy = (pack_h * 0.94) / max(B - T, pack_h * 0.94)
            scale = min(scale, sx, sy)
        for t in tiles:
            t["fullW"] *= scale
            t["fullH"] *= scale
        placed = _mask_pack(np, tiles, width, pack_h, xbias, ybias, pad, grid_stride)
        L, T, R, B = _cluster_bounds(placed)

    # Re-centre the cluster (the spiral biases toward its centre of mass).
    if R > -math.inf:
        dx, dy = width / 2 - (L + R) / 2, pack_h / 2 - (T + B) / 2
        if abs(dx) > 1 or abs(dy) > 1:
            for t in placed:
                if t["x"] > -1000:
                    t["x"] += dx
                    t["y"] += dy

    canvas = Image.new("RGB", (width, height), bg)
    # Paint back-to-front (smallest/last-placed on top reads better); placed is
    # largest-first, so reverse so the big anchor bird sits behind.
    for t in reversed(placed):
        if t["x"] < -1000:
            continue
        w_i, h_i = max(1, round(t["fullW"])), max(1, round(t["fullH"]))
        im = t["img"].resize((w_i, h_i), Image.LANCZOS)
        canvas.paste(im, (round(t["x"]), round(t["y"])), im)
    if cap_h:
        _draw_collage_names(canvas, 0, height - cap_h, width, cap_h, names, fonts_dir)
    return canvas


def to_panel(frame: Image.Image, *, dither: bool = True, sharpen: float = 0.0,
             rotate: int = 0, clean_bg: bool = True,
             clean_ink: bool = True) -> Image.Image:
    """Quantize an RGB frame to the Spectra-6 palette, ready for the panel.

    dither   Floyd-Steinberg dithering (True) or hard nearest-color (False:
             sharper edges but visible color banding).
    sharpen  UnsharpMask amount applied before quantizing (0 = off); crisps up
             detail so the dithered result reads sharper.
    rotate   Rotate the final frame this many degrees (0 or 180) for a panel
             mounted upside-down. 180 is a lossless flip.
    clean_bg Snap the near-white/cream paper to pure white before dithering so
             the background doesn't dither into yellow/red speckle.
    clean_ink Snap near-black pixels to pure black (and near-white to white)
             before dithering, so dark birds (e.g. a crow) render as solid black
             instead of scattering into red/blue/green speckle on the 6-colour
             palette. Edges-only; midtones still dither for shading.
    """
    img = frame.convert("RGB")
    if clean_ink:
        # Joint per-pixel extremes: max(R,G,B) low -> near-black; min(R,G,B)
        # high -> near-white. Pillow-only (no numpy) so it runs on the Pi.
        r, g, b = img.split()
        mx = ImageChops.lighter(ImageChops.lighter(r, g), b)
        mn = ImageChops.darker(ImageChops.darker(r, g), b)
        dark = mx.point(lambda p: 255 if p < 60 else 0)
        light = mn.point(lambda p: 255 if p > 205 else 0)
        img = img.copy()
        img.paste((0, 0, 0), None, dark)
        img.paste((255, 255, 255), None, light)
    if clean_bg:
        # Flood-fill the paper background to pure white from many points along
        # every edge. The background (cream paper + white scan margins) is
        # connected to the borders, so this whitens it uniformly — no cream/white
        # seam — while the saturated/dark bird + foliage stop the fill.
        img = img.copy()
        w, h = img.size
        steps = 9
        seeds = []
        for i in range(steps):
            x, y = w * i // (steps - 1), h * i // (steps - 1)
            seeds += [(min(x, w - 1), 0), (min(x, w - 1), h - 1),
                      (0, min(y, h - 1)), (w - 1, min(y, h - 1))]
        for xy in seeds:
            px = img.getpixel(xy)
            # Only seed from a light background pixel, so we never flood the dark
            # caption bar (or a dark plate edge) into white.
            if sum(px[:3]) >= 3 * 170:
                ImageDraw.floodfill(img, xy, (255, 255, 255), thresh=48)
    if sharpen and sharpen > 0:
        img = img.filter(ImageFilter.UnsharpMask(
            radius=2, percent=int(round(sharpen * 100)), threshold=2))
    out = img.quantize(
        palette=_palette_image(),
        dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE,
    )
    if rotate % 360:
        out = (out.transpose(Image.Transpose.ROTATE_180)
               if rotate % 360 == 180 else out.rotate(-rotate % 360, expand=False))
    return out
