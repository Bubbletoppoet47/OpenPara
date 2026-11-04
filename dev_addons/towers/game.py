"""game.py - the rules of the tower-capture mini game (no Qt, so it can be tested and later reused).

Towers hold troops. The stored count sets the level (0-19: 1, 20-39: 2, 40-59: 3, 60+: 4; it can grow to 80, the part above 60 is a buffer).
A tower makes troops only through its open paths: BASE_RATE * 1.5**(level-1) per second, shared equally by its paths (opening more paths never
makes more troops).  Level n allows n paths.  Troops walk along a lane at constant speed; on arrival they join a friendly tower (+1 stored, up to 80)
or hit an enemy / neutral tower (-1 stored; at 0 the next troop captures it).  Two opposite lanes between towers of different owners cancel troops
head-on, so the stronger stream gets through.  Sending troops never lowers a tower's level; only hits from enemy troops do.
"""
import math
import random

W, H = 1000.0, 640.0
BASE_RATE = 1.0                    # troops per second from a level 1 tower with one path
RATE_STEP = 1.5                    # output rate factor per level
LEVEL_STEP = 20                    # stored troops per level
MAX_LEVEL = 4
MAX_TROOPS = 80                    # 60 for level 4, plus a buffer of 20 that does not raise the rate
TROOP_SPEED = 170.0                # units per second
START_TROOPS = {1: 10, 2: 20, 3: 40, 4: 60}
NEUTRAL = -1
PLAYER = 0


def level_of(troops):
    return max(1, min(MAX_LEVEL, 1 + int(troops) // LEVEL_STEP))


def rate_of(level):
    return BASE_RATE * RATE_STEP ** (level - 1)


class Config:
    def __init__(self, enemies=1, nodes=12, aggression=0.5, start_level=2, seed=None, neutral_min=5, neutral_max=30):
        self.enemies = max(1, min(3, int(enemies)))
        self.nodes = max(self.enemies + 2, min(40, int(nodes)))
        self.aggression = max(0.0, min(1.0, float(aggression)))
        self.start_level = max(1, min(MAX_LEVEL, int(start_level)))
        self.seed = random.randrange(1, 10 ** 6) if seed in (None, 0) else int(seed)
        self.neutral_min, self.neutral_max = int(neutral_min), int(neutral_max)


class Node:
    def __init__(self, i, x, y, owner=NEUTRAL, troops=0):
        self.id, self.x, self.y, self.owner, self.troops = i, x, y, owner, troops

    @property
    def level(self):
        return level_of(self.troops)


class Path:
    def __init__(self, src, dst, owner):
        self.src, self.dst, self.owner = src, dst, owner
        self.acc = 0.0
        self.open = True


class Troop:
    __slots__ = ("s", "owner")

    def __init__(self, owner):
        self.s = 0.0
        self.owner = owner


def generate_nodes(cfg):
    """Random node layout with a minimum gap; the seed reproduces it."""
    rng = random.Random(cfg.seed)
    n = cfg.nodes
    gap = max(60.0, min(150.0, 0.85 * math.sqrt(W * H / n) * 0.9))
    pts = []
    tries = 0
    while len(pts) < n:
        tries += 1
        if tries > 20000:
            gap *= 0.9
            tries = 0
        x, y = rng.uniform(50, W - 50), rng.uniform(50, H - 50)
        if all(math.hypot(x - a, y - b) >= gap for a, b in pts):
            pts.append((x, y))
    # starting towers: random, but kept apart
    order = list(range(n))
    owners = list(range(cfg.enemies + 1))
    spread = 0.38 * math.hypot(W, H)
    for _ in range(200):
        rng.shuffle(order)
        pick = order[:len(owners)]
        if all(math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1]) >= spread for ai, a in enumerate(pick) for b in pick[ai + 1:]):
            break
        spread *= 0.97
    nodes = [Node(i, x, y, NEUTRAL, rng.randint(cfg.neutral_min, cfg.neutral_max)) for i, (x, y) in enumerate(pts)]
    for o, idx in zip(owners, pick):
        nodes[idx].owner, nodes[idx].troops = o, START_TROOPS[cfg.start_level]
    return nodes


