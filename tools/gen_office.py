"""Genera aidelegate/ui/static/office.js: azulejos, muebles y plano de la oficina (diseño de la IA maestra).

Uso: python3 tools/gen_office.py aidelegate/ui/static/office.js
"""

import json
import pathlib
import sys

T = 16  # tamaño de azulejo
COLS, ROWS = 34, 30

PALETTE = {
    "k": "#1a1726", "void": "#13111c",
    "wood": "#b5774a", "woodD": "#9a6238", "woodL": "#c4855a",
    "tile": "#e9e1d3", "tileD": "#d6cbb8",
    "carpet": "#3f6f8f", "carpetL": "#4a7ea0",
    "wallTop": "#2a1830", "wallFace": "#4a2c4f", "wallFaceD": "#3b2340", "wallBase": "#241628",
    "deskTop": "#8a5a3b", "deskFront": "#6b4430", "deskLeg": "#4a2f22",
    "metal": "#c2c3c7", "metalD": "#8a8f99", "screen": "#2a3550", "screenOn": "#4fa8ff",
    "white": "#fff1e8", "cream": "#f1ece0", "paper": "#e8e2d0",
    "green": "#2fbf71", "greenD": "#23a571", "greenL": "#6fd98f",
    "pot": "#e8e2d0", "potD": "#c2b8a3",
    "b1": "#d94a4a", "b2": "#4a7ad9", "b3": "#3fbf7f", "b4": "#e0b040", "b5": "#8a5ad9",
    "box": "#d9a066", "boxD": "#b5804a",
    "chair": "#3f8f5a", "chairD": "#2d6b42",
    "stool": "#c9a46a", "stoolD": "#a8854f",
    "sofa": "#c46a8a", "sofaD": "#9a4a6a", "sofaL": "#d98aa6",
    "vend": "#c9e6f5", "vendD": "#5a7a9a", "glass": "#2a4a6a",
    "water": "#bfe3ff", "fridge": "#c2c8d0", "fridgeD": "#9aa1ab",
    "frame": "#b5804a", "frameD": "#8a5a3b",
    "sky": "#8fd3ff", "hill": "#6fbf6f", "sun": "#ffd75e",
}


# --- azulejos 16x16 (letras -> PALETTE vía TILE_KEYS) ---
def wood_tile():
    seams = [5, 12, 2, 9]
    rows = []
    for y in range(T):
        plank = y // 4
        r = ""
        for x in range(T):
            if y % 4 == 3:
                r += "D"
            elif y % 4 == 0:
                r += "L"
            elif x == seams[plank]:
                r += "D"
            else:
                r += "w"
        rows.append(r)
    return rows


def kitchen_tile():
    rows = []
    for y in range(T):
        r = ""
        for x in range(T):
            if x == 15 or y == 15 or abs(x - 7.5) + abs(y - 7.5) <= 1.5:
                r += "T"
            else:
                r += "t"
        rows.append(r)
    return rows


def carpet_tile():
    specks = {(3, 5), (11, 2), (7, 12), (13, 10), (1, 14)}
    return ["".join("C" if (x, y) in specks else "c" for x in range(T)) for y in range(T)]


def wall_face_tile():
    rows = []
    for y in range(T):
        if y >= 13:
            rows.append("b" * T)
        elif y == 0:
            rows.append("F" * T)
        else:
            rows.append("".join("F" if x == 0 else "f" for x in range(T)))
    return rows


TILES = {
    "w": {"rows": wood_tile(), "keys": {"w": "wood", "D": "woodD", "L": "woodL"}},
    "t": {"rows": kitchen_tile(), "keys": {"t": "tile", "T": "tileD"}},
    "c": {"rows": carpet_tile(), "keys": {"c": "carpet", "C": "carpetL"}},
    "F": {"rows": wall_face_tile(), "keys": {"f": "wallFace", "F": "wallFaceD", "b": "wallBase"}},
    "#": {"rows": ["W" * T] * T, "keys": {"W": "wallTop"}},
    ".": {"rows": ["V" * T] * T, "keys": {"V": "void"}},
}
for t in TILES.values():
    assert len(t["rows"]) == T and all(len(r) == T for r in t["rows"])


