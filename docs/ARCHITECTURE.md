# Arquitectura

Este documento describe cómo está armado el pipeline: las etapas, los archivos que produce cada una, el modelo de datos, las decisiones que lo explican, cómo se reparte el trabajo entre un director y sus subagentes, qué se guarda en caché y dónde se puede extender. No contiene datos de ningún proyecto concreto.

## Visión general

```
 fuentes (solo lectura)                          proyecto (derivados)                           salidas
 ─────────────────────                          ─────────────────────                          ───────
 tarjeta del dron  ─┐                                                                           <name>-preview.mp4
 zip del álbum     ─┤  new → rutas → album → ingest ──► inv/media.json ─► prefilter ─► sheets    <name>-tv.mp4   (master)
 export del teléfono┤                │            │                              │      │       <name>-celu.mp4
 notas             ─┘                ▼            ▼                              ▼      ▼       <name>-chat.mp4
                                 route/*.json  sources.json                inv/prefilter.json  sheets/*.jpg
                                                                                      │
        director + subagentes ◄───── prompts rellenos (vlog prompt / triage-plan) ◄────┘
              │
              ▼  chronology → triage 1 → triage 2 → merge → sharpness → editor (EDL) → captions → música
              │
              ▼  edl-check ─► edl2guion ─► guion.json ─► render.py ─► build/ (caché) ─► salidas
```

Dos clases de etapas, con reglas distintas:

- **Etapas de CLI.** Deterministas, sin modelo de lenguaje, idempotentes: correrlas dos veces da lo mismo y lo ya hecho se saltea.
- **Etapas de juicio.** Las hace un modelo (o una persona) con una plantilla de prompt fija y un contrato de salida (un JSON con campos y valores acotados). El CLI imprime el prompt relleno y, después, **revalida** el archivo que quedó en disco; lo que no cierra vuelve a figurar como pendiente.

## Etapas y artefactos

La columna «Estado» es lo que mira `vlog status` para decir que la etapa está hecha.

| Etapa | Comando o plantilla | Entradas | Salidas | Estado |
|---|---|---|---|---|
| Proyecto | `vlog new` | respuestas del usuario | `project.yaml`, `DIRECTION.md`, carpetas base | `DIRECTION.md` sin líneas numeradas vacías |
| Ruta | `vlog rutas` (`route.py`, `adbui.py`) | exportación del teléfono | `route/<export>`, `route/route.json`, `route/route.gpx` | `route/route.json` |
| Álbum | `vlog album` | zip | carpeta de originales fuera del proyecto, raíz `album` en `sources.json` | raíz `album` registrada |
| Inventario | `vlog ingest` (`inventory.py`, `cluster.py`, `ingest.py`) | dron, álbum, ruta | `inv/inventory.json`, `inv/sessions.json`, `inv/media.json`, `inv/ingest_report.json`, `inv/geocache.json` | `inv/media.json` |
| Fuentes | `vlog sources build/check/relink/add` | `media.json`, ruta, notas, música | `sources.json` | — |
| Proxies | `vlog proxies` | videos del dron | `proxy/*.mp4` | `proxy/` no vacío |
| Cronología | `vlog prompt chronology` | `notes/` | `notes/chronology.json` | el archivo existe |
| Prefiltro | `vlog prefilter` | `media.json`, nitidez | `inv/prefilter.json` | el archivo existe |
| Hojas | `vlog sheets` | sobrevivientes del prefiltro | `sheets/*.jpg`, `sheets/index.json`, `sheets/manifest.json` | `sheets/manifest.json` |
| Triage 1 y 2 | `vlog triage-plan --pass 1|2` | hojas, brief, cronología | `triage/pass1/<día>.json`, `triage/pass2/<día>.json` | cada grupo valida contra el contrato |
| Fusión y nitidez | `vlog triage-merge`, `vlog sharpness` | pasadas 1 y 2 | `triage/merged.json`, `inv/sharpness.json`, `inv/variants.json` | ambos existen |
| Editor | `vlog prompt editor`, `vlog edl-check` | brief, triage, nitidez, cronología | `edl.json` | la EDL existe y `edl-check` no da errores |
| Captions | `vlog prompt captions` | EDL, triage, cronología | `captions.json` | el archivo existe |
| Música | director | `music/` | `music/credits.json` | el archivo existe |
| Guion | `edl2guion.py` | EDL, música, captions | `guion.json` | el archivo existe |
| Preview | `vlog preview` | guion | `<name>-preview.mp4`, `build/preview/` | el archivo existe |
| Aprobación | `vlog approve preview` | OK explícito del dueño | `approvals.json` | la clave `preview` existe |
| Final y salidas | `vlog final`, `vlog render` | guion (y `guion-reel.json`) | `<name>-tv.mp4`, `-celu`, `-chat`, `-reel` | existe el archivo del preset |

