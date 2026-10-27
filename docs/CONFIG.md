# Configuración: todas las claves

Toda la configuración vive en YAML y se resuelve por capas. De menor a mayor prioridad:

1. [`config/defaults.yaml`](../config/defaults.yaml): valores de fábrica. No se edita; se lee para saber qué existe.
2. Configuración de usuario: `~/.config/vlog-pipeline/config.yaml`, o el archivo que diga `$VLOG_CONFIG`. Sirve para lo que depende de la máquina (tipografía, carpeta de proyectos, contacto de las APIs).
3. `project.yaml` del proyecto: lo que cambia para ese video.
4. Solo para `style`, `minimap`, `caption` y `output`: el `guion.json` de cada salida (ver [`GUION.md`](GUION.md)).

Un archivo solo escribe lo que cambia. Los mapas se fusionan clave por clave (si pisás `minimap.opacity`, el resto de `minimap` sigue con su valor); las listas se reemplazan enteras. Un `null` explícito deja la clave en `null`.

```
vlog config                  # configuración fusionada del proyecto actual (o la de fábrica fuera de un proyecto)
vlog config minimap.opacity  # una sola clave
vlog config --defaults       # imprime config/defaults.yaml
```

Un ejemplo completo y comentado de `project.yaml`: [`examples/project.example.yaml`](../examples/project.example.yaml).

Las etiquetas de los pasos que muestra el CLI, los prompts de [`prompts/`](prompts/) y las categorías del triage están en español. Si querés otro idioma, editá las plantillas de `docs/prompts/` y las listas `triage.*`, `locale.*` y `credits.*`.

## Claves que solo existen en `project.yaml`

Identifican el proyecto; no tienen valor de fábrica.

| Clave | Qué es |
|---|---|
| `name` | Nombre del proyecto y prefijo de los archivos de salida (`<name>-preview.mp4`). |
| `title` | Título para los prompts; si falta, se usa `name`. |
| `theme`, `audience` | Tema y público; los escribe `vlog new` y los lee quien dirige el flujo. |
| `cost_mode` | `standard` o `low` (ver `costmode.*`). |
| `duration` | `{target_min, floor_min, ceil_min}`: duración objetivo, piso y techo en minutos. `edl-check` rechaza una EDL fuera del piso y el techo. |
| `output` | `{fps, final: {w, h}}`: velocidad de cuadros y resolución del master. Se fusiona con `output` de fábrica. |
| `sources` | `{drone, album_zip}`: carpeta de la tarjeta del dron y zip del álbum que se pasaron a `vlog new`. |
| `rutas` | `{from, to}`: fechas de la última exportación de ruta. Cuenta como rango de fechas del viaje si faltan `ingest.start_date/end_date`. |
| `trip` | `{from, to}` o `{start_date, end_date}`: otra forma de fijar el rango de fechas. |
| `guion` | Nombre del guion principal (por defecto `guion.json`). |
| `edl` | Nombre del archivo de la EDL (por defecto `edl.json`). |
| `inventory`, `media` | Rutas relativas de `inv/inventory.json` (dron) y `inv/media.json` (unificado). |
| `proxy_dir` | Carpeta de proxies (por defecto `proxy`). |
| `outputs` | Lista de salidas: `tv`, `celu`, `chat` o `{preset: reel, guion: guion-reel.json}`. |
| `people` | Nombres (en minúscula) que pueden aparecer en las tomas; alimenta el campo `who` del triage. Si falta, sale de los nombres de `ingest.owners`. |
| `source_bytes` | Tamaño de las fuentes al crear el proyecto (lo escribe `vlog new`). |

## Rutas, red y tipografía