# --- muebles: rects [x, y, w, h, color]; "outline": [x, y, w, h] = borde 1px en k ---
def R(x, y, w, h, c):
    return [x, y, w, h, c]


FURNITURE = {
    "desk": {"w": 32, "h": 22, "rects": [
        R(0, 6, 32, 10, "deskTop"), R(0, 16, 32, 4, "deskFront"), R(1, 20, 3, 2, "deskLeg"), R(28, 20, 3, 2, "deskLeg"),
        R(9, 0, 14, 10, "k"), R(10, 1, 12, 8, "screen"), R(15, 10, 2, 2, "metalD"), R(13, 12, 6, 1, "metalD"),
        R(10, 13, 12, 2, "metal"), R(24, 13, 2, 2, "metal")],
        "outline": [[0, 6, 32, 14]], "screen": [10, 1, 12, 8], "mug": [25, 1]},
    "stool": {"w": 10, "h": 8, "rects": [R(0, 0, 10, 5, "stool"), R(0, 5, 10, 2, "stoolD"), R(4, 7, 2, 1, "deskLeg")],
              "outline": [[0, 0, 10, 7]]},
    "bookshelf": {"w": 32, "h": 26, "rects": [
        R(0, 0, 32, 26, "frame"), R(2, 2, 28, 22, "frameD"), R(2, 9, 28, 1, "frame"), R(2, 17, 28, 1, "frame"),
        R(3, 3, 2, 6, "b1"), R(5, 4, 2, 5, "b2"), R(7, 3, 3, 6, "b3"), R(11, 4, 2, 5, "b4"), R(13, 3, 2, 6, "b5"),
        R(17, 6, 6, 3, "paper"), R(24, 3, 2, 6, "b1"), R(26, 4, 3, 5, "b3"),
        R(3, 11, 3, 6, "b4"), R(6, 12, 2, 5, "b1"), R(9, 11, 2, 6, "b2"), R(14, 12, 3, 5, "b5"), R(18, 11, 2, 6, "b3"),
        R(22, 13, 5, 4, "box"), R(27, 11, 2, 6, "b2"),
        R(3, 19, 2, 5, "b2"), R(6, 20, 3, 4, "paper"), R(12, 19, 2, 5, "b3"), R(16, 19, 3, 5, "b1"), R(24, 20, 4, 4, "b5")],
        "outline": [[0, 0, 32, 26]]},
    "plant": {"w": 16, "h": 24, "rects": [
        R(7, 2, 2, 13, "green"), R(3, 6, 3, 9, "green"), R(10, 5, 3, 10, "green"), R(1, 10, 3, 5, "greenD"),
        R(12, 9, 3, 6, "greenD"), R(5, 4, 2, 4, "greenL"), R(9, 3, 2, 4, "greenL"),
        R(3, 15, 10, 2, "potD"), R(4, 17, 8, 7, "pot")], "outline": [[4, 15, 8, 9]]},
    "boxes": {"w": 20, "h": 18, "rects": [
        R(0, 6, 12, 12, "box"), R(5, 6, 2, 12, "boxD"), R(8, 0, 12, 10, "box"), R(13, 0, 2, 10, "boxD")],
        "outline": [[0, 6, 12, 12], [8, 0, 12, 10]]},
    "vending": {"w": 18, "h": 34, "rects": [
        R(0, 0, 18, 34, "vend"), R(2, 3, 10, 22, "glass"),
        R(3, 5, 2, 3, "b1"), R(6, 5, 2, 3, "b3"), R(9, 5, 2, 3, "b4"), R(3, 11, 2, 3, "b2"), R(6, 11, 2, 3, "b5"),
        R(9, 11, 2, 3, "b1"), R(3, 17, 2, 3, "b4"), R(6, 17, 2, 3, "b2"), R(9, 17, 2, 3, "b3"),
        R(13, 4, 3, 8, "vendD"), R(3, 28, 8, 3, "k")], "outline": [[0, 0, 18, 34]]},
    "cooler": {"w": 12, "h": 26, "rects": [
        R(2, 0, 8, 10, "water"), R(0, 10, 12, 16, "cream"), R(3, 13, 2, 2, "b2"), R(7, 13, 2, 2, "b1"),
        R(2, 20, 8, 1, "metalD")], "outline": [[2, 0, 8, 10], [0, 10, 12, 16]]},
    "fridge": {"w": 16, "h": 34, "rects": [
        R(0, 0, 16, 34, "fridge"), R(0, 12, 16, 1, "fridgeD"), R(12, 4, 1, 6, "metalD"), R(12, 16, 1, 10, "metalD")],
        "outline": [[0, 0, 16, 34]]},
    "counter": {"w": 36, "h": 18, "rects": [
        R(0, 0, 36, 6, "cream"), R(0, 6, 36, 12, "stool"), R(12, 6, 1, 12, "stoolD"), R(24, 6, 1, 12, "stoolD"),
        R(5, 10, 2, 1, "k"), R(17, 10, 2, 1, "k"), R(29, 10, 2, 1, "k")], "outline": [[0, 0, 36, 18]]},
    "clock": {"w": 10, "h": 10, "rects": [R(1, 1, 8, 8, "white"), R(4, 2, 1, 4, "k"), R(5, 5, 3, 1, "k")],
              "outline": [[0, 0, 10, 10]]},
    "painting": {"w": 30, "h": 16, "rects": [
        R(0, 0, 30, 16, "frame"), R(2, 2, 26, 7, "sky"), R(21, 3, 3, 3, "sun"), R(2, 9, 26, 5, "hill"),
        R(8, 8, 8, 2, "hill"), R(16, 7, 8, 3, "greenD")], "outline": [[0, 0, 30, 16]]},
    "window": {"w": 32, "h": 12, "rects": [R(0, 0, 32, 12, "k"), R(15, 1, 2, 10, "k")],
               "sky": [[1, 1, 14, 10], [17, 1, 14, 10]]},
    "sofa": {"w": 16, "h": 30, "rects": [
        R(0, 0, 16, 30, "sofa"), R(0, 0, 5, 30, "sofaD"), R(0, 0, 16, 4, "sofaD"), R(0, 26, 16, 4, "sofaD"),
        R(6, 5, 9, 10, "sofaL"), R(6, 15, 9, 10, "sofaL")], "outline": [[0, 0, 16, 30]],
        "seats": [[6, 5], [6, 15]]},
    "coffee_table": {"w": 24, "h": 16, "rects": [R(0, 0, 24, 12, "frame"), R(2, 12, 2, 4, "frameD"), R(20, 12, 2, 4, "frameD")],
                     "outline": [[0, 0, 24, 12]]},
    "meeting_table": {"w": 40, "h": 72, "rects": [R(0, 0, 40, 66, "deskTop"), R(0, 66, 40, 6, "deskFront")],
                      "outline": [[0, 0, 40, 72]]},
    "chair": {"w": 12, "h": 12, "rects": [R(0, 3, 12, 8, "chair"), R(0, 0, 3, 12, "chairD")], "outline": [[0, 0, 12, 12]]},
    "trash": {"w": 8, "h": 10, "rects": [R(0, 1, 8, 9, "metalD"), R(0, 0, 8, 2, "metal")], "outline": [[0, 0, 8, 10]]},
    "phone": {"w": 8, "h": 10, "rects": [R(0, 0, 8, 10, "metalD"), R(1, 1, 6, 3, "k"), R(2, 6, 1, 1, "white"),
                                         R(5, 6, 1, 1, "white"), R(2, 8, 1, 1, "white"), R(5, 8, 1, 1, "white")]},
    "laptop": {"w": 14, "h": 10, "rects": [R(0, 6, 14, 4, "metal"), R(1, 0, 12, 7, "k"), R(2, 1, 10, 5, "screen")],
               "screen": [2, 1, 10, 5]},
    "lamp": {"w": 8, "h": 30, "rects": [R(3, 6, 2, 22, "metalD"), R(0, 0, 8, 6, "cream"), R(1, 28, 6, 2, "k")],
             "outline": [[0, 0, 8, 6]], "bulb": [0, 0, 8, 6]},
    "stool_master": {"w": 12, "h": 8, "rects": [R(0, 0, 12, 5, "chair"), R(0, 5, 12, 2, "chairD")], "outline": [[0, 0, 12, 7]]},
}
for name, f in FURNITURE.items():
    for x, y, w, h, c in f["rects"]:
        assert c in PALETTE, (name, c)
        assert 0 <= x and 0 <= y and x + w <= f["w"] and y + h <= f["h"], (name, x, y, w, h)


