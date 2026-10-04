import json, pathlib, sys

def row(*parts, w=16):
    r = "".join(parts)
    assert len(r) == w, (r, len(r))
    return r

# Cabeza: contorno k en col 3 y 12, interior cols 4-11 (8 px). Caras editan ese interior.
claude = [
    row(".....", "kkkkkk", "....."),
    row("....", "k", "hhhhhh", "k", "...."),
    row("...", "k", "hhhhhhhh", "k", "..."),
    row("...", "k", "hhhhsssh", "k", "..."),
    row("...", "k", "hhssssss", "k", "..."),
    row("...", "k", "hkssssks", "k", "..."),
    row("...", "k", "srssssrs", "k", "..."),
    row("...", "k", "ssskksss", "k", "..."),
    row("....", "k", "ssssss", "k", "...."),
    row(".....", "k", "SSSS", "k", "....."),
    row("..", "k", "caaaaaaaac", "k", ".."),
    row(".", "k", "cccccccccccc", "k", "."),
    row(".", "k", "CccccccccccC", "k", "."),
    row(".", "k", "CccccaaccccC", "k", "."),
    row(".", "k", "ssCccccccCss", "k", "."),
    row(".", "kkkkkkkkkkkkkk", "."),
]
codex = [
    row("....", "kk", ".", "kkk", ".", "kk", "..."),
    row("...", "k", "hhhhhhhh", "k", "..."),
    row("..", "a", "k", "hhhhhhhh", "k", "a", ".."),
    row(".", "aA", "k", "hhhshhhh", "k", "Aa", "."),
    row(".", "aA", "k", "hsssssss", "k", "Aa", "."),
    row(".", "aA", "k", "skssssks", "k", "Aa", "."),
    row("..", "a", "k", "ssssssss", "k", "a", ".."),
    row("...", "k", "ssskksss", "k", "..."),
    row("....", "k", "ssssss", "k", "...."),
    row(".....", "k", "SSSS", "k", "....."),
    row("..", "k", "cccccccccc", "k", ".."),
    row(".", "k", "cccccccccccc", "k", "."),
    row(".", "k", "CccccccccccC", "k", "."),
    row(".", "k", "CccccaaccccC", "k", "."),
    row(".", "k", "ssCccccccCss", "k", "."),
    row(".", "kkkkkkkkkkkkkk", "."),
]
agy = [
    row(".....", "kkkkkk", "....."),
    row("....", "k", "hhhhhh", "k", "...."),
    row("...", "k", "hhhhhhah", "k", "..."),
    row("..", "k", "hhhhhhhshh", "k", ".."),
    row("..", "k", "h", "hhssssss", "h", "k", ".."),
    row("..", "k", "h", "skssssks", "h", "k", ".."),
    row("..", "k", "H", "ssssssss", "H", "k", ".."),
    row("..", "k", "H", "ssskksss", "H", "k", ".."),
    row("..", "k", "HH", "ssssss", "HH", "k", ".."),
    row("..", "k", "H", ".", "k", "SSSS", "k", ".", "H", "k", ".."),
    row("..", "k", "ccgccccgcc", "k", ".."),
    row(".", "k", "cccccccccccc", "k", "."),
    row(".", "k", "CccccccccccC", "k", "."),
    row(".", "k", "CccccggccccC", "k", "."),
    row(".", "k", "ssCccccccCss", "k", "."),
    row(".", "kkkkkkkkkkkkkk", "."),
]

def icon(*rows):
    out = [".kkkkk."] + ["k" + r + "k" for r in rows] + [".kkkkk."]
    for r in out: assert len(r) == 7, r
    return out

emotes = {
    "alert":    icon("wwrww", "wwrww", "wwrww", "wwwww", "wwrww"),
    "question": icon("wbbbw", "wwwbw", "wwbbw", "wwwww", "wwbww"),
    "done":     icon("wwwwg", "wwwgw", "gwgww", "wgwww", "wwwww"),
    "fail":     icon("rwwwr", "wrwrw", "wwrww", "wrwrw", "rwwwr"),
    "wait":     icon("yyyyy", "wyyyw", "wwyww", "wywyw", "yyyyy"),
    "sleep":    icon("bbbbw", "wwbww", "wbwww", "bbbbw", "wwwwb"),
    "look":     icon("wwwww", "wbbbw", "bbkbb", "wbbbw", "wwwww"),
}
particles = {
    "codex":  ["a.a", ".a.", "a.a"],               # bits menta
    "agy":    ["..y..", "..y..", "yyyyy", "..y..", "..y.."],  # destello
    "claude": ["kkk", "kak", "kak", "kkk"],        # hojita de notas
}
for name, p in particles.items():
    assert len({len(r) for r in p}) == 1, name


