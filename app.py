from flask import Flask, render_template, request, jsonify
import os, uuid, base64
from PIL import Image, ImageEnhance, ImageDraw, ImageFont
import io

import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=_os.path.join(_here, 'templates'),
    static_folder=_os.path.join(_here, 'static'),
)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# ── FIX 1: Only use /tmp — the ONE writable directory on Vercel ──
# Do NOT call os.makedirs at module level; defer it to first use.
TMP_FOLDER = '/tmp/israelify_output'

ISRAEL_BLUE = (0, 56, 184)
ISRAEL_WHITE = (255, 255, 255)
ISRAEL_GOLD = (255, 215, 0)


def ensure_tmp():
    """Create /tmp dir lazily — safe to call inside a request."""
    os.makedirs(TMP_FOLDER, exist_ok=True)


def israelify_image(img):
    """Apply Israelification effect to image."""
    img = img.convert('RGBA')
    w, h = img.size

    overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))

    # ── 1. Blue stripes top & bottom ──
    stripe_h = max(int(h * 0.12), 20)
    stripe_top = Image.new('RGBA', (w, stripe_h), ISRAEL_BLUE + (180,))
    overlay.paste(stripe_top, (0, 0), stripe_top)
    stripe_bot = Image.new('RGBA', (w, stripe_h), ISRAEL_BLUE + (180,))
    overlay.paste(stripe_bot, (0, h - stripe_h), stripe_bot)

    # ── 2. Star of David ──
    import math
    star_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    star_draw = ImageDraw.Draw(star_layer)
    cx, cy = w // 2, h // 2
    star_size = min(w, h) // 5
    pts1 = [(cx + star_size * math.cos(math.radians(i * 120 - 90)),
             cy + star_size * math.sin(math.radians(i * 120 - 90))) for i in range(3)]
    pts2 = [(cx + star_size * math.cos(math.radians(i * 120 + 90)),
             cy + star_size * math.sin(math.radians(i * 120 + 90))) for i in range(3)]
    star_draw.polygon(pts1, fill=ISRAEL_BLUE + (120,), outline=ISRAEL_BLUE + (220,))
    star_draw.polygon(pts2, fill=ISRAEL_BLUE + (120,), outline=ISRAEL_BLUE + (220,))

    # ── 3. Vignette ──
    vignette = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    for i in range(30):
        alpha = int((30 - i) / 30 * 100)
        margin = i * 3
        if margin >= w // 2 or margin >= h // 2:
            break  # stop before coords invert on small images
        vdraw.rectangle([margin, margin, w - margin, h - margin],
                        outline=ISRAEL_BLUE + (alpha,), width=3)

    # ── 4. Tint & composite ──
    img = ImageEnhance.Brightness(img).enhance(1.05)
    tint = Image.new('RGBA', (w, h), (0, 56, 184, 30))
    img = Image.alpha_composite(img, tint)
    img = Image.alpha_composite(img, star_layer)
    img = Image.alpha_composite(img, vignette)
    img = Image.alpha_composite(img, overlay)

    # ── 5. Watermark text ──
    txt_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(txt_layer)
    font_size = max(int(w * 0.06), 18)

    # FIX 2: Font paths that actually exist on Vercel's Amazon Linux runtime.
    # Fall back gracefully if none found — never hard-crash on fonts.
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/var/task/fonts/DejaVuSans-Bold.ttf",  # bundle your own as fallback
    ]
    font = None
    small_font = None
    for path in font_candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size)
                small_font = ImageFont.truetype(path.replace("Bold", ""), max(font_size // 2, 12))
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    if small_font is None:
        small_font = font

    text = "ISRAELIFIED"
    bbox = tdraw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    tx = (w - tw) // 2
    ty = h - stripe_h - font_size - 10
    tdraw.text((tx + 2, ty + 2), text, font=font, fill=(0, 0, 0, 150))
    tdraw.text((tx, ty), text, font=font, fill=(255, 255, 255, 240))

    wm = "israelify.fun"
    wm_bbox = tdraw.textbbox((0, 0), wm, font=small_font)
    tdraw.text((w - (wm_bbox[2] - wm_bbox[0]) - 8, h - (wm_bbox[3] - wm_bbox[1]) - 4),
               wm, font=small_font, fill=(255, 255, 255, 160))

    img = Image.alpha_composite(img, txt_layer)
    return img.convert('RGB')


@app.route('/')
def index():
    try:
        return render_template('index.html')
    except Exception as e:
        return f"<h1>Template error</h1><pre>{e}</pre>", 500


@app.route('/transform', methods=['POST'])
def transform():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        img = Image.open(file.stream)
        max_dim = 1200
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        result = israelify_image(img)

        # ── FIX 3: Return base64 ONLY — no file saved, no download route needed.
        # The client-side JS handles the download entirely via a data: URL.
        # This is the only approach that works reliably on stateless serverless.
        buf = io.BytesIO()
        result.save(buf, format='PNG')
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode()

        return jsonify({
            'success': True,
            'preview': f'data:image/png;base64,{b64}',
            # No download_url — browser will generate it from the base64
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── FIX 4: Remove the /download route entirely.
# Files saved to /tmp don't persist across serverless invocations.
# The frontend now handles downloads client-side (see index.html fix).


# Vercel imports this module directly — the `if __name__` block
# is still useful for local dev but Vercel never hits it.
if __name__ == '__main__':
    app.run(debug=True, port=5000)
