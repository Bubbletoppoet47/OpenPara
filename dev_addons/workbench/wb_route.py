"""wb_route.py - where the wires of the schematic run: around the blocks, never behind them.

A wire leaves the right side of a cell, comes in at the left side of another, and is made only of horizontal and vertical pieces.  Every block holds a keep-out area (its body and
the name under it); two blocks are always at least GAP apart (wb_canvas), so there is a channel of that width between them.  A wire runs on the middle line of such a channel, that
is on the border of the keep-out areas grown by half the gap (CLEAR), or along the line of its own ports: those lines (and nothing else) are the roads of the router, which finds
the shortest road with the fewest bends (A*) and the corners it needs.

    route(p0, p1, rects)   p0, p1 = (x, y) of the ports; rects = [(left, top, right, bottom)] of the keep-out areas of ALL the blocks
                           -> [(x, y), ...] from p0 to p1 (a stub of CLEAR at both ends, so the wire is clear of the block it leaves and of the one it enters), or None when the
                           ports are inside the keep-out area of another block (blocks on top of each other) - the caller then draws the plain route.
    crossings(pts, rects)  the keep-out areas a path runs through (tests, and the check of a path)
"""
import heapq

GAP = 40.0                                                   # the least space between two blocks
CLEAR = GAP / 2.0                                            # a wire runs this far from the block it passes
BEND = 30.0                                                  # what a corner costs, in px of wire: fewer bends win over a slightly longer wire
EPS = 1e-6


def _grown(rects, c):
    return [(l - c, t - c, r + c, b + c) for (l, t, r, b) in rects]


def route(p0, p1, rects, clear=CLEAR):
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    s = (x0 + clear, y0)
    t = (x1 - clear, y1)
    box = _grown(rects, clear)
    xs = {round(v, 4) for o in box for v in (o[0], o[2])} | {round(s[0], 4), round(t[0], 4)}
    ys = {round(v, 4) for o in box for v in (o[1], o[3])} | {round(s[1], 4), round(t[1], 4)}
    xs, ys = sorted(xs), sorted(ys)
    xi = {v: i for i, v in enumerate(xs)}
    yi = {v: j for j, v in enumerate(ys)}
    start = (xi[round(s[0], 4)], yi[round(s[1], 4)])
    goal = (xi[round(t[0], 4)], yi[round(t[1], 4)])
    memo = {}

    def h_free(j, i):                                        # the piece of the horizontal line ys[j] between xs[i] and xs[i + 1]
        k = (0, j, i)
        v = memo.get(k)
        if v is None:
            y, a, b = ys[j], xs[i], xs[i + 1]
            v = not any(o[1] + EPS < y < o[3] - EPS and a < o[2] - EPS and b > o[0] + EPS for o in box)
            memo[k] = v
        return v

    def v_free(i, j):                                        # the piece of the vertical line xs[i] between ys[j] and ys[j + 1]
        k = (1, i, j)
        v = memo.get(k)
        if v is None:
            x, a, b = xs[i], ys[j], ys[j + 1]
            v = not any(o[0] + EPS < x < o[2] - EPS and a < o[3] - EPS and b > o[1] + EPS for o in box)
            memo[k] = v
        return v

    def heur(i, j):
        return abs(xs[i] - xs[goal[0]]) + abs(ys[j] - ys[goal[1]])

    # state: (i, j, d) with d = 0 when the wire arrived moving horizontally, 1 vertically; it leaves the block moving to the right
    best = {(start[0], start[1], 0): 0.0}
    came = {}
    heap = [(heur(*start), 0, start[0], start[1], 0)]
    n = 0
    end = None
    while heap:
        f, _n, i, j, d = heapq.heappop(heap)
        g = best.get((i, j, d))
        if g is None or f > g + heur(i, j) + EPS:
            continue
        if d == 2:                                           # (it arrived vertically and has now turned to the right, into the port)
            end = (i, j, 2)
            break
        if (i, j) == goal:
            if d == 0:
                end = (i, j, d)
                break
            tot = g + BEND                                   # it must leave the corner to the right, into the port
            if best.get((i, j, 2), 1e18) > tot:
                best[(i, j, 2)] = tot
                came[(i, j, 2)] = (i, j, d)
                n += 1
                heapq.heappush(heap, (tot, n, i, j, 2))
            continue
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if not (0 <= ni < len(xs) and 0 <= nj < len(ys)):
                continue
            if dj == 0:
                if not h_free(j, min(i, ni)):
                    continue
                nd, cost = 0, abs(xs[ni] - xs[i])
            else:
                if not v_free(i, min(j, nj)):
                    continue
                nd, cost = 1, abs(ys[nj] - ys[j])
            if nd != d:
                cost += BEND
            ng = g + cost
            key = (ni, nj, nd)
            if ng + EPS < best.get(key, 1e18):
                best[key] = ng
                came[key] = (i, j, d)
                n += 1
                heapq.heappush(heap, (ng + heur(ni, nj), n, ni, nj, nd))
    if end is None:
        return None
    path = []
    cur = end
    while cur is not None:
        path.append((xs[cur[0]], ys[cur[1]]))
        cur = came.get(cur)
    path.reverse()
    pts = [(x0, y0)] + path + [(x1, y1)]
    return simplify(pts)


def simplify(pts):
    """The corners only: no repeated points, no point in the middle of a straight run."""
    out = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < EPS and abs(out[-1][1] - p[1]) < EPS:
            continue
        out.append((p[0], p[1]))
    k = 1
    while k < len(out) - 1:
        a, b, c = out[k - 1], out[k], out[k + 1]
        if (abs(a[0] - b[0]) < EPS and abs(b[0] - c[0]) < EPS) or (abs(a[1] - b[1]) < EPS and abs(b[1] - c[1]) < EPS):
            del out[k]
        else:
            k += 1
    return out


def crossings(pts, rects):
    """The indexes of the areas (strictly) that some piece of the path runs through."""
    hit = set()
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        lo_x, hi_x, lo_y, hi_y = min(xa, xb), max(xa, xb), min(ya, yb), max(ya, yb)
        for k, (l, t, r, b) in enumerate(rects):
            if lo_x < r - EPS and hi_x > l + EPS and lo_y < b - EPS and hi_y > t + EPS:
                hit.add(k)
            elif abs(lo_y - hi_y) < EPS and t + EPS < lo_y < b - EPS and lo_x < r - EPS and hi_x > l + EPS:
                hit.add(k)
            elif abs(lo_x - hi_x) < EPS and l + EPS < lo_x < r - EPS and lo_y < b - EPS and hi_y > t + EPS:
                hit.add(k)
    return sorted(hit)
