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
- **Respaldo**: con `--to auto`, si un agente agota su cuota se reintenta con los agentes de `fallback_order` que estén configurados.
- **Corridas**: cada una deja `prompt.md`, `events.jsonl`, `last.md`, `checks.log` y `meta.json` en `~/.local/share/ai-delegate/runs/<id>/`. Las corridas cerradas de más de 7 días se borran solas. Las estadísticas viven aparte, en `ledger.jsonl`.
- **Seguridad**: el subproceso recibe un entorno limpio (`--print-env` muestra solo los nombres). Antes de enviar algo se bloquean los secretos (`sk-…`, `ghp_…`, `*_TOKEN=…`, `Bearer …`, llaves privadas) y se reemplazan correos, teléfonos y tarjetas por marcadores. Ojo: el agente sí puede leer los archivos del repo, como tu `.env`.
- **agy sin interfaz**: corre en `--mode accept-edits` (escritura) y `--mode plan` (lectura), sin saltarse permisos. Sin interfaz no puede pedir permisos, así que en `~/.gemini/antigravity-cli/settings.json` solo tiene permitidos comandos de lectura (`ls`, `tree`, `pwd`, `cat`, `head`, `tail`, `wc`, `grep` y `git status/log/diff/show/ls-files`). Además, `rm`, `sudo` y los comandos de git que reescriben historial están negados explícitamente. Todo lo demás se rechaza (también probé que `cat > archivo` y `touch` se rechazan). Edita con sus herramientas de archivos y ai-delegate corre los checks por él.

Otras opciones de `run`: `--task-file`, `--issue` (requiere `gh`), `--context-file`, `--resume <thread>`, `--timeout 20m`, `--model`, `--no-worktree`, `--dry-run`.

## Pruebas

```bash
python3 -m pytest -q
```

## Oficina pixel

Ejecuta `ai-delegate ui` para abrir la oficina en `http://127.0.0.1:8765`.
Puedes elegir otro puerto con `--port 8766` o evitar abrir el navegador con `--no-open`.

En los hooks de Claude Code (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`Notification`, `Stop`, `SubagentStop` y `SessionEnd`), configura el comando
`ai-delegate claude-status --from-hook`. Lee el JSON del hook por stdin y guarda
estado, nombre de herramienta, fecha y la lista mínima de subagentes, siempre en silencio.
También puedes usar `ai-delegate claude-status waiting` manualmente.

## Agregar una IA

Cada entrada de `agents` registra un destino disponible para `--to` y `[routing]`.
Los tipos `codex` y `agy` usan sus protocolos existentes; `generic` ejecuta un CLI
que responde texto plano, sin JSON. Por ejemplo:

```toml
fallback_order = ["codex", "agy", "opencode"]

[agents.opencode]
type = "generic"
display = "OpenCode"
color = "#f0a500"
bin = "opencode"
args = ["run", "{prompt}"]
look = { hair = "#2e5d4b", color = "#f0a500" }
quota = "none"
```

`args` sustituye `{prompt}` y `{cwd}` sin pasar por un shell. Usa
`ai-delegate --to opencode "tarea"`. Los runners genéricos reciben la tarea
original junto con el feedback y las correcciones de checks porque no reanudan
conversaciones. `[main]` configura el nombre, display y color de la sesión principal.

## Cuota y subagentes

La taza de cuota usa datos reales de Codex: el último rollout en
`agents.codex.home/.codex/sessions/` (o tu HOME), dentro de los últimos siete días.
Expone las ventanas de 5 horas y 7 días, con su fecha de reinicio; se cachea 30 segundos.
Para agy, `quota = "budget"` estima el consumo con los tokens de las corridas de hoy
respecto a `daily_token_budget`. El presupuesto por defecto es 0 (desconocido):
se muestra el consumo en tokens sin inventar un porcentaje. `quota = "none"`
no aporta datos. Una corrida reciente en `cuota-agotada` fuerza 0 durante 30 minutos.

Cualquier script, por ejemplo un statusline de Claude, puede escribir
`claude-quota.json` en `data_dir()` (`AI_DELEGATE_HOME` o
`~/.local/share/ai-delegate`) con este formato:

```json
{"windows": [{"label": "5 h", "used_pct": 35, "resets_at": null}]}
```

Esta fuente se identifica como `archivo`; sin archivo la cuota de Claude es desconocida.
`resets_at` admite una fecha ISO o `null`.

Los hooks de Claude siguen `Task`/`Agent` con id, etiqueta y fecha, sin guardar
`description` ni `prompt`; expiran a los 30 minutos y se limitan a ocho entradas.
Los streams de Codex y agy publican sus subagentes activos durante la ronda y los
limpian al terminar. `/api/state` devuelve el main primero y todos los agentes como
lista, con cuota y subagentes; también incluye los últimos 40 eventos de entrega.
`/api/run/<id>` incluye los eventos y subagentes de la corrida.

Si un feedback, escalamiento o corrección automática deja el diff igual, la corrida
queda en `sin-cambios`, conserva el worktree y permite revisar, dar feedback, escalar
o descartar. Un resumen ilegible añade un aviso para revisar el diff antes de confiar.

## Instalar en un equipo nuevo

Con Python ≥3.11 y git configurado (`user.name` y `user.email`), clona este repo y entra en él:

```sh
git clone <URL-del-repo-ai-delegate>
cd ai-delegate
python3 ai_delegate.py setup
```

El asistente detecta las CLIs, pregunta qué IA será la maestra y tu nombre, instala las instrucciones,
permisos y enlace, y respalda los archivos que modifica. Puedes usar `--master codex --user-name Ana --yes`
o revisar los cambios con `--dry-run --yes`. Si lo indica, agrega `~/.local/bin` a tu PATH.
Completa los logins pendientes (`codex login`, `agy` siguiendo su flujo y `claude`) y verifica:

```sh
ai-delegate doctor
ai-delegate doctor --live  # prueba real de respuesta; consume uso de las IAs
```

## Cambiar la IA maestra

```sh
ai-delegate master        # maestra actual y candidatas instaladas
ai-delegate master codex # también acepta claude o agy
```

El cambio mueve el bloque de instrucciones entre los archivos personales de las IAs y ajusta los hooks
de Claude. La maestra revisa y recibe los escalamientos; las otras IAs son los destinos delegables.
La actividad se detecta también desde sus sesiones locales, sin depender de hooks.