# --- Cuerpo completo (16x24): cabeza+torso del sprite sentado (filas 0-13) + piernas comunes ---
LEGS = {
    "stand": [
        row(".", "k", "CccccccccccC", "k", "."),
        row(".", "k", "sCccccccccCs", "k", "."),
        row("..", "k", "pppppppppp", "k", ".."),
        row("...", "k", "pppppppp", "k", "..."),
        row("...", "k", "ppp", "kk", "ppp", "k", "..."),
        row("...", "kPpk", "..", "kpPk", "..."),
        row("...", "kPpk", "..", "kpPk", "..."),
        row("...", "kPpk", "..", "kpPk", "..."),
        row("..", "kbbbk", "..", "kbbbk", ".."),
        row("..", "kkkkk", "..", "kkkkk", ".."),
    ],
}
LEGS["walkA"] = LEGS["stand"][:7] + [
    row("..", "kbbbk", "..", "kpPk", "..."),
    row("..", "kkkkk", "..", "kbbbk", ".."),
    row(".........", "kkkkk", ".."),
]
LEGS["walkB"] = LEGS["stand"][:7] + [
    row("...", "kPpk", "..", "kbbbk", ".."),
    row("..", "kbbbk", "..", "kkkkk", ".."),
    row("..", "kkkkk", "........."),
]
bodies = {}
generic = [r.replace("r", "s") for r in claude]  # plantilla para IAs nuevas: sin rubor
for name, seated in (("claude", claude), ("codex", codex), ("agy", agy), ("generic", generic)):
    bodies[name] = {pose: seated[:14] + legs for pose, legs in LEGS.items()}
    for pose, rows in bodies[name].items():
        assert len(rows) == 24 and all(len(r) == 16 for r in rows), (name, pose)

mini = [  # becario / subagente, 10x10, usa la paleta de su jefe
    row("...", "kkkk", "...", w=10),
    row("..", "k", "hhhh", "k", "..", w=10),
    row(".", "k", "h", "ssss", "h", "k", ".", w=10),
    row(".", "k", "skssks", "k", ".", w=10),
    row(".", "k", "ssssss", "k", ".", w=10),
    row("..", "k", "ssss", "k", "..", w=10),
    row(".", "k", "cccccc", "k", ".", w=10),
    row("k", "cccccccc", "k", w=10),
    row(".", "k", "cccccc", "k", ".", w=10),
    row("..", "kk", "..", "kk", "..", w=10),
]
items = {
    "paper":      ["kkkkk", "kwwwk", "kllwk", "kwwwk", "kllwk", "kkkkk"],
    "paper_done": ["kkkkk", "kwwwk", "kggwk", "kwwwk", "kggwk", "kkkkk"],
    "mug": ["kkkkk..", "kxxxkk.", "kxxxk.k", "kxxxk.k", "kxxxk.k", "kxxxkk.", "kxxxk..", "kkkkk.."],
    "puff": [".w.w.", "w...w", ".....", "w...w", ".w.w."],
}
for k, v in items.items():
    assert len({len(r) for r in v}) == 1, k

# --- v4: espaldas (up) y perfil (side, mirando a la derecha; izquierda = espejo) ---
def back_head(name):
    rows = [
        row(".....", "kkkkkk", "....."),
        row("....", "k", "hhhhhh", "k", "...."),
        row("...", "k", "hhhhhhhh", "k", "..."),
        row("...", "k", "hhhhhhhh", "k", "..."),
        row("...", "k", "hhhhhhhh", "k", "..."),
        row("...", "k", "hhhhhhhh", "k", "..."),
        row("...", "k", "hhhhhhhh", "k", "..."),
        row("...", "k", "shhhhhhs", "k", "..."),
        row("....", "k", "hhhhhh", "k", "...."),
        row(".....", "k", "SSSS", "k", "....."),
    ]
    if name == "codex":
        rows[1] = row("...", "a", "hhhhhhhh", "a", "...")
        for i in (3, 4, 5):
            rows[i] = row(".", "aA", "k", "hhhhhhhh", "k", "Aa", ".")
        rows[6] = row("..", "a", "k", "hhhhhhhh", "k", "a", "..")
    if name == "agy":
        rows[2] = row("...", "k", "hhhhhhah", "k", "...")
        for i in (7, 8, 9):
            rows[i] = row("...", "k", "HHHHHHHH", "k", "...")
    return rows

