# ai-delegate

La sesión principal (Claude) planea, diseña y revisa. **Codex** y **Antigravity (`agy`)** programan.
La herramienta reparte las tareas, corre tus checks y devuelve solo un resumen corto, así la sesión principal no gasta contexto.

Funciona en cualquier proyecto. Solo usa la librería estándar de Python 3.11 o superior.

## Instalación

```bash
ln -sf ~/Documentos/Proyectos/ai-delegate/ai_delegate.py ~/.local/bin/ai-delegate
```

Codex y agy usan tus sesiones ya iniciadas. ai-delegate nunca lee ni guarda credenciales.

## Quién hace qué (`--kind`)

| Tipo | Agente | Modo |
|---|---|---|
| `design`, `security` | **la sesión principal**: no se delegan (sale con código 3) | — |
| `feature`, `bugfix`, `refactor`, `api` | codex | write |
| `review`, `summarize` | codex | read |
| `test`, `docs`, `mock`, `i18n`, `chore`, `image` | agy | write |
| `research` | agy | read |

Puedes cambiar estas reglas en `~/.config/ai-delegate/config.toml` (ver `config.example.toml`).

## Ciclo

```text
ai-delegate --kind feature --dir <repo> "tarea"   # worktree propio + checks + corrección automática
ai-delegate diff <id> [--stat]                    # revisar solo el diff
ai-delegate feedback <id> "qué corregir"          # vuelve al mismo agente (máx. 2 rondas)
ai-delegate escalate <id>                         # agy → codex → sesión principal
ai-delegate merge <id>  |  discard <id>
ai-delegate list | show <id> | stats
```

- **Trabajo aislado**: en modo `write` dentro de un repo git, el agente trabaja en `~/.local/share/ai-delegate/worktrees/<id>`, en la rama `ai/<id>`. Tu copia no se toca hasta `merge`. `node_modules`, `.venv` y `venv` se enlazan desde tu copia para que los checks corran.
- **Checks**: se detectan solos (scripts `lint`/`typecheck`/`test` de npm, pnpm, yarn o bun, o pytest). También puedes pasar `--check "cmd"` o `--check none`. Si fallan, la salida vuelve al agente hasta `--max-fix-rounds` veces (3 por defecto).
- **Respaldo**: con `--to auto`, si un agente agota su cuota se reintenta con el otro.
- **Corridas**: cada una deja `prompt.md`, `events.jsonl`, `last.md`, `checks.log` y `meta.json` en `~/.local/share/ai-delegate/runs/<id>/`. Las corridas cerradas de más de 7 días se borran solas. Las estadísticas viven aparte, en `ledger.jsonl`.
- **Seguridad**: el subproceso recibe un entorno limpio (`--print-env` muestra solo los nombres). Antes de enviar algo se bloquean los secretos (`sk-…`, `ghp_…`, `*_TOKEN=…`, `Bearer …`, llaves privadas) y se reemplazan correos, teléfonos y tarjetas por marcadores. Ojo: el agente sí puede leer los archivos del repo, como tu `.env`.
- **agy sin interfaz**: corre en `--mode accept-edits` (escritura) y `--mode plan` (lectura), sin saltarse permisos. No puede usar la terminal, así que edita con sus herramientas de archivos y ai-delegate corre los checks por él. En lectura puede investigar en la web, pero no leer repos locales; por eso `summarize` va a codex.

Otras opciones de `run`: `--task-file`, `--issue` (requiere `gh`), `--context-file`, `--resume <thread>`, `--timeout 20m`, `--model`, `--no-worktree`, `--dry-run`.

## Pruebas

```bash
python3 -m pytest -q
```
