"""Draws the icon of the workbench: nodes of a grid tied by edges.

Why a script and not a ready file. The module has a rule: the product is not versioned, what
the product is made from is. The icon is such a product: twenty-odd numbers redraw it from
scratch, while a binary `.ico` in the history of git would show only "file changed".

Why a grid and not a beast. The workbench works with ANY morphs - a human body, armour,
anything with vertices and a `.tri` file. A wolf is a special case here, and an icon with a
beast would promise a tool that does not exist. Nodes and edges are exactly what the
workbench shows: points and the links between them.

Why one node is moved aside and coloured. A morph is a displacement of a vertex; a still
lattice would draw a viewer, not a workbench. The moved corner is what turns the geometry
into an action.

    python launcher/make-icon.py [--out launcher/morphbench.ico] [--show]

`--show` puts a 256 point `.png` beside the `.ico` as well - something that can actually be
opened and looked at, which an `.ico` cannot.

The few lines this prints stay plain English rather than going through the message catalogue:
this is a build tool, run by `build.cmd` from a folder the `morphbench` package is not
importable from, and it has to work when the module beside it does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

#: The sizes Windows takes out of an icon: the taskbar, the desktop, the large tiles.
SIZES = (16, 24, 32, 48, 64, 128, 256)

#: The plate is dark and the nodes are light: on a light taskbar and on a dark one the icon
#: stays legible, because the contrast is given by the plate itself, not by the background.
BACK = (32, 36, 44, 255)
NODE = (232, 214, 186, 255)
EDGE = (150, 142, 128, 255)
ACCENT = (96, 176, 208, 255)

#: The nodes in fractions of the side: x, y, radius, colour. The top right one is pulled
#: outwards and coloured - that is the morph. The radii are large on purpose: at sixteen
#: points a node degenerates into three pixels, and anything thinner disappears altogether.
NODES = (
    (0.27, 0.35, 0.100, NODE),
    (0.73, 0.20, 0.120, ACCENT),
    (0.79, 0.71, 0.100, NODE),
    (0.30, 0.76, 0.100, NODE),
)

#: The edges: a quadrangle plus a diagonal. The diagonal matters - without it the drawing
#: reads as a frame, and with it as two faces, that is, as a grid.
EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 2))

#: At sixteen and at twenty four points a SIMPLIFIED variant is drawn: the diagonal there is
#: shorter than the width of the line and merges with the edges into a blot. An icon drawn
#: differently at different sizes is the usual thing: in a small layer what matters is being
#: recognisable, not being complete.
SMALL_UPTO = 24
EDGES_SMALL = ((0, 1), (1, 2), (2, 3), (3, 0))
SMALL_NODE = 1.18
SMALL_EDGE = 1.30


def graph(side: int) -> Image.Image:
    """One layer of the icon. Drawn four times larger and scaled down - the edges are ragged
    otherwise."""
    k = 4
    big = side * k
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = big * 0.22
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=r, fill=BACK)
    # A thin frame in the accent colour: on a dark desktop the plate merges with it otherwise.
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=r, outline=ACCENT,
                        width=max(1, int(big * 0.02)))

    small = side <= SMALL_UPTO
    edges = EDGES_SMALL if small else EDGES
    width = max(1, int(big * 0.055 * (SMALL_EDGE if small else 1.0)))
    for a, b in edges:
        xa, ya = NODES[a][0] * big, NODES[a][1] * big
        xb, yb = NODES[b][0] * big, NODES[b][1] * big
        d.line((xa, ya, xb, yb), fill=EDGE, width=width)

    for cx, cy, rad, colour in NODES:
        x, y = cx * big, cy * big
        rr = rad * big * (SMALL_NODE if small else 1.0)
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=colour)
    return img.resize((side, side), Image.LANCZOS)


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else here / "morphbench.ico"
    layers = [graph(s) for s in SIZES]
    out.parent.mkdir(parents=True, exist_ok=True)
    # append_images is required: without it Pillow takes ONE picture and squeezes it down to
    # every size itself, quietly throwing away the layers drawn separately - the simplified
    # small variant then never reaches the file at all.
    layers[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=layers[:-1])
    print("icon: %s (%d layers: %s)" % (out, len(SIZES),
                                        ", ".join(str(s) for s in SIZES)))
    if "--show" in argv:
        png = out.with_suffix(".png")
        layers[-1].save(png)
        print("preview: %s" % png)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