| Clave | Defecto | Qué hace |
|---|---|---|
| `paths.root` | `null` | Carpeta que contiene los proyectos. `$VLOG_ROOT` la pisa; si ninguna está, `~/vlogs`. |
| `paths.vendor_dir` | `vendor` | Datos descargados (Natural Earth, calles OSM, caché OSRM). Relativa al repo. |
| `paths.naturalearth_dir` | `null` | Carpeta de los GeoJSON de Natural Earth; `null` es `<vendor_dir>/naturalearth`. |
| `paths.osm_dir` | `null` | Carpeta de las calles de pueblos (`vlog osm`); `null` es `<vendor_dir>/osm`. |
| `paths.osrm_cache_dir` | `null` | Caché de respuestas OSRM; `null` es `<vendor_dir>/osrm-cache`. |
| `paths.originals_dirname` | `originales` | Nombre de la carpeta hermana del proyecto donde `vlog album` descomprime el zip cuando no hay `storage.originals_dir`. |
| `timezone` | `null` | Desfase `+HH:MM` de la hora local del viaje. `ingest.tz` lo pisa; si ambos son `null` se usa el desfase actual del sistema (no tiene en cuenta un cambio de horario entre la fecha del viaje y hoy). |
| `http.contact` | `null` | Mail o URL que se agrega al User-Agent de Nominatim, Overpass y OSRM. Sus políticas piden identificarse: definilo. |
| `http.nominatim_url` | OSM público | Servicio de geocodificación inversa. Si lo cambiás por uno propio, ajustá `ingest.geocode_delay_s`. |
| `http.overpass_url` | overpass-api.de | Servicio de `vlog osm`. |
| `http.osrm_url` | demo de OSRM | Servicio de ruteo de `routefill.py`. El demo público no es para uso intensivo. |
| `fonts.main` | `null` | `.ttf` o `.ttc` para los textos del video. `null` usa la primera de `fonts.candidates` que exista. |
| `fonts.ui` | `null` | Tipografía de hojas de contacto y tiras de review; `null` usa `fonts.main`. |
| `fonts.candidates` | Futura, Helvetica, Arial, DejaVu | Lista de búsqueda cuando `fonts.main` es `null`. |
| `locale.months` | `ene…dic` | Meses abreviados que dibuja el minimapa. |
| `locale.months_full` | `enero…diciembre` | Meses completos de la etiqueta del minimapa. |
| `locale.date_format` | `{day} de {month}` | Formato de la fecha de la etiqueta (`{day}`, `{month}`, `{year}`). |

## Render

| Clave | Defecto | Qué hace |
|---|---|---|
| `output.fps` | `"30000/1001"` | Fracción o número (30, 29.97). Debe estar entre 1 y 120. |
| `render.hwaccel` | `auto` | `auto` usa `-hwaccel videotoolbox` si ffmpeg trae los encoders de VideoToolbox; `none` lo desactiva. |
| `render.nice` | `10` | Prioridad (`nice -n`) de los ffmpeg largos; `0` la desactiva. |
| `render.shots_per_part` | `default: 4, preview: 24, reel: 8` | Cuántos shots codifica cada ffmpeg de ensamble. Más shots usan más memoria. |
| `presets` | ver archivo | Un mapa por salida nativa (`preview`, `final`, `celu`, `chat`, `reel`) con `w`, `h`, `bitrate`, `seg_bitrate`, `codec`, `audio_bitrate` y, según el caso, `max_mb`, `vmax`, `max_s`. Un codec VideoToolbox cae a `libx264`/`libx265` si no existe. El `output.<preset>` del guion lo pisa. |

### Estilo (`style`)

