#!/usr/bin/env python3
"""Render TwoFold's daily Instagram reel (1080x1920, 30fps, ~14s, silent AAC track).

Usage: python3 render_reel.py [--date YYYY-MM-DD] [--out reels/YYYY-MM-DD.mp4]
Prints one JSON line: {"date", "file", "caption", "hook"}.
Picks the reel from library.json by weekday, rotating weekly.
"""
import argparse, datetime, json, math, os, subprocess, sys
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
INK, CREAM, GREY = (27, 26, 23), (240, 237, 230), (148, 144, 138)
SOFT_ON_INK, SOFT_ON_CREAM = (201, 197, 187), (74, 71, 65)
MARGIN = 96


def font(weight, size):
    return ImageFont.truetype(os.path.join(HERE, 'fonts', f'dm-sans-latin-{weight}-normal.woff'), size)


def ease_out_back(x):
    x = max(0.0, min(1.0, x))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def wrap(text, f, width, tracking=0):
    lines = []
    for para in text.split('\n'):
        words, cur = para.split(' '), ''
        for w in words:
            t = (cur + ' ' + w).strip()
            if text_w(t, f, tracking) <= width or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def text_w(t, f, tracking=0):
    return f.getlength(t) + tracking * max(0, len(t) - 1)


def draw_tracked(d, xy, t, f, fill, tracking=0):
    if not tracking:
        d.text(xy, t, font=f, fill=fill)
        return
    x, y = xy
    for ch in t:
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + tracking


def fit_font(text, weight, size, width, min_size, max_lines, tracking_ratio=0.0):
    while size > min_size:
        f = font(weight, size)
        lines = wrap(text, f, width, -size * tracking_ratio)
        if len(lines) <= max_lines and all(text_w(l, f, -size * tracking_ratio) <= width for l in lines):
            return f, lines
        size -= 4
    f = font(weight, min_size)
    return f, wrap(text, f, width, -min_size * tracking_ratio)


class Layer:
    """A block of content that slides up and fades in at a delay within its scene."""
    def __init__(self, img, y, delay):
        self.img, self.y, self.delay = img, y, delay


def text_block(lines, f, color, line_h, tracking=0):
    hgt = int(line_h * len(lines)) + 20
    im = Image.new('RGBA', (W - 2 * MARGIN, hgt), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        draw_tracked(d, (0, int(i * line_h)), l, f, color, tracking)
    return im


def eyebrow_block(text, color):
    f = font(700, 30)
    return text_block([text.upper()], f, color, 40, tracking=8)


def bubble_block(text, bg, fg):
    f = font(500, 44)
    lines = wrap(text, f, 820 - 96)
    lh = 58
    w = int(min(820, max(text_w(l, f) for l in lines) + 96))
    h = int(lh * len(lines) + 88)
    im = Image.new('RGBA', (W - 2 * MARGIN, h + 70), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w, h), radius=44, fill=bg)
    d.rectangle((0, h - 44, 44, h), fill=bg)
    d.rounded_rectangle((0, h - 30, 30, h), radius=8, fill=bg)
    for i, l in enumerate(lines):
        d.text((48, 40 + i * lh), l, font=f, fill=fg)
    d.text((0, h + 22), 'Sent automatically, seconds after the call', font=font(400, 28), fill=GREY)
    return im


def logo(color, size=64):
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size / 24.0
    wdt = max(2, int(2.4 * s))
    for pts, col in (([(4, 11), (12, 4), (20, 11)], GREY), ([(4, 20), (12, 13), (20, 20)], color)):
        d.line([(x * s, y * s) for x, y in pts], fill=col, width=wdt, joint='curve')
        for x, y in (pts[0], pts[2]):
            r = wdt / 2
            d.ellipse((x * s - r, y * s - r, x * s + r, y * s + r), fill=col)
    return im


