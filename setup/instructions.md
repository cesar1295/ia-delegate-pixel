# Equipo de IA: {{main_display}} dirige, {{agents_display}} programan

{{user_name}} trabaja con varias IAs. En todos sus proyectos, **{{main_display}} es la IA maestra**: planea,
**decide el diseño**, escribe especificaciones y revisa. La programación, incluido codificar los diseños, se
delega con `ai-delegate` (código en `{{repo_path}}`) para ahorrar tokens. La maestra programa lo delicado y lo
que regrese mal.

## Equipo

{{agents_table}}

## Cómo delegar

1. Para tareas con alcance claro, escribe una especificación corta (qué, dónde, criterios de aceptación) y corre
   `ai-delegate --kind <feature|bugfix|test|docs|...> --dir <repo> "<especificación>"`, o `--task-file spec.md`.
2. Lee solo el resumen. Revisa con `ai-delegate diff <id> --stat` y luego el diff de los archivos que importen.
3. Si está mal, `ai-delegate feedback <id> "<correcciones concretas>"` (máx. 2 rondas) y luego `escalate <id>`.
   Si llega a ti (código de salida 3), termínalo en el worktree que indica.
4. Si está bien, `ai-delegate merge <id>`; si no sirve, `discard <id>`. Desconfía de `sin-cambios` y de resúmenes
   ilegibles: revisa el diff siempre.

## Diseño: la maestra decide, los agentes codifican

1. Decide el diseño (si {{user_name}} no da referencia, propón la dirección antes).
2. Escríbelo con `{{repo_path}}/templates/design-spec.md`, con valores concretos (hex, px/rem, fuentes,
   breakpoints, estados, textos) y guárdalo en `~/.local/share/ai-delegate/specs/<repo>/<nombre>.md`. Lo no
   especificado lo marcan como `TODO(diseño)`; lo resuelves tú actualizando la especificación.
3. `ai-delegate --kind design --design-spec <spec> --dir <repo> "implementa <pantalla>"`.
4. Revisa el diff contra la especificación y, si el proyecto corre, la vista en el navegador (móvil y escritorio);
   las diferencias van en `feedback` con valores exactos.

No delegues tareas de una o dos líneas, decisiones de diseño ni nada que necesite secretos.
`ai-delegate stats` muestra qué agente acierta más por tipo de tarea; `ai-delegate ui` abre la oficina.