BACK_TORSO = [
    row("..", "k", "cccccccccc", "k", ".."),
    row(".", "k", "cccccccccccc", "k", "."),
    row(".", "k", "CccccccccccC", "k", "."),
    row(".", "k", "CccccccccccC", "k", "."),
]

def side_head(name):
    rows = [
        row("......", "kkkkk", "....."),
        row(".....", "k", "hhhhh", "k", "...."),
        row("....", "k", "hhhhhhh", "k", "..."),
        row("....", "k", "hhhhsss", "k", "..."),
        row("....", "k", "hhhssss", "k", "..."),
        row("....", "k", "hhsssks", "k", "..."),
        row("....", "k", "hsssssss", "k", ".."),
        row("....", "k", "sssssks", "k", "..."),
        row(".....", "k", "sssss", "k", "...."),
        row("......", "k", "SSS", "k", "....."),
    ]
    if name == "codex":
        rows[4] = row("....", "k", "hhAaaas", "k", "...")
        rows[5] = row("....", "k", "hhAaaks", "k", "...")
    if name == "agy":
        rows[2] = row("....", "k", "hhhhhah", "k", "...")
        rows[6] = row("....", "k", "Hsssssss", "k", "..")
        rows[7] = row("...", "kH", "sssssks", "k", "...")
        rows[8] = row("...", "kH", "kssssk", ".....")
    if name == "claude":
        rows[6] = row("....", "k", "hssrssss", "k", "..")
    return rows

SIDE_BODY = {
    "stand": [
        row("....", "k", "cccccc", "k", "...."),
        row("....", "k", "cccccc", "k", "...."),
        row("....", "k", "Ccccc", "C", "k", "...."),
        row("....", "k", "CccscC", "k", "...."),
        row("....", "k", "Ccccc", "C", "k", "...."),
        row("....", "k", "pppppp", "k", "...."),
        row("....", "k", "pppppp", "k", "...."),
        row(".....", "k", "pPpP", "k", "....."),
        row(".....", "k", "pPpP", "k", "....."),
        row(".....", "k", "pPpP", "k", "....."),
        row(".....", "k", "bbbbb", "k", "...."),
        row(".....", "kkkkkkk", "...."),
        row("................"),
        row("................"),
    ],
}
SIDE_BODY["walkA"] = SIDE_BODY["stand"][:7] + [
    row("....", "kpPk", "kPpk", "...."),
    row("...", "kpPk", "..", "kPpk", "..."),
    row("..", "kpPk", "....", "kPpk", ".."),
    row("..", "kbbbk", "...", "kbbbk", "."),
    row("..", "kkkkk", "...", "kkkkk", "."),
    row("................"),
    row("................"),
]
SIDE_BODY["walkB"] = SIDE_BODY["stand"]

dirs = {}
for name, seated in (("claude", claude), ("codex", codex), ("agy", agy), ("generic", generic)):
    up_rows = back_head(name if name != "generic" else "claude") + BACK_TORSO
    up = {pose: up_rows + legs for pose, legs in LEGS.items()}
    sh = side_head(name if name != "generic" else "x")
    if name == "claude":
        torso0 = row("....", "k", "caaccc", "k", "....")
        side_body = {pose: [torso0] + rows[1:] for pose, rows in SIDE_BODY.items()}
    else:
        side_body = SIDE_BODY
    side = {pose: sh + side_body[pose] for pose in SIDE_BODY}
    # sentado de espaldas frente al escritorio: cabeza + torso, sin piernas (las tapa el banco)
    seated_back = back_head(name if name != "generic" else "claude") + BACK_TORSO + [
        row(".", "k", "sCccccccccCs", "k", "."),
        row("..", "k", "pppppppppp", "k", ".."),
    ]
    dirs[name] = {"down": bodies[name], "up": up, "side": side, "seated_back": seated_back}
    for d, poses in dirs[name].items():
        if d == "seated_back":
            assert len(poses) == 16 and all(len(r) == 16 for r in poses), (name, d)
            continue
        for pose, rows in poses.items():
            assert len(rows) == 24 and all(len(r) == 16 for r in rows), (name, d, pose, len(rows))

