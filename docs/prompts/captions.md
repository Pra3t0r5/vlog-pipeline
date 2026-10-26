# Captions (Sonnet): lugar y dato por toma

Produce `captions.json`: `{id: {place, line, confidence, sources}}` para las tomas con `keep >= 2`. Se imprime rellena con `vlog prompt captions`. Alcance según el modo de costo: standard puede investigar el dato de cada lugar (`line`) con fuentes; low solo completa `place` y deja `line` en `null`, sin investigación.

Parámetros: `{{project}}`, `{{media}}`, `{{index}}`, `{{triage}}`, `{{chronology}}`, `{{out_file}}`, `{{captions_scope}}`.

Reglas del director:
- Se lanza después de que la EDL existe: alcanza con las tomas de la EDL más las `keep >= 2`.
- Verificar: cada `line` tiene al menos una fuente que el director abre; una `line` sin fuente o con `confidence: "low"` se anula (`null`). `vlog edl-check` avisa si un caption usa un dato de confianza baja.

=== PROMPT ===
Asigná a cada toma su lugar y, si corresponde, un dato breve para el texto que aparece abajo a la izquierda del video.

Entradas dentro de {{project}}: inventario {{media}} (lat/lon, `place` geocodificado, hora), códigos {{index}}, triage {{triage}} (`desc`, `keep`) y cronología {{chronology}} (lugares y hitos por día).

Alcance: {{captions_scope}}

Reglas:
- `place`: el lugar como lo diría una persona del viaje, de 1 a 4 palabras («Iglesia del pueblo», «Mirador del valle»). Primero manda el GPS de la toma, después la cronología del día. Tomas contiguas del mismo lugar llevan el mismo nombre escrito igual.
- `line`: un dato verificable y corto (máximo 8 palabras), o null. Nada de adjetivos ni opiniones. Un dato sin fuente va en null.
- `confidence`: high si GPS y cronología coinciden, medium si solo una fuente, low si es una suposición.
- `sources`: lista de `{"title", "url"}` solo de páginas que abriste; vacía si no hay.
- Nunca rotules momentos del `avoid` de la cronología.

Escribí con la herramienta Write un único JSON en {{out_file}}: `{"<id de media>": {"place": "...", "line": null, "confidence": "high", "sources": []}}`. Tu respuesta final es UNA línea: "N tomas, M con dato".