class Game:
    def __init__(self, cfg):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed * 7 + 1)
        self.nodes = generate_nodes(cfg)
        self.paths = []
        self.lanes = {}                 # (src, dst) -> list of Troop, oldest (furthest along) first
        self.time = 0.0
        self.state = "running"          # running | won | lost
        self.effects = []               # [x, y, age] for the cancel flashes
        self.think_at = {o: 1.0 + 0.4 * o for o in range(1, cfg.enemies + 1)}
        self.events = []                # short messages for the UI

    # ------------------------------------------------------------------ queries
    def open_paths(self, src):
        return [p for p in self.paths if p.src == src and p.open]

    def node_len(self, a, b):
        A, B = self.nodes[a], self.nodes[b]
        return max(1.0, math.hypot(A.x - B.x, A.y - B.y))

    def owned(self, owner):
        return [n for n in self.nodes if n.owner == owner]

    # ------------------------------------------------------------------ commands
    def toggle_path(self, owner, src, dst):
        """Open a path src -> dst for `owner`, or close it when it is already open.  Returns a message when refused, None otherwise."""
        if src == dst or self.state != "running":
            return None
        s = self.nodes[src]
        if s.owner != owner:
            return "Not your tower."
        for p in self.open_paths(src):
            if p.dst == dst:
                p.open = False
                self.prune()
                return None
        if len(self.open_paths(src)) >= s.level:
            return f"A level {s.level} tower can have {s.level} path{'s' if s.level > 1 else ''}."
        self.paths.append(Path(src, dst, owner))
        return None

    def close_paths_of(self, src):
        for p in self.paths:
            if p.src == src:
                p.open = False

    def enforce_slots(self, node):
        """After a level drop: the newest paths beyond the allowed number close."""
        op = self.open_paths(node.id)
        for p in op[node.level:]:
            p.open = False

    def prune(self):
        self.paths = [p for p in self.paths if p.open]

    # ------------------------------------------------------------------ simulation
    def step(self, dt):
        if self.state != "running":
            return
        self.time += dt
        # production, shared between a tower's open paths
        for node in self.nodes:
            if node.owner == NEUTRAL:
                continue
            op = self.open_paths(node.id)
            if not op:
                continue
            per = rate_of(node.level) / len(op)
            for p in op:
                p.acc += per * dt
                while p.acc >= 1.0:
                    p.acc -= 1.0
                    self.lanes.setdefault((p.src, p.dst), []).append(Troop(node.owner))
        # movement
        for (a, b), lane in self.lanes.items():
            if lane:
                d = TROOP_SPEED * dt / self.node_len(a, b)
                for t in lane:
                    t.s += d
        # head-on cancelling between opposite lanes of different owners
        for (a, b), lane in list(self.lanes.items()):
            if a < b and lane:
                other = self.lanes.get((b, a))
                while lane and other and lane[0].s + other[0].s >= 1.0 and lane[0].owner != other[0].owner:
                    t, u = lane.pop(0), other.pop(0)
                    A, B = self.nodes[a], self.nodes[b]
                    f = max(0.0, min(1.0, t.s))
                    self.effects.append([A.x + (B.x - A.x) * f, A.y + (B.y - A.y) * f, 0.0])
        # arrivals
        for (a, b), lane in self.lanes.items():
            while lane and lane[0].s >= 1.0:
                self.arrive(lane.pop(0), b)
        self.lanes = {k: v for k, v in self.lanes.items() if v}
        self.effects = [[x, y, age + dt] for x, y, age in self.effects if age + dt < 0.5]
        # paths whose tower changed hands are gone; paths of a tower follow its level
        for p in self.paths:
            if p.open and self.nodes[p.src].owner != p.owner:
                p.open = False
        for node in self.nodes:
            if node.owner != NEUTRAL:
                self.enforce_slots(node)
        self.prune()
        for o in range(1, self.cfg.enemies + 1):
            if self.time >= self.think_at[o] and self.owned(o):
                self.ai_think(o)
        self.check_end()

    def arrive(self, t, dst):
        n = self.nodes[dst]
        if n.owner == t.owner:
            n.troops = min(MAX_TROOPS, n.troops + 1)
        elif n.troops > 0:
            n.troops -= 1
        else:
            n.owner, n.troops = t.owner, 1
            self.close_paths_of(n.id)
            if t.owner == PLAYER:
                self.events.append("Tower captured")

    def check_end(self):
        if not self.owned(PLAYER):
            self.state = "lost"
        elif all(n.owner == PLAYER for n in self.nodes):
            self.state = "won"

    # ------------------------------------------------------------------ the opponent
    def ai_think(self, owner):
        a = self.cfg.aggression
        self.think_at[owner] = self.time + (2.6 - 2.1 * a) * self.rng.uniform(0.8, 1.25)
        mine = self.owned(owner)
        for n in mine:                                            # stop feeding towers that are full
            for p in self.open_paths(n.id):
                tgt = self.nodes[p.dst]
                if tgt.owner == owner and tgt.troops >= 60:
                    p.open = False
        self.prune()
        opened = 0
        for n in sorted(mine, key=lambda q: -q.troops):
            if opened >= (1 if a < 0.7 else 2):
                break
            if len(self.open_paths(n.id)) >= n.level:
                continue
            have = {p.dst for p in self.open_paths(n.id)}
            best, best_s = None, 0.05
            for t in self.nodes:
                if t.id == n.id or t.id in have:
                    continue
                d = math.hypot(t.x - n.x, t.y - n.y)
                near = 1.0 / (d / 250.0 + 0.3)
                if t.owner == owner:
                    if t.troops >= 60:
                        continue
                    s = (0.25 + 0.9 * (1 - a)) * (1 + (60 - t.troops) / 60.0) * near * (0.6 if t.level >= n.level else 1.0)
                elif t.owner == NEUTRAL:
                    s = 1.3 * near / (1 + t.troops / 20.0)
                else:
                    s = (0.4 + 1.2 * a) * near / (1 + t.troops / 20.0)
                    if t.troops > 25 and a < 0.5:
                        s *= 0.4
                s *= self.rng.uniform(0.8, 1.2)
                if s > best_s:
                    best, best_s = t, s
            if best is not None:
                self.paths.append(Path(n.id, best.id, owner))
                opened += 1
