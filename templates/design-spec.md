# Especificación de diseño: <pantalla o componente>

> La escribe la sesión principal (Claude). Codex o agy la implementan **al pie de la letra**.
> Todo valor debe ser concreto (hex, px/rem, nombre de clase o token); nada de "moderno" o "limpio".

## 1. Alcance
- Qué se construye: <página / sección / componente>
- Archivos a crear o editar: <rutas>
- Qué NO se toca: <archivos y estilos existentes que deben quedar igual>

## 2. Tokens
| Token | Valor | Uso |
|---|---|---|
| `--color-bg` | `#0F0F10` | fondo de página |
| `--color-text` | `#F4F4F5` | texto principal |
| `--color-accent` | `#E4572E` | botones primarios, enlaces |
| fuente títulos | `"Clash Display", sans-serif` 600 | h1–h3 |
| fuente texto | `"Inter", sans-serif` 400/500 | párrafos, UI |
| espaciado base | `8px` (escala 4/8/12/16/24/32/48/64) | |
| radio | `12px` tarjetas, `999px` botones | |
| sombra | `0 8px 24px rgb(0 0 0 / .25)` | tarjetas en hover |

Si el proyecto ya tiene tokens (Tailwind config, variables CSS), usa esos nombres: <ruta del archivo>.

## 3. Layout por breakpoint
- **Móvil (<640px)**: <columnas, orden, márgenes laterales 16px…>
- **Tablet (640–1023px)**: <…>
- **Escritorio (≥1024px)**: <grid, ancho máximo 1200px centrado…>

## 4. Componentes
Para cada uno: estructura, tamaños, tipografía y **estados** (normal, hover, focus-visible, active, disabled, carga, vacío, error).

### <Componente>
- Estructura: <elementos en orden>
- Medidas: <alto, padding, gap>
- Texto: <tamaño/peso/interlineado>
- Estados: <hover: …; focus-visible: anillo 2px `--color-accent` con offset 2px; …>

## 5. Movimiento
- <qué se anima, propiedad, duración, curva; ej.: tarjetas `transform: translateY(-4px)` 200ms ease-out>
- Respeta `prefers-reduced-motion: reduce` (sin animación).

## 6. Contenido
Textos exactos, alt de imágenes, rutas de imágenes y enlaces.

## 7. Accesibilidad
- Contraste mínimo AA; jerarquía de headings; foco visible; etiquetas en formularios.

## 8. Criterios de aceptación
- [ ] Coincide con los tokens y medidas de arriba en los 3 breakpoints
- [ ] Todos los estados implementados
- [ ] Sin estilos ni componentes no especificados
- [ ] Lo no especificado quedó marcado con `TODO(diseño)`

## Criterios verificables

Estos criterios reemplazan a los criterios de casillas cuando se pueden verificar automáticamente.

```acceptance
cmd: npm test
contains: src/components/Hero.tsx :: Bienvenido
not-contains: src/ :: console.log
exists: src/components/Hero.tsx
```
