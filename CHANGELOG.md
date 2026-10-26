# Changelog

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado, [SemVer](https://semver.org/lang/es/).

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