| Clave | Defecto | Qué hace |
|---|---|---|
| `style.font` | `null` | Tipografía de títulos, tarjetas y captions; `null` usa `fonts.main`. |
| `style.xfade` | `0.6` | Duración del fundido cruzado, en segundos. |
| `style.transition` | `fade` | Transición por defecto de un shot (`fade` o `cut`). |
| `style.photo_dur` | `3.0` | Duración por defecto de una foto. |
| `style.card_dur` | `3.5` | Duración por defecto de una tarjeta. |
| `style.zoom_amt` | `0.08` | Zoom lento de una foto sin `focus`. |
| `style.focus_zoom` | `0.14` | Zoom de una foto con `focus`. |
| `style.pan_zoom` | `0.14` | Zoom del barrido `pan`. |
| `style.bg_sigma` | `6` | Desenfoque del fondo de los medios que no son 16:9. |
| `style.bg_dim` | `0.55` | Oscurecimiento de ese fondo. |
| `style.card_dim` | `0.4` | Oscurecimiento del fondo de una tarjeta con imagen. |
| `style.card_color` | `#1b1511` | Color de una tarjeta sin imagen. |
| `style.aspect_tol` | `0.02` | Tolerancia para considerar un medio como 16:9. |
| `style.fade_in` | `0.6` | Fundido de entrada del video. |
| `style.fade_out` | `1.0` | Fundido de salida del video. |
| `style.clip_lufs` | `-18.0` | Sonoridad objetivo del audio de un clip con `audio: keep`. |
| `style.clip_gain_max` | `15.0` | Ganancia máxima al normalizar un clip (dB). |
| `style.clip_fade` | `0.25` | Fundido de audio de un clip. |
| `style.music_lufs` | `-16.0` | Sonoridad integrada de la música. |
| `style.music_tp` | `-1.5` | Pico verdadero máximo de la música (dBTP). |
| `style.music_xfade` | `2.0` | Cruce entre dos temas contiguos. |
| `style.music_fade_in` | `1.5` | Fundido de entrada de la música. |
| `style.music_fade_out` | `3.0` | Fundido de salida final. |
| `style.duck_db` | `-8.0` | Cuánto baja la música bajo un clip con audio. |
| `style.duck_offset_db` | `1.9` | Calibración del umbral del compresor de ducking. |
| `style.snap_tolerance` | `0.35` | Margen (±35 %) con el que `snap_to_beats` puede estirar o acortar un shot. |

### Minimapa (`minimap`)

| Clave | Defecto | Qué hace |
|---|---|---|
| `minimap.enabled` | `false` | Enciende el minimapa. |
| `minimap.size` | `null` | Fracción del lado corto del cuadro; si se define, pisa `diameter` en todos los formatos. |
| `minimap.opacity` | `0.6` | Opacidad del círculo. |
| `minimap.position` | `top-right` | `top-right`, `top-left`, `bottom-right` o `bottom-left`. |
| `minimap.layout` | `corner` | `corner`: el minimapa en su esquina, con el lugar y la fecha debajo, y las captions abajo a la izquierda. `beside`: un solo bloque, el minimapa con el lugar, la fecha y la descripción a su costado, del lado que diga `position` (a la derecha del círculo en `*-left`, alineado a la derecha en `*-right`). |
| `minimap.beside_gap` | `0.12` | `beside`: separación entre el círculo y el texto, en fracciones del diámetro. |
| `minimap.beside_text_w` | `0.40` | `beside`: ancho máximo del texto (lugar y descripción), en fracción del ancho del cuadro. |
| `minimap.label_scale` | `1.0` | Multiplica el tamaño de la etiqueta respecto de la escala tipográfica compartida con los captions (`caption.format_defaults`). El tamaño es fijo por formato: no se ajusta al largo del texto. |
| `minimap.suppress_redundant_place` | `true` | Si un título o una tarjeta del acto ya nombra el lugar, la etiqueta muestra solo la fecha. |
| `minimap.radius_km` | `120.0` | Radio del mapa regional. |
| `minimap.urban_km` | `1.2` | Radio del mapa de calles cuando hay datos OSM del pueblo. |
| `minimap.break_on_act` | `true` | Un cambio de acto corta la racha de minimapa continuo. |
| `minimap.fade_s` | `0.4` | Fundido de entrada y salida de una racha. |
| `minimap.lat_min` | `null` | Descarta los puntos de la ruta con latitud menor que este valor (útil si el recorrido incluye un tramo lejano, como el viaje de ida). `null` no filtra. |
| `minimap.simplify_km` | `1.5` | Tolerancia con la que se simplifica la ruta dibujada. |
| `minimap.theme` | `dark` | Paleta de `minimap.themes`. |
| `minimap.accent` | `[255, 138, 38]` | Color del punto actual y del tramo recorrido. |
| `minimap.labels_max` | `3` | Referencias que se rotulan en el mapa regional. |
| `minimap.places.natural_earth` | `{}` | `{nombre en Natural Earth: etiqueta}`: ciudades de referencia que se suman al mapa regional. |
| `minimap.places.always` | `[]` | Etiquetas que se dibujan siempre que entren en el cuadro, sin contar contra `labels_max`. |
| `minimap.geometry` | ver archivo | Constantes de dibujo: `ref_diameter`, `line_floor`, `dot_min`, `label_min_px_map`, `label_min_diameter`, `supersample`. |
| `minimap.themes` | `dark`, `light` | Colores RGBA de cada paleta (`base`, `road`, `prov`, `pend`). |
| `minimap.format_defaults` | ver archivo | Por formato (`tv`, `celu`, `chat`, `reel`): `diameter` (fracción del lado corto: tv 0,14), `label_size` (multiplicador de la escala compartida), `label_max_w` (ancho máximo de la etiqueta, fracción del ancho; el lugar se parte en 2 renglones en límites de palabra, nunca se achica) y `margin_x`/`margin_y` (`null` hereda los de `caption.format_defaults`: mismo margen seguro). |
| `minimap.presets` | `{}` | Lo que cambia tu proyecto sobre `format_defaults`, por formato. |

