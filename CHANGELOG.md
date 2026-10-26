# Changelog

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado, [SemVer](https://semver.org/lang/es/).

## [0.2.0]

Cambios a partir de la revisión de un video en una TV.

### Cambiado
- El texto superpuesto tiene tamaño fijo por salida: se quitó el ajuste al ancho. La etiqueta del minimapa y los captions comparten una escala tipográfica (`caption.format_defaults`) y un área segura; los nombres largos se parten en 2 renglones en límites de palabra. Los títulos y las tarjetas también se parten en lugar de achicarse.
- Más grande en la TV: el minimapa `tv` pasa de 10 % a 14 % del lado corto y el texto sube a 1,4x (lugar 54 px y descripción 45 px en 4K); `celu`, `chat` y `reel` suben a 1,25x y su minimapa se agranda en proporción. El texto del preview ahora es proporcional al del master (antes tenía pisos de 30 y 24 px).
- Los captions se dibujan al ensamblar cada parte, como el minimapa, y no en los segmentos: editar un caption ya no recodifica el segmento. El caché de segmentos se invalida una vez.
- `caption.min_shot_s` se aplica a la racha completa y `edit.min_caption_s` (`caption-short`) también.
- `minimap.label_scale` pasa de 0,8 a 1,0 y `minimap.presets.*.label_fit` y `label_min_px` ya no se leen (reemplazados por `label_max_w` y la escala compartida).

### Agregado
- Captions en hilo: los shots consecutivos con el mismo lugar forman una racha; el lugar no se corta en cada corte y solo la descripción cambia, con fundido cruzado. Cada descripción tiene permanencia mínima (`caption.min_line_s` + `caption.line_s_per_word` por palabra) y persiste en el shot siguiente si el suyo es corto (`caption.on_short_shot`).
- Sin redundancias: el lugar que ya nombra un título, una tarjeta de acto o la etiqueta del minimapa no se repite (`caption.suppress_redundant_place`, `minimap.suppress_redundant_place`). `vlog edl-check` avisa (`caption-dup-title`, `caption-dup-minimap`, `caption-min-time`, `caption-no-room`).
- `pacing: relaxed|standard` (defecto `relaxed`, rangos 1,3x más largos y menos cortes por minuto) y `pacing.min_shot_s`; lo leen el prompt del editor y `vlog edl-check` (`pacing-short`, `pacing-cuts`).
- Los prompts de captions y del editor piden un dato verificado en la web, con URL, de hasta 12 palabras, priorizado en tomas largas de dron.
- `vlog overlay-check`: stills de un shot sintético con minimapa y caption por preset, sin material propio.

## [0.1.0]

Primera versión pública.

### Agregado
- CLI `vlog` con una etapa idempotente por subcomando: `new`, `doctor`, `config`, `fetch-data`, `osm`, `rutas`, `album`, `ingest`, `sources`, `proxies`, `prefilter`, `sheets`, `triage-plan`, `triage-merge`, `sharpness`, `edl-check`, `prompt`, `preview`, `final`, `render`, `approve`, `status`, `profile`, `clean`.
- Render por lista de cortes (`guion.json`) con caché por contenido, salidas nativas `tv`, `celu`, `chat` y `reel`, minimapa continuo, captions, color y nitidez automáticos, mezcla de audio con ducking y ajuste de cortes al pulso de la música.
- Modos de costo `standard` y `low`, con un modelo por rol, plantillas de prompt en `docs/prompts/` y `STATUS.md` para retomar entre sesiones.
- Configuración por capas en YAML: `config/defaults.yaml`, configuración de usuario y `project.yaml`. Referencia en `docs/CONFIG.md`; ejemplos en `examples/`.
- `vlog doctor` revisa ffmpeg (filtros y encoders), exiftool, adb (opcional), dependencias de Python, tipografía y datos de mapas.
- Fallback automático de los encoders VideoToolbox a `libx264`/`libx265`.
- `vlog fetch-data` (Natural Earth) y `vlog osm` (calles de pueblos desde Overpass).

### Corregido respecto del código interno previo
- Las fechas de `routefill.py` siempre llevaban el desfase `-03:00`, fuera cual fuera la zona horaria configurada.
- El minimapa descartaba en silencio los puntos de la ruta al sur de una latitud fija; ahora el filtro es opcional (`minimap.lat_min`).
- El recuadro de caminos del mapa regional no escalaba con `minimap.radius_km`.
- `vlog album` podía elegir `/originales` en la raíz del disco como destino cuando el proyecto estaba en el disco del sistema.
- `triage.people` devolvía el regex del dueño del dispositivo en lugar de su nombre.
- `inventory.py` ignoraba videos con extensión en minúscula, evaluaba con `eval` la velocidad de cuadros que devuelve ffprobe y fallaba si la carpeta no tenía fotos JPG.
- `gradecompare.py` fijaba 29,97 cuadros por segundo para ubicar el cuadro a comparar.
- `shortmix.py` buscaba los módulos en una ruta fija del home del autor.
- `musicmix.py` y `routefill.py` tenían una carpeta de proyecto por defecto fija.
- `routemap.py` fallaba con sesiones sin coordenadas.
- `vlog new` escribía en `project.yaml` una resolución de preview y un bitrate que ningún comando leía; ahora escribe solo `output.fps` y `output.final`, que el render sí respeta.
- `vlog new` fallaba con un traceback ante una resolución o una duración inválidas.

### Quitado
- Scripts sueltos que contenían datos de un viaje concreto o que no tenían un flujo de uso (`captions.py`, `geocode.py`, `score.py`, `sheet.py`, `mix.sh`).
