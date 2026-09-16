#!/usr/bin/env python3
"""Regenerate the figures in docs/img/ (hand-built SVG, no dependencies).

    python3 docs/make_figures.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "img")
os.makedirs(IMG, exist_ok=True)

INK = "#1f2933"
MUTE = "#6b7580"
LINE = "#c3cbd3"
ACCENT = "#0b7285"
OK = "#2b8a3e"
OK_BG = "#e8f5ec"
FAIL = "#b02a37"
FAIL_BG = "#fbe9eb"
WARN = "#b25a00"
FONT = "'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "'Cascadia Code','Consolas','DejaVu Sans Mono',monospace"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SVG:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.b = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" '
                  f'height="{h}" viewBox="0 0 {w} {h}" font-family="{FONT}">',
                  f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
                  f'<defs><marker id="a" markerWidth="10" markerHeight="10" '
                  f'refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 z" '
                  f'fill="{MUTE}"/></marker>'
                  f'<marker id="af" markerWidth="10" markerHeight="10" refX="8" '
                  f'refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 z" '
                  f'fill="{FAIL}"/></marker></defs>']

    def rect(self, x, y, w, h, fill="#fff", stroke=LINE, sw=1.6, rx=8):
        self.b.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
                      f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x, y, s, size=14, fill=INK, anchor="start", weight="400",
             mono=False):
        fam = f' font-family="{MONO}"' if mono else ""
        self.b.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
                      f'text-anchor="{anchor}" font-weight="{weight}"{fam}>{esc(s)}</text>')

    def line(self, x1, y1, x2, y2, stroke=MUTE, sw=1.8, dash=None, arrow=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        a = f' marker-end="url(#{arrow})"' if arrow else ""
        self.b.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                      f'stroke="{stroke}" stroke-width="{sw}"{d}{a}/>')

    def save(self, name):
        self.b.append("</svg>")
        open(os.path.join(IMG, name), "w").write("\n".join(self.b))
        print("wrote", name)


def topic_graph():
    s = SVG(1000, 560)
    s.text(30, 40, "The topic graph, and the four ways it goes silent", size=22, weight="700")
    s.text(30, 64, "Every box is a node; every arrow is a topic. Red is a bug the linter reports.",
           size=13, fill=MUTE)

    def node(x, y, name, sub):
        s.rect(x, y, 220, 62, fill="#f5f8fa", stroke=ACCENT, sw=2)
        s.text(x + 16, y + 28, name, size=15, weight="700", mono=True)
        s.text(x + 16, y + 48, sub, size=11.5, fill=MUTE)

    node(40, 110, "talker", "publisher")
    node(40, 250, "talker", "publisher")
    node(40, 390, "(no one)", "missing publisher")
    node(740, 110, "listener", "subscriber")
    node(740, 250, "listener", "subscriber")
    node(740, 390, "listener", "subscriber")

    def edge(y1, y2, label, detail, bad):
        col = FAIL if bad else OK
        s.line(260, y1 + 31, 740, y2 + 31, stroke=col, sw=2.2,
               arrow="af" if bad else "a", dash="7 5" if bad else None)
        mid = (y1 + y2) / 2 + 31
        s.text(500, mid - 8, label, size=13, fill=col, anchor="middle", weight="700", mono=True)
        s.text(500, mid + 10, detail, size=11.5, fill=col if bad else MUTE, anchor="middle")

    edge(110, 110, "/scan  Float64", "BEST_EFFORT pub -> RELIABLE sub: nothing arrives", True)
    edge(250, 250, "/cmd", "String published, Int32 subscribed: type mismatch", True)
    edge(390, 390, "/sensor_temp", "subscribed, nobody publishes: typo or missing remap", True)

    # one healthy edge for contrast
    s.rect(40, 480, 220, 50, fill="#f5f8fa", stroke=ACCENT, sw=2)
    s.text(56, 510, "any node", size=13, mono=True, weight="700")
    s.rect(740, 480, 220, 50, fill="#f5f8fa", stroke=ACCENT, sw=2)
    s.text(756, 510, "any node", size=13, mono=True, weight="700")
    s.line(260, 505, 740, 505, stroke=OK, sw=2.2, arrow="a")
    s.text(500, 497, "/joint_states  JointState", size=13, fill=OK, anchor="middle",
           weight="700", mono=True)
    s.text(500, 520, "matched type and QoS: fine", size=11.5, fill=MUTE, anchor="middle")
    s.save("topic_graph.svg")


def unit_mismatch():
    s = SVG(1000, 360)
    s.text(30, 40, "A physical-unit mismatch the types cannot catch", size=22, weight="700")
    # before
    s.rect(40, 80, 430, 230, fill=FAIL_BG, stroke=FAIL, sw=2)
    s.text(60, 110, "flagged", size=14, weight="700", fill=FAIL)
    code1 = ["angle_deg = 90.0            # unit: deg",
             "q_rad = angle_deg           # <- deg into a",
             "                            #    rad name",
             "js.position = [q_rad]       # position is",
             "                            #    radians",
             "",
             "total_m = x_mm + reach_m    # mm + m in one",
             "                            #    expression"]
    for i, ln in enumerate(code1):
        s.text(60, 138 + i * 21, ln, size=12.5, mono=True,
               fill=FAIL if "<-" in ln or "mm + m" in ln else INK)
    # after
    s.rect(530, 80, 430, 230, fill=OK_BG, stroke=OK, sw=2)
    s.text(550, 110, "clean", size=14, weight="700", fill=OK)
    code2 = ["import math",
             "angle_deg = 90.0            # unit: deg",
             "q_rad = math.radians(angle_deg)",
             "js.position = [q_rad]       # radians now",
             "",
             "total_m = x_mm / 1000.0 + reach_m",
             "                            # both in m"]
    for i, ln in enumerate(code2):
        s.text(550, 138 + i * 21, ln, size=12.5, mono=True,
               fill=OK if "radians(" in ln or "/ 1000" in ln else INK)
    s.text(30, 345, "Units come from a name suffix (_deg, _rad, _mm, _m) or a "
           "trailing '# unit:' comment; a conversion on the way clears the finding.",
           size=12, fill=MUTE)
    s.save("unit_mismatch.svg")


if __name__ == "__main__":
    topic_graph()
    unit_mismatch()
