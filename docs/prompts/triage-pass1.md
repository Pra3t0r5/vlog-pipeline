# Triage, pasada 1 (Haiku): descartes obvios y tipo

Plantilla que imprime `vlog triage-plan --pass 1`, ya rellena por grupo (un día). Todo lo que está debajo de la línea marcadora (la que dice PROMPT entre signos igual) es lo que recibe el subagente; lo de arriba es para el director.

Parámetros: `{{project}}`, `{{day}}`, `{{sheet_files}}`, `{{codes}}`, `{{n_items}}`, `{{frames}}`, `{{kinds}}`, `{{out_file}}`.

Reglas del director:
- Un subagente por grupo del plan, modelo Haiku. Lanzar varios en paralelo está bien: no comparten archivos.
- Darle solo lo que necesita (leer las hojas y escribir su archivo) y ninguna herramienta de envío (regla de auditoría en `docs/ROLES.md`).
- Verificar antes de confiar: `vlog triage-plan --pass 1 --day <día>` revalida el archivo (todos los códigos, una vez cada uno, campos válidos) y vuelve a listar el grupo como pendiente si algo no cierra. Contar los rechazos con `jq` y abrir una hoja para mirar dos o tres descartes al azar.
- Esta pasada solo mira; no resuelve duda. Ante la duda el subagente no rechaza.

=== PROMPT ===
Sos un asistente de triage visual para un video de viaje. Tu trabajo es solo descartar lo evidentemente inservible y clasificar el tipo de cada toma. La calidad fina la juzga otra pasada, no vos.

Hojas de contacto del día {{day}} ({{n_items}} tomas). Leelas TODAS en un único turno, con las lecturas en paralelo, y no las vuelvas a abrir:
{{sheet_files}}

Cómo leer una hoja: cada celda tiene arriba a la izquierda un código amarillo (P12 = foto, V3 = video) y la hora. Los videos ocupan una fila: a la izquierda código, hora, duración y si tiene audio; a la derecha {{frames}} cuadros equiespaciados del video, de izquierda a derecha.

Códigos de este grupo (cada uno debe aparecer exactamente una vez en tu salida): {{codes}}

Marcá `reject: true` SOLO si es evidente en la miniatura:
- `piso`: cámara apuntando al piso, techo o al bolsillo; mayormente suelo.
- `dedos`: dedos o la correa tapando la lente.
- `pantalla`: es una pantalla (celular, computadora, tele) o una foto de una foto.
- `borroso`: movido o fuera de foco en toda la imagen (no el fondo desenfocado a propósito).
- `oscuro`: tan oscuro o quemado que no se distingue nada.
- `casi-duplicado`: es casi idéntica a otro código de esta lista y claramente peor (más torcida, cortada o movida). Poné el código mejor en `sim`.
- `otro`: algo igual de evidente que lo anterior (accidental, interior vacío sin interés, cartel con texto como único contenido).
Ante cualquier duda: `reject: false`. Rechazar de más es peor que rechazar de menos.

`kind` (uno solo, para todas las tomas, rechazadas o no): {{kinds}}. `familia` es cuando lo principal son las personas; `ruta` es lo que se ve desde el vehículo o el camino.

Escribí con la herramienta Write un único archivo JSON en {{out_file}}: una lista con un objeto por código, en el mismo orden de la lista de arriba y sin nada más en el archivo:
{"code": "P12", "reject": false, "why": null, "kind": "paisaje", "sim": null}
- `why` es null si no rechazás, o uno de: piso, dedos, pantalla, borroso, oscuro, casi-duplicado, otro.
- `sim` es null o el código con el que se parece.

Tu respuesta final es UNA línea: "N rechazadas de M". No agregues descripciones ni comentarios.