### Captions (`caption`)

| Clave | Defecto | Qué hace |
|---|---|---|
| `caption.min_shot_s` | `2.5` | Una racha de captions más corta (en segundos) no lleva texto. |
| `caption.fade_in_after` | `0.5` | Espera tras verse entero el shot antes de entrar. |
| `caption.fade_s` | `0.5` | Duración del fundido del lugar al empezar y terminar la racha, y del fundido cruzado entre descripciones. No hay fundido en cada corte. |
| `caption.suppress_redundant_place` | `true` | No dibuja el lugar si ya lo nombra un título, una tarjeta del acto o la etiqueta del minimapa del mismo shot. |
| `caption.min_line_s` | `1.5` | Permanencia mínima de una descripción: `min_line_s` + `line_s_per_word` por palabra. |
| `caption.line_s_per_word` | `0.3` | Segundos extra por palabra de la descripción. |
| `caption.on_short_shot` | `persist` | `persist`: la descripción de un shot demasiado corto sigue en el shot siguiente de la racha; `skip`: se omite. En ambos casos los shots cortos de una racha muestran solo el lugar. |
| `caption.format_defaults` | ver archivo | Escala tipográfica fija por formato, compartida con la etiqueta del minimapa. `place` (lugar, y su renglón en la etiqueta) y `line` (descripción, y la fecha) son fracciones del lado corto (tv: 0,0252 y 0,021, es decir 54 y 45 px en 4K); `min_place_px`/`min_line_px` son pisos para cuadros chicos; `max_w` es el ancho máximo (fracción del ancho); `margin_x`/`margin_y` definen el área segura común. |
| `caption.presets` | `{}` | Lo que cambia tu proyecto sobre `format_defaults`, por formato. |

### Ritmo (`pacing`)

`pacing: relaxed` (o `standard`) en `project.yaml` equivale a `pacing.mode`. El modo `relaxed`, pensado para espectadores mayores frente a una TV, multiplica por 1,3 las duraciones objetivo por plano y baja en la misma proporción el tope de cortes por minuto. Lo leen `vlog prompt editor` y `vlog edl-check`; el render no cambia las duraciones que ya trae el guion.