# --- plano ---
grid = [["."] * COLS for _ in range(ROWS)]


def fill(c0, r0, c1, r1, ch):
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            grid[r][c] = ch


fill(10, 2, 21, 9, "w"); fill(10, 1, 21, 1, "F")                   # dirección
fill(14, 10, 17, 14, "w")                                         # pasillo
fill(2, 15, 18, 28, "w"); fill(2, 14, 13, 14, "F"); fill(18, 14, 18, 14, "F")  # área de trabajo
fill(19, 15, 31, 19, "t"); fill(19, 14, 31, 14, "F")               # cocina
fill(20, 22, 31, 28, "c"); fill(20, 21, 31, 21, "F"); fill(19, 24, 19, 25, "c")  # descanso + puerta
FLOOR = set("wtc")
for r in range(ROWS):
    for c in range(COLS):
        if grid[r][c] != ".":
            continue
        near = any(0 <= r + dr < ROWS and 0 <= c + dc < COLS and grid[r + dr][c + dc] in FLOOR | {"F"}
                   for dr in (-1, 0, 1) for dc in (-1, 0, 1))
        if near:
            grid[r][c] = "#"
GRID = ["".join(row) for row in grid]


def P(kind, x, y, blocks=(), flip=False, **extra):
    return {"kind": kind, "x": x, "y": y, "flip": flip, "blocks": [list(b) for b in blocks], **extra}


