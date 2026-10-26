# Roles: director y subagentes

## Director (sesión principal)

Es el único que habla con el dueño del video y el único que decide. Lee el brief (`DIRECTION.md`), ordena las etapas del CLI, hace las preguntas de intake, juzga el resultado y lanza subagentes con tareas acotadas. Es dueño de la lista de cortes final y de cualquier comunicación hacia afuera: ningún mensaje a una persona sale sin el OK del dueño para ese mensaje.

## Subagentes

| Modelo | Para qué | Ejemplos |
|---|---|---|
| Haiku | Extracción mecánica, sin juicio | Cronología a partir de las notas por fecha; triage pasada 1 (descartes obvios y tipo); listar archivos de un documento; normalizar fechas. |
| Sonnet | Código, investigación y triage | Cambiar o depurar scripts del pipeline; investigar un formato de exportación; triage pasada 2 (puntaje por toma, solo de lo que pasó la pasada 1); captions; el reel. |
| Opus (esfuerzo alto) | Decisión de edición | La lista de cortes (EDL): qué toma va, cuánto dura, en qué orden, con qué música, respetando el brief y las reglas de fuentes. En `cost_mode: low` no se usa: el editor es Sonnet con una sola ronda. |

Qué modelo corre cada paso en cada modo, con las plantillas de prompt y el orden exacto: `docs/DIRECTOR.md`.

## Regla de auditoría

El informe de un subagente es una afirmación, no una prueba. Antes de actuar sobre cualquier cosa que reporte, el director la verifica con un chequeo independiente que el subagente no escribió:

- "Corrieron los tests": correrlos de nuevo.
- "Extraje N archivos": contar con `zipinfo -1` o `ls`.
- "No toqué X": comparar antes y después (`git status`, `git diff`, hash o `ls -l`).
- "Esta toma es buena": mirar el contacto o el frame.
- "La fecha es esta": cruzar con el GPS del recurso, después Rutas, por último las notas.
- "El triage quedó completo": `vlog triage-plan --pass 1|2` revalida cada archivo y lista como pendiente lo que no cierra.
- "La EDL cumple el brief": `vlog edl-check`.

Los subagentes no editan archivos que otro agente tiene abiertos, no escriben fuera de su alcance y, si tienen herramientas de envío, heredan la regla de que no mandan nada a nadie.