| Clave | Defecto | Qué hace |
|---|---|---|
| `pacing.mode` | `relaxed` | `relaxed` o `standard`. |
| `pacing.multiplier` | `{relaxed: 1.3, standard: 1.0}` | Factor sobre los rangos de `pacing.targets` según el modo. |
| `pacing.targets` | ver archivo | `[mínimo, máximo]` en segundos en modo standard, por tipo de plano: `drone` 4 a 6, `photo` 2,5 a 4, `hero` 4 a 4,5, `phone` 3 a 8. En `relaxed` resultan drone 5 a 8, photo 3,5 a 5, hero 5 a 6, phone 4 a 10,5 (redondeados a 0,5 s). |
| `pacing.min_shot_s` | `null` | Si se define, es el plano más corto que tolera `edl-check` para todos los tipos y pisa el mínimo de cada rango. |
| `pacing.max_cuts_per_min` | `18` | Cortes por minuto en standard; el tope efectivo es este valor dividido por el multiplicador (13,8 en relaxed). |

### Color y nitidez (`grade`)

| Clave | Defecto | Qué hace |
|---|---|---|
| `grade.sunset` | `"19:15"` | Hora local desde la que una toma oscura se considera de noche cuando no hay telemetría del dron. |
| `grade.sample_w` | `1024` | Lado mayor de los cuadros con los que se mide cada shot. |
| `grade.night_iso` | `250` | ISO mediano del SRT del dron desde el que la toma es de noche. |
| `grade.night_shutter_denominator` | `200` | Un obturador más lento que `1/200` s también marca noche. |
| `grade.night_luma` | `95.0` | Luma media por debajo de la cual una toma tardía es de noche. |
| `grade.soft_lap` | `drone: 800, phone: 1000` | Varianza del laplaciano bajo la cual una toma con zoom se considera blanda. |
| `grade.zoom_frac` | `0.25` | Fracción de cuadros con zoom digital del dron que activa la detección. |
| `grade.sharp_strength` | `0.4` | Fuerza del filtro `cas`. |
| `grade.warm_rb` | `[0.9, 1.04]` | Rango de relación R/B donde el tono medio se considera neutro y recibe calor. |
| `grade.warm_amount` | `0.02` | Cuánto calor se agrega. |
| `grade.vibrance_taper` | `[0.40, 0.55]` | Saturación media del original (0 a 1) entre la que la vibrance de los perfiles de día se reduce en proporción: completa hasta el primer valor, nula desde el segundo. Evita sobresaturar tomas que el teléfono ya realzó. |
| `grade.srt_fps` | `"30000/1001"` | Velocidad con la que se indexan los cuadros del SRT del dron. |
| `grade.probe_fractions` | `[0.15, 0.5, 0.85]` | Posiciones del shot donde se miden cuadros. |
| `grade.denoise` | tres tramos | `[[iso_máximo, "hqdn3d"], …]`: reducción de ruido según el ISO. |
| `grade.profiles` | `night`, `day_drone`, `day_phone` | Curva, vibrance, orden y si admite calor de cada perfil. |

## Inventario y prefiltro