def scene_layers(kind, data, dark):
    fg = CREAM if dark else INK
    soft = SOFT_ON_INK if dark else SOFT_ON_CREAM
    layers = []
    if kind == 'hook':
        eb = eyebrow_block(data['eyebrow'], GREY)
        f, lines = fit_font(data['hook'], 700, 150, W - 2 * MARGIN, 96, 3, 0.04)
        hb = text_block(lines, f, fg, f.size * 1.04, tracking=-f.size * 0.04)
        total = eb.height + 36 + hb.height
        y0 = (H - total) // 2 - 120
        layers += [Layer(eb, y0, 0.05), Layer(hb, y0 + eb.height + 36, 0.15)]
    elif kind == 'problem':
        eb = eyebrow_block('The problem', GREY)
        f, lines = fit_font(data['problem'], 700, 84, W - 2 * MARGIN, 60, 5, 0.02)
        hb = text_block(lines, f, fg, f.size * 1.18, tracking=-f.size * 0.02)
        total = eb.height + 36 + hb.height
        y0 = (H - total) // 2 - 120
        layers += [Layer(eb, y0, 0.05), Layer(hb, y0 + eb.height + 36, 0.15)]
    elif kind == 'fix':
        eb = eyebrow_block('The fix', GREY)
        f, lines = fit_font(data['fix'], 700, 76, W - 2 * MARGIN, 56, 4, 0.02)
        hb = text_block(lines, f, fg, f.size * 1.2, tracking=-f.size * 0.02)
        blocks = [(eb, 0.05), (hb, 0.15)]
        if data.get('sms'):
            blocks.append((bubble_block(data['sms'], fg, INK if dark else CREAM), 0.45))
        gap = 48
        total = sum(b.height for b, _ in blocks) + gap * (len(blocks) - 1)
        y = (H - total) // 2 - 120
        for b, dl in blocks:
            layers.append(Layer(b, y, dl))
            y += b.height + gap
    elif kind == 'price':
        im = Image.new('RGBA', (W - 2 * MARGIN, 620), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        draw_tracked(d, (0, 0), 'ONE FLAT PRICE', font(700, 30), GREY, 8)
        big = font(700, 330)
        pound = font(700, 120)
        d.text((0, 110), '£', font=pound, fill=fg)
        px = pound.getlength('£') + 6
        d.text((px, 40), '299', font=big, fill=fg)
        d.text((px + big.getlength('299') + 14, 300), '/mo', font=font(500, 64), fill=GREY)
        d.text((0, 460), 'No contract. Cancel anytime.', font=font(500, 52), fill=soft)
        layers.append(Layer(im, (H - 620) // 2 - 140, 0.05))
    elif kind == 'end':
        im = Image.new('RGBA', (W - 2 * MARGIN, 640), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        lg = logo(fg, 150)
        im.alpha_composite(lg, (0, 0))
        d.text((0, 200), 'TwoFold', font=font(700, 120), fill=fg)
        d.text((0, 350), 'twofoldmanagements.com', font=font(500, 52), fill=GREY)
        d.text((0, 470), 'Book a free demo.', font=font(700, 64), fill=fg)
        d.text((0, 560), 'Link in bio.', font=font(400, 48), fill=soft)
        layers.append(Layer(im, (H - 640) // 2 - 140, 0.05))
    return layers


def render(entry, start_dark, out):
    scenes = [('hook', 2.4), ('problem', 3.0), ('fix', 3.8 if entry.get('sms') else 3.0), ('price', 2.6), ('end', 2.8)]
    total = sum(d for _, d in scenes)
    nframes = int(total * FPS)
    bgs, built, starts = [], [], []
    t = 0.0
    for i, (kind, dur) in enumerate(scenes):
        dark = (i % 2 == 0) == start_dark
        bgs.append(INK if dark else CREAM)
        built.append(scene_layers(kind, entry, dark))
        starts.append(t)
        t += dur

    def frame_for(si, tl, dur):
        im = Image.new('RGB', (W, H), bgs[si])
        for L in built[si]:
            p = (tl - L.delay) / 0.45
            if p <= 0:
                continue
            a = ease_out(p)
            dy = int((1 - ease_out_back(p)) * 70)
            layer = L.img
            if a < 1:
                layer = L.img.copy()
                alpha = layer.getchannel('A').point(lambda v: int(v * a))
                layer.putalpha(alpha)
            im.paste(layer, (MARGIN, L.y + dy), layer)
        return im

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
           '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-shortest',
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-profile:v', 'high',
           '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    xfade = 0.2
    for n in range(nframes):
        tt = n / FPS
        si = max(i for i, s in enumerate(starts) if s <= tt)
        dur = scenes[si][1]
        tl = tt - starts[si]
        im = frame_for(si, tl, dur)
        if si + 1 < len(scenes) and tl > dur - xfade:
            nxt = frame_for(si + 1, tl - dur, scenes[si + 1][1])
            im = Image.blend(im, nxt, (tl - (dur - xfade)) / xfade)
        bar = int(W * (tt / total))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, bar, 6), fill=GREY)
        proc.stdin.write(im.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit('ffmpeg failed')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date')
    ap.add_argument('--out')
    a = ap.parse_args()
    day = datetime.date.fromisoformat(a.date) if a.date else datetime.datetime.now(ZoneInfo('Europe/London')).date()
    lib = json.load(open(os.path.join(HERE, 'library.json')))
    options = lib['reels'][str(day.isoweekday())]
    entry = options[day.isocalendar()[1] % len(options)]
    out = a.out or os.path.join(HERE, 'reels', f'{day.isoformat()}.mp4')
    render(entry, day.toordinal() % 2 == 0, out)
    caption = entry['caption'] + '\n\n' + lib['hashtags']
    print(json.dumps({'date': day.isoformat(), 'file': os.path.relpath(out, HERE), 'caption': caption, 'hook': entry['hook'].replace('\n', ' ')}))


if __name__ == '__main__':
    main()
