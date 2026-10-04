// Arte pixel de la oficina de ai-delegate.
// Lo define la sesión principal (diseño): NO lo modifiques; solo léelo.
// Cada sprite es una lista de filas; un carácter = un pixel; '.' = transparente.
// Paleta de un personaje = palettes.common + palettes.<personaje>.
// faces: reemplazan, a partir de la columna faceOriginCol, las filas indicadas;
// '_' conserva el pixel original.
window.PIXEL_ART = {
  "size": {
    "character": [
      16,
      16
    ],
    "emote": [
      7,
      7
    ]
  },
  "palettes": {
    "common": {
      "k": "#1a1726",
      "s": "#f2c6a0",
      "S": "#d9a07a"
    },
    "claude": {
      "h": "#6b3e2e",
      "c": "#d97757",
      "C": "#b45a3c",
      "a": "#f4e4c1",
      "r": "#f29c9c"
    },
    "codex": {
      "h": "#24242c",
      "c": "#3a4045",
      "C": "#262a2e",
      "a": "#3ddc97",
      "A": "#23a571"
    },
    "agy": {
      "h": "#dfe6ff",
      "H": "#a9b4e8",
      "c": "#5b6cff",
      "C": "#3f4bd1",
      "a": "#ffd75e",
      "g": "#8fd3ff"
    },
    "emote": {
      "k": "#1a1726",
      "w": "#fff1e8",
      "r": "#ff5d73",
      "b": "#4fa8ff",
      "g": "#2fbf71",
      "y": "#ffb627"
    },
    "particles": {
      "codex": {
        "a": "#3ddc97"
      },
      "agy": {
        "y": "#ffd75e"
      },
      "claude": {
        "k": "#1a1726",
        "a": "#f4e4c1"
      }
    }
  },
  "characters": {
    "claude": [
      ".....kkkkkk.....",
      "....khhhhhhk....",
      "...khhhhhhhhk...",
      "...khhhhssshk...",
      "...khhssssssk...",
      "...khkssssksk...",
      "...ksrssssrsk...",
      "...kssskksssk...",
      "....kssssssk....",
      ".....kSSSSk.....",
      "..kcaaaaaaaack..",
      ".kcccccccccccck.",
      ".kCccccccccccCk.",
      ".kCccccaaccccCk.",
      ".kssCccccccCssk.",
      ".kkkkkkkkkkkkkk."
    ],
    "codex": [
      "....kk.kkk.kk...",
      "...khhhhhhhhk...",
      "..akhhhhhhhhka..",
      ".aAkhhhshhhhkAa.",
      ".aAkhssssssskAa.",
      ".aAksksssskskAa.",
      "..aksssssssska..",
      "...kssskksssk...",
      "....kssssssk....",
      ".....kSSSSk.....",
      "..kcccccccccck..",
      ".kcccccccccccck.",
      ".kCccccccccccCk.",
      ".kCccccaaccccCk.",
      ".kssCccccccCssk.",
      ".kkkkkkkkkkkkkk."
    ],
    "agy": [
      ".....kkkkkk.....",
      "....khhhhhhk....",
      "...khhhhhhahk...",
      "..khhhhhhhshhk..",
      "..khhhsssssshk..",
      "..khsksssskshk..",
      "..kHssssssssHk..",
      "..kHssskksssHk..",
      "..kHHssssssHHk..",
      "..kH.kSSSSk.Hk..",
      "..kccgccccgcck..",
      ".kcccccccccccck.",
      ".kCccccccccccCk.",
      ".kCccccggccccCk.",
      ".kssCccccccCssk.",
      ".kkkkkkkkkkkkkk."
    ]
  },
  "faceOriginCol": 4,
  "faces": {
    "base": {
      "5": "_k____k_",
      "7": "___kk___"
    },
    "blink": {
      "5": "_s____s_",
      "6": "_k____k_"
    },
    "happy": {
      "4": "_k____k_",
      "5": "_s____s_",
      "7": "__kkkk__"
    },
    "sad": {
      "5": "_s____s_",
      "6": "_k____k_",
      "7": "___ss___",
      "8": "___kk___"
    }
  },
  "emotes": {
    "alert": [
      ".kkkkk.",
      "kwwrwwk",
      "kwwrwwk",
      "kwwrwwk",
      "kwwwwwk",
      "kwwrwwk",
      ".kkkkk."
    ],
    "question": [
      ".kkkkk.",
      "kwbbbwk",
      "kwwwbwk",
      "kwwbbwk",
      "kwwwwwk",
      "kwwbwwk",
      ".kkkkk."
    ],
    "done": [
      ".kkkkk.",
      "kwwwwgk",
      "kwwwgwk",
      "kgwgwwk",
      "kwgwwwk",
      "kwwwwwk",
      ".kkkkk."
    ],
    "fail": [
      ".kkkkk.",
      "krwwwrk",
      "kwrwrwk",
      "kwwrwwk",
      "kwrwrwk",
      "krwwwrk",
      ".kkkkk."
    ],
    "wait": [
      ".kkkkk.",
      "kyyyyyk",
      "kwyyywk",
      "kwwywwk",
      "kwywywk",
      "kyyyyyk",
      ".kkkkk."
    ],
    "sleep": [
      ".kkkkk.",
      "kbbbbwk",
      "kwwbwwk",
      "kwbwwwk",
      "kbbbbwk",
      "kwwwwbk",
      ".kkkkk."
    ],
    "look": [
      ".kkkkk.",
      "kwwwwwk",
      "kwbbbwk",
      "kbbkbbk",
      "kwbbbwk",
      "kwwwwwk",
      ".kkkkk."
    ]
  },
  "particles": {
    "codex": [
      "a.a",
      ".a.",
      "a.a"
    ],
    "agy": [
      "..y..",
      "..y..",
      "yyyyy",
      "..y..",
      "..y.."
    ],
    "claude": [
      "kkk",
      "kak",
      "kak",
      "kkk"
    ]
  },
  "confetti": [
    "#ff5d73",
    "#ffd75e",
    "#3ddc97",
    "#4fa8ff",
    "#d97757",
    "#b28dff"
  ]
};