Otros directorios del proyecto: `build/` (caché de render y tiras de review), `notes/` (notas del viaje), `music/` (temas y `credits.json`), `triage/`, `sheets-p2/` (hojas de la segunda pasada) y `STATUS.md` (el estado, escrito por `vlog status`).

## Modelo de datos

Todo son archivos JSON o YAML en la carpeta del proyecto; no hay base de datos. La fuente de verdad del estado son los propios archivos.

### `inv/media.json`: un registro por foto o video

| Campo | Significado |
|---|---|
| `id` | `<fuente>.<nombre sin extensión>`, por ejemplo `drone.DJI_0001` o `phone_a.IMG_0001`. Es la clave que usan el triage, la EDL y el guion. |
| `path`, `root`, `relpath` | Ruta absoluta y la misma ruta expresada como raíz de `sources.json` más ruta relativa. Se resuelven por la raíz, así que mover un disco no rompe el proyecto. |
| `source` | `drone`, o el nombre que `ingest.owners` asignó al dispositivo, o `other`. |
| `kind` | `video` o `photo`. |
| `time_art`, `time_confidence` | Hora local del viaje con desfase (ISO 8601) y `high`/`medium`/`low` según de dónde salió. El nombre `time_art` es histórico («ART») y se conserva por compatibilidad: es la hora local configurada, no necesariamente la de Argentina. |
| `lat`, `lon`, `geo_source`, `geo_err_min` | Posición y de dónde sale: `gps` del archivo, `route_interp` o `route_visit` de la ruta, o `none`. |
| `day`, `place` | Fecha local y lugar por geocodificación inversa. |
| `w`, `h`, `orientation`, `dur`, `has_audio`, `audio_lufs` | Medidas del archivo. |
| `burst_group`, `keep_in_burst`, `exclude_reason` | Ráfaga a la que pertenece, si es la elegida, y el motivo de exclusión (`screenshot`, `duplicate_of:<id>`, `out_of_range`, …). |

### Otros contratos

- **`sources.json`**: `{version, roots: {id: {kind, path, origin, volume_uuid, volume_name, added_at}}, files: [{id, root, relpath, size, mtime, quick_hash}]}`. `quick_hash` es el SHA-1 del primer y el último MiB.
- **`route/route.json`**: `{points: [[iso, lat, lon]…], visits: [{start, end, type, place_id, lat, lon}…], activities: […]}`. `route_filled.json` agrega a cada punto su origen (`gps` o `filled`) y la evidencia de cada hueco rellenado.
- **Triage**: la pasada 1 produce `{code, reject, why, kind, sim}` por toma; la pasada 2, `{code, keep 0-3, kind, who, mood, desc, avoid, best, sim}`. Los códigos `P#`/`V#` los asigna `vlog sheets` y mapean a ids en `sheets/index.json`. `triage/merged.json` junta ambas; `best` se normaliza a una grilla de 6 cuadros.
- **EDL (`edl.json`)**: `{title, acts: [{name, music, shots: [{id, kind: video|photo|card|map, in, out | dur, audio, title, caption, why}]}], music_plan, exceptions, crossfade_s, total_s, …}`. Cada shot lleva `why`; una regla rota solo pasa `edl-check` si está declarada en `exceptions`.
- **Guion (`guion.json`)**: la lista de cortes ejecutable. Formato completo en [`GUION.md`](GUION.md).
- **`approvals.json`**: `{gate: fecha ISO}`. Las aprobaciones del dueño viven acá, no en la conversación.

## Decisiones de diseño

**ADR-1. Indexar, no copiar.** Los originales viven donde estaban y se leen en solo lectura; el proyecto guarda derivados y un manifiesto. Copiar duplica cientos de gigas y deja dos fuentes de verdad; indexar obliga a manejar discos ausentes, y por eso `sources.json` guarda el UUID del volumen, `vlog sources check` distingue «falta» de «cambió» y `vlog sources relink` re-apunta una raíz sin tocar archivos.

**ADR-2. El CLI decide lo mecánico; el modelo, el criterio.** Descartar borrosas, medir nitidez o resolver una fecha no necesita un modelo y no debe costar tokens ni variar entre corridas. Al modelo se le dan solo tareas de juicio visual o editorial, con plantillas fijas y salidas validables.

