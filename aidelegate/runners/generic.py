"""CLI configurable que devuelve texto plano."""

import re
from pathlib import Path

from .base import Runner


class GenericRunner(Runner):
    plain_text = True
    args: list[str] = []

    def argv(self, prompt: str, mode: str, cwd: Path, resume_id: str | None) -> list[str]:
        values = {"prompt": prompt, "cwd": str(cwd)}
        return [self.binary, *(re.sub(r"\{(prompt|cwd)\}", lambda m: values[m[1]], arg)
                               for arg in self.args)]