art = {
    "size": {"character": [16, 16], "body": [16, 24], "mini": [10, 10], "emote": [7, 7]},
    "palettes": {
        "common": {"k": "#1a1726", "s": "#f2c6a0", "S": "#d9a07a", "b": "#2a2433"},
        "pants": {"claude": {"p": "#3b3f5c", "P": "#2c2f47"}, "codex": {"p": "#3b4a5e", "P": "#2c3848"},
                  "agy": {"p": "#2b2f6b", "P": "#1f2250"}},
        "items": {"k": "#1a1726", "w": "#fff1e8", "l": "#a8a3c1", "g": "#2fbf71", "x": "#e8e2d0"},
        "mug_fill": {"high": "#8b5a2b", "mid": "#c98a00", "low": "#ff5d73", "steam": "#fff1e8"},
        "claude": {"h": "#6b3e2e", "c": "#d97757", "C": "#b45a3c", "a": "#f4e4c1", "r": "#f29c9c"},
        "codex":  {"h": "#24242c", "c": "#3a4045", "C": "#262a2e", "a": "#3ddc97", "A": "#23a571"},
        "agy":    {"h": "#dfe6ff", "H": "#a9b4e8", "c": "#5b6cff", "C": "#3f4bd1", "a": "#ffd75e", "g": "#8fd3ff"},
        "emote":  {"k": "#1a1726", "w": "#fff1e8", "r": "#ff5d73", "b": "#4fa8ff", "g": "#2fbf71", "y": "#ffb627"},
        "particles": {"codex": {"a": "#3ddc97"}, "agy": {"y": "#ffd75e"}, "claude": {"k": "#1a1726", "a": "#f4e4c1"}},
    },
    "characters": {"claude": claude, "codex": codex, "agy": agy, "generic": generic},
    "bodies": bodies,
    "directions": dirs,
    "mini": mini,
    "items": items,
    "faceOriginCol": 4,
    "faces": {
        "base":  {"5": "_k____k_", "7": "___kk___"},
        "blink": {"5": "_s____s_", "6": "_k____k_"},
        "happy": {"4": "_k____k_", "5": "_s____s_", "7": "__kkkk__"},
        "sad":   {"5": "_s____s_", "6": "_k____k_", "7": "___ss___", "8": "___kk___"},
    },
    "emotes": emotes,
    "particles": particles,
    "confetti": ["#ff5d73", "#ffd75e", "#3ddc97", "#4fa8ff", "#d97757", "#b28dff"],
}
for name, rows in art["characters"].items():
    if name == "generic":
        continue
    assert len(rows) == 16, name
    pal = {**art["palettes"]["common"], **art["palettes"][name]}
    used = set("".join(rows)) - {"."}
    assert used <= set(pal), (name, used - set(pal))

header = """// Arte pixel de la oficina de ai-delegate.
// Lo define la sesión principal (diseño): NO lo modifiques; solo léelo.
// Cada sprite es una lista de filas; un carácter = un pixel; '.' = transparente.
// Paleta de un personaje = palettes.common + palettes.<personaje>.
// faces: reemplazan, a partir de la columna faceOriginCol, las filas indicadas;
// '_' conserva el pixel original.
// bodies.<nombre>.<stand|walkA|walkB>: cuerpo completo 16x24 para caminar; paleta + palettes.pants.<nombre>.
// characters.generic / bodies.generic: plantilla para IAs nuevas; su paleta se deriva de agents.<n>.look.
// directions.<nombre>.<down|up|side>.<stand|walkA|walkB>: 16x24 en 4 direcciones (izquierda = side en
// espejo); directions.<nombre>.seated_back: 16x16 sentado de espaldas frente a su monitor.
// mini: becario (subagente) 10x10 con la paleta de su jefe. items: paper, paper_done, mug ('x' = celdas de
// líquido, se llenan de abajo hacia arriba con palettes.mug_fill), puff (aparición de un becario).
"""
out = header + "window.PIXEL_ART = " + json.dumps(art, indent=2, ensure_ascii=False) + ";\n"
pathlib.Path(sys.argv[1]).write_text(out)
print("ok", len(out), "bytes")