**ADR-3. El informe de un subagente es una afirmación, no una prueba.** Cada etapa de juicio tiene un chequeo que el subagente no escribió: `triage-plan` revalida el JSON, `edl-check` revalida la EDL, `zipinfo -1` cuenta los archivos del álbum. Es la defensa contra un «hecho» que no lo está.

**ADR-4. Sin estado oculto: el estado son los archivos.** `vlog status` mira qué existe y es válido. Por eso cada etapa es reanudable y un proyecto se puede retomar desde otra máquina o sesión leyendo `STATUS.md`.

**ADR-5. Caché por contenido, no por fecha.** Cada segmento de video se nombra con el hash de todo lo que lo determina (fuente con tamaño y mtime, recorte, estilo, resolución, fps, título, grading, captions). Editar un shot recodifica solo ese shot; insertar uno no invalida los siguientes. Detalle abajo.

**ADR-6. Minimapa y captions se superponen al ensamblar, no en los segmentos.** Así cambiarlos recodifica solo las partes que tocan, y los segmentos no dependen de ellos. Una racha de shots con minimapa mantiene el círculo en pantalla de corrido.

**ADR-7. Cada salida se renderiza nativa.** `celu`, `chat` y `reel` no son transcodificaciones del master: el minimapa, los captions y los reencuadres dependen del tamaño del cuadro y se calculan para él.

**ADR-8. Los textos salen de Pillow, no de `drawtext`.** Algunas compilaciones de ffmpeg no traen `drawtext` (o su FreeType). Dibujar los textos como PNG con Pillow da control tipográfico y evita esa dependencia.

**ADR-9. Triage en dos pasadas, con prefiltro.** El modelo barato descarta lo evidente y clasifica; el modelo mejor califica solo lo que sobrevive, sobre hojas más chicas. El prefiltro previo (sin modelo) reduce lo que llega a cualquiera de las dos.

**ADR-10. Configuración por capas en un solo formato.** Valores de fábrica en `config/defaults.yaml`, capa de usuario, `project.yaml`, y el guion para lo visual. Ninguna constante personal vive en el código. Un test verifica que cada clave esté documentada en [`CONFIG.md`](CONFIG.md).

**ADR-11. Servicios públicos con cortesía.** Nominatim, Overpass y OSRM se consultan con pausa, User-Agent identificable (`http.contact`) y caché en disco. El mapa regional usa datos locales de Natural Earth y las calles de pueblos se bajan una vez; no se usan mosaicos de OSM.

**ADR-12. Los encoders de hardware son una preferencia, no un requisito.** Los presets piden VideoToolbox; si el ffmpeg no lo trae, el codec cae a `libx264`/`libx265`. `vlog doctor` informa cuál se usará.

## Topología de agentes

El flujo asume un **director** (la sesión principal de un asistente de IA, o una persona) y **subagentes** que reciben una tarea acotada.

| Rol | Modelo (`standard` / `low`) | Tarea | Entradas | Salida |
|---|---|---|---|---|
| Director | el de la sesión | Habla con el dueño, ordena las etapas, juzga, decide | `DIRECTION.md`, `STATUS.md` | decisiones, EDL final |
| Cronología | pequeño / pequeño | Extracción mecánica de las notas por fecha | `notes/` | `notes/chronology.json` |
| Triage 1 | pequeño / pequeño | Descartes evidentes y tipo de toma | hojas de un día | `triage/pass1/<día>.json` |
| Triage 2 | mediano / mediano | Califica lo que sobrevivió | hojas, brief, contexto del día | `triage/pass2/<día>.json` |
| Editor | grande, 2 rondas / mediano, 1 | Escribe la EDL sin mirar imágenes | triage, nitidez, cronología, brief | `edl.json` |
| Captions | mediano / mediano (solo lugar) | Lugar y dato de cada toma | EDL, triage, cronología | `captions.json` |
| Reel | mediano / opcional | Corte vertical a partir de la EDL aprobada | EDL, brief | `guion-reel.json` |
| Código e investigación | mediano | Cambiar scripts, investigar un formato | — | cambios revisados |

Reglas que no se negocian:

1. Solo el director habla con el dueño y decide; ningún subagente recibe herramientas de envío.
2. Un subagente por grupo (por ejemplo, por día), con la plantilla de `docs/prompts/`. Los grupos de una pasada no comparten archivos y pueden correr en paralelo.
3. Cada informe se verifica con un chequeo independiente (ADR-3).
4. Ningún mensaje a una persona sale sin el OK del dueño para ese mensaje.
5. El modo de costo es una decisión del dueño, no del director: si falta cuota, se corta en el límite de una etapa y se retoma.

