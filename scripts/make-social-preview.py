#!/usr/bin/env python3
"""Draw the repository's social preview, docs/images/social-preview.png.

GitHub shows this 1280x640 card when someone shares a link to the
repository. It follows oikoaudio.com's own card (public/og.png in the website
repository): its page colour, a monospace eyebrow, a large headline and the
blue and orange rule. The library screenshot, docs/images/library-dark.png,
sits on the right.

The fonts are IBM Plex Sans and IBM Plex Mono (SIL Open Font License), taken
from google/fonts at a pinned commit and checked against pinned SHA-256s.
They are downloaded into a temporary directory for each run and never
installed. Needs Pillow built with FreeType.

GitHub has no API for the image, so a maintainer uploads the result under
Settings > General > Social preview.
"""
import argparse
import hashlib
from pathlib import Path
import tempfile
import urllib.request

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
FONTS_COMMIT = '23e54b51ddffbc7713c583748e3bd86f62b1fa4a'
FONTS = {
    'sans': ('ofl/ibmplexsans/IBMPlexSans%5Bwdth,wght%5D.ttf',
             '3b031aa4216174205bd8471f88a49b91f093169e9e87bd5262242bc5967fe2e3'),
    'mono': ('ofl/ibmplexmono/IBMPlexMono-Regular.ttf',
             '6a3412f058c7d8dfd9170c41e85ade48e5156ecb89356110ca57a0a27734af46'),
}

WIDTH, HEIGHT = 1280, 640
MARGIN = 64
# oikoaudio.com's dark page and ink, and the rule colours of its card.
PAGE, INK, MUTED = '#171817', '#eeeee8', '#a7aaa1'
BLUE, ORANGE = '#2172fb', '#f86428'

EYEBROW = 'OIKO AUDIO'
TITLE = 'Plugg'
TAGLINE = ('Windows audio plug-ins', 'in your Linux DAW.')
SUBLINE = 'Ubuntu · Debian · Fedora · Arch'


def fetch_fonts(directory):
    paths = {}
    for name, (path, sha256) in FONTS.items():
        url = f'https://raw.githubusercontent.com/google/fonts/{FONTS_COMMIT}/{path}'
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise SystemExit(f'{url} does not match its pinned SHA-256')
        paths[name] = directory / (name + '.ttf')
        paths[name].write_bytes(data)
    return paths


def sans(path, size, weight):
    font = ImageFont.truetype(str(path), size)
    axes = {axis['name']: axis for axis in font.get_variation_axes()}
    font.set_variation_by_axes([weight if name in (b'Weight', 'Weight') else axis['default']
                                for name, axis in axes.items()])
    return font


def draw_card(fonts, screenshot):
    card = Image.new('RGB', (WIDTH, HEIGHT), PAGE)
    draw = ImageDraw.Draw(card)

    # The whole window, on the right.
    window = Image.open(screenshot).convert('RGBA')
    scale = 0.29
    window = window.resize((round(window.width * scale), round(window.height * scale)), Image.LANCZOS)
    left, top = WIDTH - MARGIN + 16 - window.width, (HEIGHT - window.height) // 2
    card.paste(window, (left, top), window)

    column = left - MARGIN - 40
    mono = ImageFont.truetype(str(fonts['mono']), 30)
    draw.text((MARGIN, 72), EYEBROW, font=mono, fill=INK, anchor='la')
    title = sans(fonts['sans'], 148, 560)
    draw.text((MARGIN - 6, 124), TITLE, font=title, fill=INK, anchor='la')
    # The largest size, up to 46 px, at which the longer line fits the column.
    size = 46
    while max(draw.textlength(line, font=sans(fonts['sans'], size, 480)) for line in TAGLINE) > column:
        size -= 1
    tagline = sans(fonts['sans'], size, 480)
    y = 318
    for line in TAGLINE:
        draw.text((MARGIN, y), line, font=tagline, fill=INK, anchor='la')
        y += round(size * 1.3)
    y += 36
    draw.rectangle((MARGIN, y, MARGIN + 48, y + 5), fill=BLUE)
    draw.rectangle((MARGIN + 48, y, MARGIN + 96, y + 5), fill=ORANGE)
    subline = ImageFont.truetype(str(fonts['mono']), 23)
    draw.text((MARGIN, y + 34), SUBLINE, font=subline, fill=MUTED, anchor='la')
    return card


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=REPO / 'docs/images/social-preview.png')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        card = draw_card(fetch_fonts(Path(directory)), REPO / 'docs/images/library-dark.png')
    card.save(args.output, optimize=True)
    print(f'{args.output} {WIDTH}x{HEIGHT}')


if __name__ == '__main__':
    main()