PLACEMENTS = [
    # dirección
    P("window", 176, 18), P("window", 288, 18), P("painting", 233, 17),
    P("plant", 160, 24, [(10, 2)]), P("plant", 336, 24, [(21, 2)]),
    P("lamp", 330, 92, [(20, 6)], role="night_lamp"),
    P("meeting_table", 228, 40, [(14, r) for r in range(2, 7)] + [(15, r) for r in range(2, 7)] + [(16, r) for r in range(2, 7)]),
    *[P("chair", 214, y, [(13, (y + 6) // 16)]) for y in (52, 72, 92)],
    *[P("chair", 270, y, [(17, (y + 6) // 16)], flip=True) for y in (52, 72, 92)],
    P("laptop", 241, 98, role="master_laptop", z=113), P("stool_master", 242, 120),
    # área de trabajo
    P("bookshelf", 48, 216, [(3, 15), (4, 15)]), P("bookshelf", 80, 216, [(5, 15), (6, 15)]),
    P("bookshelf", 160, 216, [(10, 15), (11, 15)]), P("bookshelf", 192, 216, [(12, 15), (13, 15)]),
    P("plant", 32, 232, [(2, 15)]), P("boxes", 112, 228, [(7, 15)]),
    P("plant", 32, 440, [(2, 28)]), P("plant", 288, 440, [(18, 28)]), P("trash", 36, 420, [(2, 26)]),
    # cocina
    P("vending", 312, 214, [(19, 15), (20, 15)]), P("cooler", 340, 222, [(21, 15)]), P("window", 360, 226),
    P("clock", 400, 222), P("trash", 412, 238, [(25, 15)]), P("counter", 432, 230, [(27, 15), (28, 15), (29, 15)]),
    P("fridge", 480, 214, [(30, 15)]),
    # descanso
    P("painting", 400, 337), P("bookshelf", 336, 330, [(21, 22), (22, 22)]), P("bookshelf", 464, 330, [(29, 22), (30, 22)]),
    P("plant", 384, 330, [(24, 22)]), P("plant", 432, 330, [(27, 22)]),
    P("plant", 320, 440, [(20, 28)]), P("plant", 496, 440, [(31, 28)]),
    P("sofa", 352, 376, [(22, 23), (22, 24), (22, 25)], role="sofa_left"),
    P("sofa", 448, 376, [(28, 23), (28, 24), (28, 25)], flip=True, role="sofa_right"),
    P("coffee_table", 388, 384, [(24, 24), (25, 24)]), P("laptop", 393, 385, z=401), P("phone", 308, 360),
]

DESK_TILES = [(3, 17), (8, 17), (13, 17), (3, 21), (8, 21), (13, 21), (3, 25), (8, 25), (13, 25)]
DESKS = []
for c, r in DESK_TILES:
    x, y = c * T, r * T - 6
    DESKS.append({"desk": [x, y], "stool": [x + 11, y + 24], "seat_tile": [c, r + 1],
                  "seated_sprite": [x + 8, y + 16], "visit_tile": [c + 2, r + 1],
                  "blocks": [[c, r], [c + 1, r]]})

SPOTS = {
    "master": {"seat_tile": [15, 7], "seated_sprite": [240, 108], "mug": [262, 92], "audience": [[14, 7], [16, 7]]},
    "kitchen": [[21, 17], [23, 17], [25, 17], [27, 17]],
    "lounge_sofa": [{"tile": [23, 24], "sofa": "sofa_left", "seat": 0}, {"tile": [23, 25], "sofa": "sofa_left", "seat": 1},
                    {"tile": [27, 24], "sofa": "sofa_right", "seat": 0}, {"tile": [27, 25], "sofa": "sofa_right", "seat": 1}],
    "lounge_stand": [[24, 27], [26, 27], [29, 27]],
}
ROOMS = {
    "direccion": {"name": "Dirección", "rect": [10, 1, 21, 9]},
    "trabajo": {"name": "Área de trabajo", "rect": [2, 14, 18, 28]},
    "cocina": {"name": "Cocina", "rect": [19, 14, 31, 19]},
    "descanso": {"name": "Descanso", "rect": [20, 21, 31, 28]},
}

walk = {(c, r) for r, row in enumerate(GRID) for c, ch in enumerate(row) if ch in FLOOR}
blocked = {tuple(b) for p in PLACEMENTS for b in p["blocks"]} | {tuple(b) for d in DESKS for b in d["blocks"]}
for d in DESKS:
    for key in ("seat_tile", "visit_tile"):
        assert tuple(d[key]) in walk and tuple(d[key]) not in blocked, (key, d[key])
for t in SPOTS["kitchen"] + SPOTS["lounge_stand"] + [s["tile"] for s in SPOTS["lounge_sofa"]] + SPOTS["master"]["audience"] + [SPOTS["master"]["seat_tile"]]:
    assert tuple(t) in walk and tuple(t) not in blocked, t

OFFICE = {
    "tile": T, "cols": COLS, "rows": ROWS, "palette": PALETTE, "tiles": TILES, "furniture": FURNITURE,
    "map": {"grid": GRID, "walkable": sorted(FLOOR), "placements": PLACEMENTS, "desks": DESKS, "spots": SPOTS,
            "rooms": ROOMS},
}
HEADER = """// Oficina pixel v4: azulejos, muebles y plano. Diseño de la IA maestra: NO lo modifiques; generado por
// tools/gen_office.py. Azulejos: filas de letras -> tiles.<t>.keys -> palette. Muebles: rects [x,y,w,h,color],
// outline = borde 1px en palette.k. Plano: grid (. vacío, # muro, F cara de muro, w madera, t azulejo, c alfombra),
// placements (x,y en px; blocks = azulejos no caminables; flip = espejo horizontal; z = profundidad
// de dibujo si no es y+h), desks (lugares de agentes en
// orden), spots (maestra, cocina, descanso), rooms.
"""
pathlib.Path(sys.argv[1]).write_text(HEADER + "window.OFFICE = " + json.dumps(OFFICE, ensure_ascii=False) + ";\n")
print("ok", COLS, "x", ROWS, "muebles:", len(PLACEMENTS), "escritorios:", len(DESKS))