| Clave | Defecto | Qué hace |
|---|---|---|
| `ingest.tz` | `null` | Zona horaria `+HH:MM` de las fotos sin offset y de los nombres de archivo. |
| `ingest.start_date`, `ingest.end_date` | `""` | Rango del viaje (`AAAA-MM-DD`). Lo de afuera se excluye como `out_of_range`. |
| `ingest.owners` | `[]` | Lista de `regex=fuente`. El regex se prueba contra el modelo EXIF del dispositivo o, si empieza con `^`, contra el nombre del archivo. La fuente da el prefijo del id (`phone_a.IMG_001`). |
| `ingest.clock_offsets` | `[]` | Lista de `fuente=segundos` para corregir un reloj atrasado o adelantado. |
| `ingest.duplicate_seconds` | `120` | Dos fotos casi idénticas dentro de esta ventana son duplicados. |
| `ingest.duplicate_phash_same_source` | `2` | Distancia pHash máxima para duplicar dentro de una misma fuente. |
| `ingest.duplicate_phash_cross_source` | `6` | Ídem entre fuentes distintas. |
| `ingest.burst_seconds` | `10` | Ventana de una ráfaga. |
| `ingest.burst_phash` | `10` | Distancia pHash máxima dentro de una ráfaga. |
| `ingest.route_gap_min` | `20` | Hueco máximo (minutos) entre dos puntos de la ruta para interpolar un lugar. |
| `ingest.visit_conflict_m` | `500` | Distancia desde la que una visita de la ruta contradice la posición interpolada. |
| `ingest.geocode` | `true` | `false` evita toda consulta a Nominatim (no se manda ninguna coordenada). |
| `ingest.geocode_language` | `es` | Idioma de los nombres de lugar. |
| `ingest.geocode_delay_s` | `1.1` | Pausa entre consultas; la política de Nominatim pide como máximo una por segundo. |
| `ingest.geocode_cell_deg` | `[0.009, 0.01]` | Tamaño de la celda (grados) en la que se reutiliza una respuesta. |
| `ingest.exclude_name_patterns` | tres regex | `{motivo: regex}` sobre el nombre de archivo: `screenshot`, `generated_highlight`, `drone_app_cache`. |
| `ingest.cluster_gap_s` | `2700` | Hueco que corta una sesión del dron. |
| `ingest.cluster_km` | `3` | Distancia que corta una sesión del dron. |
| `proxies.drone` | `640x360, 1500k` | Proxies de los videos del dron (`vlog proxies`). |
| `proxies.phone` | `640x360, 1200k, audio 64k` | Proxies de los videos del teléfono (`vlog ingest`) y cuántos ffmpeg a la vez (`max_parallel_ffmpeg`). |
| `storage.originals_dir` | `null` | Carpeta de originales fuera del proyecto. |
| `storage.album_dir` | `null` | Carpeta del álbum ya extraída (la escribe `vlog album`). |
| `storage.album_name` | `null` | Nombre de la subcarpeta del álbum; si falta, sale del zip. |
| `prefilter.blurry_z` | `-1.5` | Puntaje de nitidez bajo el cual el prefiltro descarta como borrosa. |
| `prefilter.variant_phash` | `14` | Distancia pHash máxima entre variantes de una misma escena. |
| `prefilter.variant_seconds` | `90` | Ventana en la que dos fotos pueden ser variantes. |
| `prefilter.screenshot_pattern` | regex | Nombres de archivo que se tratan como captura de pantalla. |
| `sharpness.long_side` | `1024` | Lado mayor con el que se mide la nitidez. |
| `sharpness.blurry_z` | `-1.0` | Umbral con el que `sharpness.json` marca `blurry` (lo usa `edl-check`). |
| `sharpness.motion_ratio` | `0.25` | Relación direccional bajo la cual hay desenfoque de movimiento. |
| `sharpness.variant_seconds` | `90` | Ventana de variantes al medir nitidez. |
| `sharpness.variant_phash` | `14` | Distancia pHash de variantes al medir nitidez. |
| `sharpness.frames` | `3` | Cuadros que se miden por video. |

## Hojas de contacto, review y triage

| Clave | Defecto | Qué hace |
|---|---|---|
| `sheets.preset` | `null` | `standard` o `low`; `null` lo decide el modo de costo. |
| `sheets.quality` | `78` | Calidad JPEG de las hojas. |
| `sheets.token_div` | `750` | Divisor con el que se estiman los tokens de imagen (ancho × alto / 750). |
| `sheets.presets` | `standard`, `low` | Columnas, tamaño de celda, cuadros por video, tope de píxeles y de tokens por hoja. |
| `review.cols` | `6` | Columnas de la tira de review. |
| `review.tile_w`, `review.tile_h` | `320`, `180` | Tamaño de cada cuadro. |
| `review.max_h` | `1568` | Alto máximo de una tira. |
| `triage.kinds` | diez categorías | Valores válidos de `kind`. |
| `triage.moods` | seis | Valores válidos de `mood`. |
| `triage.reject_why` | siete | Motivos válidos de rechazo en la pasada 1. |

