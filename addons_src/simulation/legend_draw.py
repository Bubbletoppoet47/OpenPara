"""
legend_draw.py - the colour scale of a result picture (1D FEA, 2D FEA, CFD, and so in the exported animations), drawn so that it NEVER leaves the
picture: the text is measured first, a long title wraps onto lines (the unit stays on the last one), the bar shrinks in a short window and drops
labels it has no room for.  Everything is placed from the right edge of the picture inwards.

    draw_legend(p, W, H, title, labels, colour_fn, subtitle=None) -> QRect (what was drawn; always inside 0..W x 0..H)
      labels: [(t, text)] with t = 0 at the top of the bar and 1 at the bottom
      colour_fn(t) -> (r, g, b) for t = 1 at the top (the value ramp)
"""
from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics

MARGIN = 8
BAR_W = 16
GAP = 4


def wrap(text, max_w, fm):
    """Greedy word wrap to lines no wider than max_w; a single word that is still too wide is shortened in the middle."""
    lines, cur = [], ""
    for word in str(text).split():
        trial = word if not cur else cur + " " + word
        if fm.horizontalAdvance(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return [fm.elidedText(l, Qt.TextElideMode.ElideMiddle, max(int(max_w), 10)) for l in lines] or [""]


def draw_legend(p, W, H, title, labels, colour_fn, subtitle=None, desired_h=180, font_pt=8):
    p.save()
    try:
        font = QFont("Arial", font_pt)
        p.setFont(font)
        fm = QFontMetrics(p.font())
        W, H = max(int(W), 40), max(int(H), 40)
        room_w = W - 2 * MARGIN
        label_w = max([fm.horizontalAdvance(t) for _t, t in labels] + [0])
        block_w = BAR_W + GAP + label_w
        if block_w > room_w:                                   # absurdly narrow: shorten the numbers rather than leave the picture
            label_w = max(room_w - BAR_W - GAP, 10)
            labels = [(t, fm.elidedText(s, Qt.TextElideMode.ElideRight, int(label_w))) for t, s in labels]
            block_w = BAR_W + GAP + label_w
        head = wrap(title, room_w, fm) + (wrap(subtitle, room_w, fm) if subtitle else [])
        lh = fm.height()
        head_h = lh * len(head)
        y_text = MARGIN
        y0 = y_text + head_h + 6
        h = int(min(desired_h, H - y0 - MARGIN - lh // 2))
        if h < 36 and len(head) > 1:                           # a very short window: the title is cut to its first line before the bar is
            head = head[:1]
            head_h = lh
            y0 = y_text + head_h + 6
            h = int(min(desired_h, H - y0 - MARGIN - lh // 2))
        h = max(h, 20)
        if y0 + h > H:                                         # nothing fits: pull the whole thing up inside
            y0 = max(0, H - h - lh // 2 - 1)
            head = head if y0 >= y_text + head_h else []
        x0 = W - MARGIN - block_w
        # the bar
        for k in range(h):
            c = colour_fn(1 - k / max(h - 1, 1))
            p.fillRect(QRectF(x0, y0 + k, BAR_W, 1.5), QColor(int(c[0]), int(c[1]), int(c[2])))
        p.setPen(QColor("black"))
        p.drawRect(QRect(int(x0), int(y0), BAR_W, h))
        # the labels, as many as fit (the first and the last always)
        fit = max(2, int(h // (1.5 * lh)) + 1)
        if len(labels) > fit:
            keep = sorted({round(i * (len(labels) - 1) / (fit - 1)) for i in range(fit)})
            labels = [labels[i] for i in keep]
        for t, text in labels:
            base = y0 + t * h + fm.ascent() // 2
            p.drawText(int(x0 + BAR_W + GAP), int(base), text)
        # the title and the note, right aligned to the picture's edge
        for i, line in enumerate(head):
            w_ = fm.horizontalAdvance(line)
            p.drawText(int(max(MARGIN, W - MARGIN - w_)), int(y_text + fm.ascent() + i * lh), line)
        left = min([x0] + [max(MARGIN, W - MARGIN - fm.horizontalAdvance(l)) for l in head])
        return QRect(int(left), int(y_text if head else y0), int(W - MARGIN - left), int(y0 + h + lh // 2 - (y_text if head else y0)))
    finally:
        p.restore()