El cliente de modelos es intercambiable: el CLI solo imprime prompts y valida archivos, así que cualquier asistente que pueda leer imágenes y escribir JSON sirve. Roles y regla de auditoría completos: [`ROLES.md`](ROLES.md); secuencia y verificaciones: [`DIRECTOR.md`](DIRECTOR.md).

## Caché

| Qué | Dónde | Clave |
|---|---|---|
| Segmento de video, foto o tarjeta | `build/<modo>/<etiqueta>-<hash>.mp4` | Hash del spec del shot: revisión, resolución, fps, tipo, cuadros, codec, bitrate, claves de estilo, título, firma de la fuente (ruta, tamaño, mtime), recorte, velocidad, ajuste, grading y captions. |
| Parte ensamblada | `build/<modo>/part-<modo>-<hash>.mp4` | Grafo de filtros, firmas de los minimapas, shots incluidos, total de cuadros, preset, fundidos y revisiones. |
| Audio | `build/<modo>/audio-<hash>.m4a` | Grafo de filtros, entradas y sus firmas, bitrate y duración. |
| Música normalizada | `build/<modo>/music-<hash>.wav` | Firma del archivo y objetivos de sonoridad. |
| Pulsos de un tema | `build/<modo>/beats-<hash>.json` | Firma del wav normalizado. |
| Minimapa | `build/<modo>/minimap-<hash>.png` (+ `.json` con el desplazamiento) | Revisión, tamaño de cuadro, formato, configuración del minimapa que difiere de la de fábrica, posición, hora, lugar y firma de la ruta. |
| Medición de color por shot | `build/gprobe/<hash>.json` | Revisión, id, ruta, recorte y tipo. |
| Nitidez | `inv/sharpness_cache.json` | Id del medio. |
| Sonoridad, pHash, geocodificación | `inv/ingest_cache.json`, `inv/geocache.json` | Ruta, tamaño y mtime; celda geográfica. |
| Respuestas de OSRM | `<vendor_dir>/osrm-cache/<sha1>.json` | Coordenadas y parámetros de la consulta. |

Los segmentos, las partes, el audio, la música normalizada, el manifiesto de fuentes y los proxies se escriben primero a un archivo `.part` y se renombran al terminar, de modo que una interrupción no deja un archivo a medias que parezca válido. Cada segmento se verifica contra el conteo de cuadros esperado. `vlog clean` clasifica los derivados regenerables (`segcache`, `proxies`, `sheets`, `review`, `previews`) y nunca toca fuentes ni los videos listados en `outputs`.

## Configuración

`pipeline/config.py` resuelve las capas y expone `config.get("a.b.c")`, `config.section(nombre)` y `config.font()`. Los módulos leen sus valores en el momento de usarlos, de modo que la configuración activa (la del proyecto en curso) se aplica sin pasar diccionarios de mano en mano. `Guion` activa la del proyecto al crearse; los scripts sueltos reciben `--project`.

## Puntos de extensión

- **Un modo de costo nuevo**: agregar un perfil en `costmode.profiles` (modelos por rol, hojas, rondas, música, reel, tope por ventana) y su fila en `workflow.stage_tokens`.
- **Un preset de salida nuevo**: una entrada en `presets` con su resolución y codec, y su formato en `FORMAT_OF` (`pipeline/guion.py`) si necesita minimapa y captions propios (`minimap.format_defaults`, `caption.format_defaults`).
- **Una fuente o un dispositivo nuevo**: una línea en `ingest.owners` (`regex=fuente`). Una cámara con telemetría propia requiere un lector como el de SRT de DJI en `inventory.py` y `grade.py`.
- **Un perfil de color nuevo**: una entrada en `grade.profiles` con su curva y vibrance; el guion lo pide con `"grade": "<perfil>"`.
- **Una plantilla de prompt nueva**: un archivo en `docs/prompts/` con una línea `=== PROMPT ===` y los parámetros `{{...}}` que arma `pipeline/prompts.py`.
- **Otro idioma**: traducir las plantillas de `docs/prompts/` y ajustar `triage.*`, `locale.*`, `credits.*` y `edit.credits_act`.
- **Otro origen de la ruta**: cualquier cosa que produzca `route/route.json` con el formato de arriba reemplaza a `route.py`.
- **Otro servicio de geocodificación o ruteo**: `http.nominatim_url` y `http.osrm_url`.

## Pruebas

`tests/` usa `unittest`, carpetas temporales y datos inventados. Cubre configuración, CLI, triage, prefiltro, hojas, EDL, guion, overlays, flujo de estado y un render de punta a punta sobre un clip sintético generado con ffmpeg. Se corre con `venv/bin/python -I -m unittest discover -s tests`.