## Edición, créditos y modos de costo

| Clave | Defecto | Qué hace |
|---|---|---|
| `edit.drone_share_max` | `0.45` | Fracción máxima del total que puede ser dron. |
| `edit.credits_act` | `Créditos` | Nombre exacto del último acto. |
| `edit.map_clip` | `build/mapa-4k.mp4` | Clip de mapa que `edl2guion` usa para un shot `kind: map` si no se pasa `--map`. |
| `edit.crossfade_s` | `0.6` | Fundido que asume la EDL si no declara `crossfade_s`. |
| `edit.tie_z` | `0.3` | Diferencia de nitidez desde la cual una variante ya no es un empate. |
| `edit.min_caption_s` | `2.5` | Duración mínima de un plano con caption. |
| `edit.edge_s` | `0.3` | Margen con los bordes de un clip. |
| `edit.max_drone_run` | `3` | Planos de dron seguidos que `edl-check` tolera antes de avisar. |
| `credits.fallback_title` | `Créditos` | Título de la tarjeta final si la EDL no trae texto. |
| `credits.map_attribution` | texto OSM + Natural Earth | Línea de atribución que el editor pone en los créditos. |
| `credits.map_words` | `[OpenStreetMap]` | Palabras que `edl-check` busca en los créditos cuando hay mapas. |
| `credits.music_words` | `[Música, Music]` | Palabras que `edl-check` busca cuando hay música. |
| `costmode.default` | `standard` | Modo si el proyecto no declara `cost_mode`. |
| `costmode.profiles` | `standard`, `low` | Por modo: `models` (un modelo por rol), `sheet_preset`, `editor_rounds`, `preview_iterations`, `music`, `research_subagents`, `reel`, `window_budget`. |
| `music.default_list` | `config/music_default.json` | Lista corta de temas con licencia CC BY para el modo `low`. |
| `workflow.stage_tokens` | tabla | **Estimaciones** de tokens por etapa y modo. No son mediciones: recalibralas con tu primer video. |

## Ruta del teléfono, mapas y música

