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
| `security` | **la sesión principal**: no se delega (sale con código 3) | — |
| `design` | codex (o `--to agy`) implementa la especificación de la sesión principal | write |
| `feature`, `bugfix`, `refactor`, `api` | codex | write |
| `review` | codex | read |
| `test`, `docs`, `mock`, `i18n`, `chore`, `image` | agy | write |
| `research`, `summarize` | agy | read |

Puedes cambiar estas reglas en `~/.config/ai-delegate/config.toml` (ver `config.example.toml`).

## Diseño

El diseño lo decide la sesión principal; Codex y agy solo lo codifican, porque cada uno tiene su propio estilo y lo impondría.

1. La sesión principal escribe la especificación con [templates/design-spec.md](templates/design-spec.md): tokens, layout por breakpoint, componentes con sus estados, movimiento, textos y criterios de aceptación, siempre con valores concretos.
2. `ai-delegate --kind design --design-spec hero.md --dir <repo> "implementa el hero"`. Sin `--design-spec` la tarea se rechaza.
3. El agente recibe la regla de implementarla **exactamente**: nada inventado, nada "mejorado", y lo que falte queda marcado como `TODO(diseño)`.
4. La sesión principal revisa el diff contra la especificación (y la vista en el navegador) y regresa las diferencias con `feedback`, dando valores exactos.

En las tareas que no son de diseño (`feature`, `bugfix`…), el agente tiene prohibido tocar estilos.

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
- **agy sin interfaz**: corre en `--mode accept-edits` (escritura) y `--mode plan` (lectura), sin saltarse permisos. Sin interfaz no puede pedir permisos, así que en `~/.gemini/antigravity-cli/settings.json` solo tiene permitidos comandos de lectura (`ls`, `tree`, `pwd`, `cat`, `head`, `tail`, `wc`, `grep` y `git status/log/diff/show/ls-files`). Además, `rm`, `sudo` y los comandos de git que reescriben historial están negados explícitamente. Todo lo demás se rechaza (también probé que `cat > archivo` y `touch` se rechazan). Edita con sus herramientas de archivos y ai-delegate corre los checks por él.

Otras opciones de `run`: `--task-file`, `--issue` (requiere `gh`), `--context-file`, `--resume <thread>`, `--timeout 20m`, `--model`, `--no-worktree`, `--dry-run`.

## Pruebas

```bash
python3 -m pytest -q
```
