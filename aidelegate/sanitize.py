"""Revisión de texto antes de enviarlo a un proveedor externo.

Bloquea secretos (o los redacta, para salidas generadas como logs de tests)
y reemplaza correos, teléfonos y tarjetas por marcadores. Los mensajes de
error nunca incluyen el valor encontrado, solo el tipo y la línea.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .errors import SecretFound

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("llave tipo sk-", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("token de GitHub", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("llave de AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("llave de Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("token de Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("llave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("token Bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-]{20,}=*")),
    (
        "asignación de secreto",
        re.compile(
            r"(?<![A-Za-z0-9_])[A-Z0-9_]*(?:TOKEN|PASSWORD|PASSWD|SECRET|API_KEY|APIKEY)[ \t]*[=:][ \t]*"
            # valores literales; no referencias como $VAR, <placeholder>, process.env.X o tipos
            r"(?![\"']?(?:\$|<|\*{3}|process\.|os\.|import\.|getenv|env\.|(?:string|number|boolean|any)\b))"
            r"[\"']?[A-Za-z0-9_\-./+=~]{6,}"
        ),
    ),
]

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"(?<![\d\w])(?:\d[ \-]?){12,18}\d(?![\d\w])")
_PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{10,14}"
    r"|(?:\+\d{1,3}[ .\-]?)?(?:\(\d{2,3}\)[ .\-]?|\d{2,3}[ .\-])\d{3,4}[ .\-]\d{4})(?![\w.])"
)

OnSecret = Literal["block", "redact"]


@dataclass(frozen=True)
class Finding:
    kind: str
    line: int


def find_secrets(text: str) -> list[Finding]:
    findings = []
    for kind, pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(Finding(kind, text.count("\n", 0, match.start()) + 1))
    return sorted(findings, key=lambda f: f.line)


def redact_secrets(text: str) -> str:
    for _, pattern in _SECRET_PATTERNS:
        text = pattern.sub("[SECRETO-REMOVIDO]", text)
    return text


def mask_pii(text: str) -> str:
    text = _EMAIL.sub("[CORREO]", text)
    text = _CARD.sub(_mask_card, text)
    return _PHONE.sub("[TELÉFONO]", text)


def sanitize(text: str, *, source: str, on_secret: OnSecret = "block") -> str:
    findings = find_secrets(text)
    if findings and on_secret == "block":
        raise SecretFound(_blocked_message(source, findings))
    if findings:
        text = redact_secrets(text)
    return mask_pii(text)


def _blocked_message(source: str, findings: list[Finding]) -> str:
    where = ", ".join(f"{f.kind} (línea {f.line})" for f in findings[:5])
    return (
        f"Envío bloqueado: {source} contiene posibles secretos: {where}. "
        "Quítalos o usa el nombre de la variable de entorno en lugar de su valor."
    )


def _mask_card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group())
    if 13 <= len(digits) <= 19 and _luhn_ok(digits):
        return "[TARJETA]"
    return match.group()


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0