| Clave | Defecto | Qué hace |
|---|---|---|
| `route.export_file` | `Rutas.json` | Nombre con el que se guarda la exportación del teléfono en `<proyecto>/route/`. |
| `route.device_dir` | `/sdcard/Download` | Carpeta del teléfono donde aparece la exportación. |
| `adb.entry_label` | `Rutas` | Texto exacto del ajuste que se toca primero (depende del idioma del teléfono). |
| `adb.export_label` | `Exportar datos de Rutas` | Texto exacto del botón de exportar. |
| `adb.forbidden_words` | `[borrar, delete]` | Si alguna aparece en el objetivo o debajo del punto a tocar, la automatización aborta sin tocar. |
| `adb.file_pattern` | regex | Nombres de archivo que cuentan como la exportación. |
| `adb.settings_action` | ajustes de ubicación | Intent con el que se abre la pantalla de ajustes. |
| `adb.timeout_s` | `180` | Cuánto se espera a que aparezca el archivo. |
| `routefill.min_interval_s` | `1.2` | Pausa entre consultas a OSRM. |
| `routefill.gap_min` | `15.0` | Minutos sin puntos desde los que hay un hueco. |
| `routefill.gap_min_km` | `1.5` | Un hueco de tiempo solo cuenta si también se movió esta distancia. |
| `routefill.speed_kmh` | `120.0` | Velocidad implícita sospechosa. |
| `routefill.speed_min_km` | `1.0` | Distancia mínima para evaluar la velocidad. |
| `routefill.jump_km` | `5.0` | Salto grande en poco tiempo. |
| `routefill.flight_km` | `150.0` | Un tramo más largo se trata como vuelo y no se rutea. |
| `routefill.feasible_kmh` | `95.0` | Velocidad por ruta que se considera posible al reprogramar horarios. |
| `routefill.road_dev_m` | `150.0` | Desvío máximo para decir que la recta ya sigue la ruta. |
| `routefill.road_ratio` | `1.06` | Relación ruta/recta bajo la cual la recta es válida. |
| `routefill.reject_ratio` | `2.2` | Relación desde la cual el ruteo se rechaza como rodeo. |
| `routefill.reject_extra_km` | `4.0` | Kilómetros extra que, junto con `reject_ratio`, rechazan el rodeo. |
| `routefill.off_corridor_km` | `1.5` | Distancia al corredor desde la que un punto es una parada fuera de ruta. |
| `routefill.drone_off_km` | `4.0` | Ídem para un grupo de tomas del dron. |
| `routefill.raw_acc_m` | `100` | Precisión máxima de un fix GPS crudo para usarlo. |
| `routefill.visit_contradict_km` | `3.0` | Distancia desde la que una visita larga contradice los puntos de su intervalo. |
| `routefill.chain_max_coords` | `24` | Coordenadas máximas por consulta. |
| `routefill.bridge_max_segs` | `4` | Tramos sanos que se pueden unir en una misma consulta. |
| `routefill.simplify_m` | `12.0` | Simplificación de la geometría devuelta. |
| `routefill.enroute_pattern` | regex | Lugares de caption que significan «en camino a». |
| `routefill.attribution` | texto | Atribución que se escribe en `route_filled.json`. |
| `routefill.check_views` | `[]` | Vistas de la imagen de control: `[{title, bbox: [lat_min, lat_max, lon_min, lon_max]}]`. Sin vistas, una sola con todo el recorrido. |
| `osm.towns` | `{}` | `{nombre: [lat, lon, radio_en_grados]}` de los pueblos para los que `vlog osm` baja calles. |
| `routemap.pad_deg` | `0.35` | Margen del mapa animado. |
| `routemap.fps` | `30` | Cuadros por segundo del clip de mapa. |
| `routemap.background`, `routemap.province_line`, `routemap.road_line`, `routemap.route_line` | colores | RGB de fondo, límites, rutas y recorrido. |
| `routemap.attribution` | `Made with Natural Earth` | Texto en una esquina del mapa. |
| `musicmix.default_target_s` | `480.0` | Duración objetivo cuando no se pasa `--target-s` ni `--guion`. |
| `musicmix.sr` | `48000` | Frecuencia de muestreo de salida. |
| `musicmix.win_beats` | `8` | Pulsos que se comparan a cada lado de un empalme. |
| `musicmix.min_play_bars` | `4` | Compases mínimos entre dos saltos. |
| `musicmix.min_loop_s` | `10.0` | Duración mínima de un tramo repetido. |
| `musicmix.head_trim_cap` | `1.0` | Segundos que se pueden recortar del comienzo para clavar la duración. |
| `musicmix.lag_ms` | `30` | Búsqueda de alineación fina de cada empalme. |
| `musicmix.search_tol_s` | `0.4` | Tolerancia de duración al buscar caminos. |
| `musicmix.gap_bars` | `16` | Compases antes de poder repetir un mismo compás sin penalización. |
| `musicmix.trim_fade_s` | `3.0` | Cuando el objetivo es más corto que el tema y la búsqueda de empalmes no encuentra un camino (típico de un reel), el tema se recorta desde el principio con este fundido final (como mucho un cuarto de la duración). |
| `musicmix.loudnorm` | `-16 / -1.5 / 11` | `lufs`, `tp` y `lra` de la normalización final. |

## Variables de entorno

| Variable | Qué hace |
|---|---|
| `VLOG_ROOT` | Carpeta de proyectos (pisa `paths.root`). |
| `VLOG_PROJECT` | Proyecto por defecto si no se pasa `--project` ni se está dentro de uno. |
| `VLOG_CONFIG` | Archivo de configuración de usuario (en lugar de `~/.config/vlog-pipeline/config.yaml`). |
| `VLOG_PYTHON` | Intérprete que usa `bin/vlog` (por defecto `venv/bin/python`, `.venv/bin/python` o `python3`). |
