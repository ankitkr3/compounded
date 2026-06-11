#!/usr/bin/env python3
"""Render the compounded demo GIF: correction -> rule capture -> approval -> saved.

Simulated Claude Code session, rendered frame-by-frame with Pillow.
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 960, 700
PAD_X, PAD_TOP = 28, 54
LINE_H = 24
FONT_SIZE = 15

BG = (15, 20, 26)        # #0F141A
CHROME = (22, 27, 34)    # title bar
BORDER = (45, 51, 59)
FG = (230, 237, 243)     # main text
DIM = (139, 148, 158)    # gray
GREEN = (63, 185, 80)
CORAL = (217, 119, 87)
BLUE = (88, 166, 255)
PURPLE = (188, 140, 255)
RED = (248, 81, 73)
SELBG = (35, 134, 54)    # selected button bg

font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", FONT_SIZE, index=0)
font_b = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", FONT_SIZE, index=1)

CW = font.getlength("M")  # monospace char width


def base_frame():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # window chrome
    d.rectangle([0, 0, W, 36], fill=CHROME)
    d.line([0, 36, W, 36], fill=BORDER)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([16 + i * 22, 12, 28 + i * 22, 24], fill=c)
    title = "Claude Code — compounded demo"
    d.text((W / 2 - font.getlength(title) / 2, 10), title, font=font, fill=DIM)
    return img, d


def draw_segments(d, row, segs, cursor=False):
    """segs: list of (text, color, bold, bg). Draw at line `row`."""
    x = PAD_X
    y = PAD_TOP + row * LINE_H
    for text, color, bold, bgc in segs:
        f = font_b if bold else font
        w = f.getlength(text)
        if bgc:
            d.rectangle([x - 3, y - 2, x + w + 3, y + LINE_H - 5], fill=bgc)
        d.text((x, y), text, font=f, fill=color)
        x += w
    if cursor:
        d.rectangle([x + 2, y + 1, x + 2 + CW, y + LINE_H - 6], fill=FG)


def render(lines, cursor_row=None):
    img, d = base_frame()
    for row, segs in enumerate(lines):
        draw_segments(d, row, segs, cursor=(row == cursor_row))
    return img


# ---- segment helpers -------------------------------------------------------
def S(text, color=FG, bold=False, bg=None):
    return (text, color, bold, bg)


frames = []   # (PIL.Image, duration_ms)


def emit(lines, ms, cursor_row=None):
    frames.append((render(lines, cursor_row), ms))


def type_line(lines, prefix_segs, text, color=FG, ms_per_step=30, chars_per_step=2):
    """Animate typing `text` on the last line."""
    for i in range(0, len(text) + 1, chars_per_step):
        cur = lines[:-1] + [prefix_segs + [S(text[:i], color)]]
        emit(cur, ms_per_step, cursor_row=len(lines) - 1)
    final = lines[:-1] + [prefix_segs + [S(text, color)]]
    emit(final, 200, cursor_row=len(lines) - 1)
    return final


PROMPT = [S("❯ ", GREEN, bold=True)]

# ---- scene -----------------------------------------------------------------
lines = [PROMPT]
emit(lines, 700, cursor_row=0)

# 1. user asks
lines = type_line(lines, PROMPT, "use the latest gemini embedding model for search")
emit(lines, 400)

# 2. claude picks an old one
lines = lines + [[]]
lines = lines + [[S("● ", CORAL), S("Update", FG, bold=True), S("(src/embeddings.py)", DIM)]]
emit(lines, 500)
lines = lines + [[S("  └ ", DIM), S('model = "gemini-embedding-001"', BLUE)]]
emit(lines, 450)
lines = lines + [[S("● ", CORAL), S("Done — using gemini-embedding-001.", FG)]]
emit(lines, 1400)

# 3. user corrects
lines = lines + [[], PROMPT]
emit(lines, 400, cursor_row=len(lines) - 1)
lines = type_line(lines, PROMPT, "no — that's old. web-search for the latest first", RED)
emit(lines, 500)

# 4. corrective work
lines = lines + [[]]
lines = lines + [[S("● ", CORAL), S("WebSearch", FG, bold=True), S('("latest gemini embedding model")', DIM)]]
emit(lines, 600)
lines = lines + [[S("  └ ", DIM), S("found: ", DIM), S("gemini-embedding-002", GREEN, bold=True), S("  (current)", DIM)]]
emit(lines, 650)
lines = lines + [[S("● ", CORAL), S("Update", FG, bold=True), S("(src/embeddings.py)", DIM), S("  001 → 002", GREEN)]]
emit(lines, 700)
lines = lines + [[S("✓ ", GREEN, bold=True), S("Fixed — now on the latest model.", FG)]]
emit(lines, 1100)

# 5. compounded notices
lines = lines + [[]]
lines = lines + [[S("[compounded] ", CORAL, bold=True), S("correction detected — this looks like a reusable rule", DIM)]]
emit(lines, 1300)

# 6. approval box — exact column math: every row is 52 monospace cols
RULE1 = '"When asked for the latest model or library,'
RULE2 = ' web-search current options before choosing."'
TITLE = "Save this rule?"
box_top = [S("┌─ ", CORAL), S(TITLE, FG, bold=True), S(" " + "─" * (52 - 3 - len(TITLE) - 2) + "┐", CORAL)]
box_l1 = [S("│ ", CORAL), S(RULE1.ljust(48), FG), S(" │", CORAL)]
box_l2 = [S("│ ", CORAL), S(RULE2.ljust(48), FG), S(" │", CORAL)]
box_sp = [S("│ ", CORAL), S(" " * 48), S(" │", CORAL)]


def box_buttons(selected):
    yes_bg = SELBG if selected else None
    yes_fg = (255, 255, 255) if selected else DIM
    yes = " Yes, remember it "          # 18 cols
    no = "No, one-off"                  # 11 cols
    tail = 48 - 2 - len(yes) - 4 - len(no)
    return [S("│ ", CORAL), S("  "), S(yes, yes_fg, bold=True, bg=yes_bg),
            S("    "), S(no, DIM), S(" " * tail), S(" │", CORAL)]


box_bot = [S("└" + "─" * 50 + "┘", CORAL)]

lines = lines + [[]]
base = list(lines)
emit(base + [box_top, box_l1, box_l2, box_sp, box_buttons(False), box_bot], 600)
emit(base + [box_top, box_l1, box_l2, box_sp, box_buttons(True), box_bot], 1600)
# press Enter: flash
emit(base + [box_top, box_l1, box_l2, box_sp, box_buttons(False), box_bot], 120)
emit(base + [box_top, box_l1, box_l2, box_sp, box_buttons(True), box_bot], 700)

# 7. saved
lines = base + [box_top, box_l1, box_l2, box_sp, box_buttons(True), box_bot, []]
lines = lines + [[S("✓ ", GREEN, bold=True), S("Rule saved → ", FG), S(".verified/", PURPLE, bold=True), S("latest-model-web-search", PURPLE)]]
emit(lines, 800)
lines = lines + [[S("  ", FG), S("active immediately — it earns trust with every clean use,", DIM)]]
lines = lines + [[S("  ", FG), S("and never makes this mistake again", DIM)]]
emit(lines, 3200)

# ---- save ------------------------------------------------------------------
imgs = [f for f, _ in frames]
durs = [d for _, d in frames]
total = sum(durs) / 1000
out = str(__import__("pathlib").Path(__file__).parent / "demo.gif")
imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=durs, loop=0, optimize=True)
import os
print(f"frames={len(imgs)} duration={total:.1f}s size={os.path.getsize(out)/1024:.0f}KB -> {out}")
