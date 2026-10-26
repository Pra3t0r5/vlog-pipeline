# Captions (Sonnet): lugar y dato por toma

Produce `captions.json`: `{id: {place, line, confidence, sources}}` para las tomas con `keep >= 2`. Se imprime rellena con `vlog prompt captions`. Alcance según el modo de costo: standard investiga en la web un dato interesante y verificado para cada lugar (`line`), con su URL; low solo completa `place` y deja `line` en `null`, sin investigación.

Parámetros: `{{project}}`, `{{media}}`, `{{index}}`, `{{triage}}`, `{{chronology}}`, `{{captions}}`, `{{captions_scope}}`.

Reglas del director:
- Se lanza después de que la EDL existe: alcanza con las tomas de la EDL más las `keep >= 2`.
- Verificar: cada `line` tiene al menos una URL que el director abre y donde encuentra el dato; una `line` sin fuente, con una fuente que no dice eso o con `confidence: "low"` se anula (`null`). `vlog edl-check` avisa si un caption usa un dato de confianza baja.
- Una `line` no es un rótulo de lo que se ve: es un dato que el espectador no sabía. Si no hay uno verificable, queda `null` (mejor sin descripción que con una inventada).

=== PROMPT ===
Asigná a cada toma su lugar y, si corresponde, un dato breve para el texto que aparece abajo a la izquierda del video.

Entradas dentro de {{project}}: inventario {{media}} (lat/lon, `place` geocodificado, hora), códigos {{index}}, triage {{triage}} (`desc`, `keep`) y cronología {{chronology}} (lugares y hitos por día).

Alcance: {{captions_scope}}

Reglas:
- `place`: el lugar como lo diría una persona del viaje, de 1 a 4 palabras («Iglesia del pueblo», «Mirador del valle»). Primero manda el GPS de la toma, después la cronología del día. Tomas contiguas del mismo lugar llevan el mismo nombre escrito igual: el render las junta en una racha, deja el lugar fijo en pantalla y cambia solo la descripción.
- `line`: UN dato interesante y verificado de geología, flora, fauna, historia o cultura del lugar o de lo que se ve, de máximo 12 palabras, o null. Nada de adjetivos ni opiniones, ni cifras que no estén en la fuente. Priorizá las tomas largas de dron (5 s o más), que son las que dan tiempo de leerlo; en una toma corta, null. Cada descripción necesita 1,5 s + 0,3 s por palabra en pantalla.
- Verificación obligatoria: buscá en la web (fuentes abiertas: un parque nacional, un museo, un servicio geológico, una enciclopedia), abrí la página y confirmá que dice lo que escribís. Nunca inventes ni completes de memoria; si no lo confirmás, `line` es null.
- `confidence`: high si GPS y cronología coinciden, medium si solo una fuente, low si es una suposición.
- `sources`: lista de `{"title", "url"}` solo de páginas que abriste y que respaldan la `line`; no puede estar vacía si `line` no es null.
- No repitas en la `line` el nombre del `place` ni la fecha: ya están en pantalla (en el caption y en la etiqueta del minimapa).
- Nunca rotules momentos del `avoid` de la cronología.

Escribí con la herramienta Write un único JSON en {{captions}}: `{"<id de media>": {"place": "...", "line": "dato de hasta 12 palabras", "confidence": "high", "sources": [{"title": "...", "url": "https://..."}]}}` (con `line` null, `sources` vacía). Tu respuesta final es UNA línea: "N tomas, M con dato".
