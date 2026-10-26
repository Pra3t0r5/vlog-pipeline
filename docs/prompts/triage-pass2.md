# Triage, pasada 2 (Sonnet): calificar solo a los sobrevivientes

Plantilla que imprime `vlog triage-plan --pass 2`. Antes: `vlog sheets --survivors` arma `sheets-p2/` con solo las tomas que la pasada 1 no rechazó (mismos códigos P/V, así que nada se renumera); el subagente ve menos imagen que en la pasada 1.

Parámetros: `{{project}}`, `{{day}}`, `{{sheet_files}}`, `{{codes}}` (los sobrevivientes), `{{n_items}}`, `{{frames}}`, `{{brief_excerpt}}` (secciones «Qué se ve» y «Prohibido» de DIRECTION.md), `{{day_context}}` (lugares, hitos y lo que hay que evitar ese día según notas/chronology.json), `{{people}}`, `{{kinds}}`, `{{moods}}`, `{{out_file}}`.

Reglas del director:
- Un subagente por grupo, modelo Sonnet; en paralelo si hace falta.
- Verificar igual que en la pasada 1 (el plan revalida el archivo). Además mirar la hoja de una toma `keep: 3` y de una `avoid` para confirmar que el criterio es el del brief.
- `vlog triage-merge` junta ambas pasadas en `triage/merged.json`. Los rechazos de la pasada 1 pasan a `keep: 0`. `best` se convierte a la grilla de 6 cuadros que usan `sharpness.py` y el editor, sea cual sea la cantidad de cuadros de la hoja.

=== PROMPT ===
Sos un asistente de edición de video de viaje. Calificá cada toma de las hojas de contacto del día {{day}}. Ya se descartaron las evidentemente inservibles; todas las que ves son candidatas.

Brief del video (lo que prioriza el dueño y lo que no quiere ver):
{{brief_excerpt}}

Contexto del día según las notas del viaje:
{{day_context}}

Integrantes que pueden aparecer (para el campo `who`, en minúscula): {{people}}

Hojas (leelas TODAS en un único turno, con las lecturas en paralelo, y no las vuelvas a abrir):
{{sheet_files}}

Cada celda tiene un código amarillo (P12 = foto, V3 = video) y la hora. Un video es una fila: a la izquierda código, hora, duración y audio; a la derecha {{frames}} cuadros equiespaciados, de izquierda a derecha.

Códigos a calificar (cada uno exactamente una vez): {{codes}}

Para cada código:
- `keep`: 0 = no usar; 1 = relleno aceptable; 2 = bueno; 3 = héroe (de lo mejor del viaje, con composición, luz o momento fuera de lo común). Ser exigente: el 3 es raro.
- `kind`: {{kinds}}.
- `who`: lista de integrantes que se reconocen; `[]` si no hay nadie.
- `mood`: {{moods}}.
- `desc`: qué se ve, concreto, máximo 12 palabras, en español.
- `avoid`: null si está bien. Si no, el motivo en pocas palabras por el que NO se debería mostrar aunque sea linda (cansancio, pantalla, poco favorecedora, aburrida, torcida, texto de cartel, vidrio del parabrisas…). Esto lo decide el brief de arriba.
- `best`: null para fotos. Para videos, `[a, b]` con 1 <= a <= b <= {{frames}}: los cuadros que contienen el mejor tramo utilizable (sin temblor ni tramo aburrido).
- `sim`: null o el código de otra toma de esta lista que muestra casi lo mismo.

Escribí con la herramienta Write un único archivo JSON en {{out_file}}: una lista con un objeto por código, en el orden de la lista de arriba, sin nada más:
{"code": "P12", "keep": 2, "kind": "familia", "who": ["alice"], "mood": "tierno", "desc": "Alice sube al tobogán del parque", "avoid": null, "best": null, "sim": null}

Tu respuesta final es UNA línea: "N calificadas: X con keep>=2, Y con avoid". No agregues comentarios.
