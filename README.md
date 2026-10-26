# vlog-pipeline

Un pipeline para convertir el material en bruto de un viaje (fotos y videos del teléfono, tomas de un dron, la ruta de Google Maps y tus notas) en un video terminado. Cada etapa es un comando que se puede repetir, el criterio editorial lo aporta un asistente de IA con tareas acotadas y el render está hecho para no repetir trabajo: si cambiás una toma, solo se vuelve a codificar esa toma.

No es un editor gráfico ni un servicio: es un conjunto de scripts de Python y ffmpeg que corren en tu máquina, sobre una carpeta de proyecto que vos controlás.

[English summary at the end](#english-summary).

## Qué hace

- **Inventario unificado.** Junta el dron (con su telemetría SRT), el álbum de Google Photos y las exportaciones del teléfono en un solo `media.json` con hora local, posición (GPS del archivo o interpolada desde la ruta) y lugar.
- **Indexa, no copia.** Los originales se leen donde están y nunca se modifican. El proyecto guarda solo derivados y un manifiesto (`sources.json`) que detecta si falta un disco o cambió un archivo.
- **Descarte sin IA.** Un prefiltro quita lo borroso, las ráfagas, los duplicados exactos, las capturas de pantalla y lo que cae fuera de las fechas del viaje, y explica cada descarte.
- **Triage en dos pasadas** sobre hojas de contacto, con salidas JSON validadas por el CLI (el CLI no cree el informe de un subagente: lo revalida).
- **Edición por lista de cortes.** Un editor (humano o modelo) escribe una EDL; `vlog edl-check` la valida contra el brief, el triage y la nitidez; `edl2guion.py` la convierte en el guion que se renderiza.
- **Render con caché por contenido.** Fundidos, zoom en fotos sin saltos de píxel, fondo desenfocado para medios que no son 16:9, tarjetas de título y créditos, minimapa de recorrido, captions en hilo (el lugar fijo en pantalla y la descripción con fundido cruzado, sin repetir lo que ya dice un título o el minimapa), texto de tamaño fijo por salida, ritmo pausado para espectadores mayores (`pacing: relaxed`), color y nitidez automáticos, música por acto con ducking y ajuste opcional de los cortes al pulso.
- **Varias salidas nativas** del mismo guion: `tv` (4K), `celu` (1080p), `chat` (hasta 28 MB) y `reel` (vertical, hasta 90 s, con su propio guion).
- **Reanudable.** `vlog status` calcula dónde estás mirando los archivos, estima lo que falta y escribe `STATUS.md` para retomar desde otra sesión.

## Requisitos

| Componente | Para qué | Obligatorio |
|---|---|---|
| macOS, de preferencia Apple Silicon | Encoders VideoToolbox y `diskutil` (UUID de los volúmenes). En otros sistemas el render cae a `libx264`/`libx265` y el álbum se descomprime con la biblioteca estándar, pero no está probado fuera de macOS. | Recomendado |
| Python 3.12 o más | El código y las dependencias fijadas en `requirements.txt` | Sí |
| `ffmpeg` y `ffprobe` (con `libx264`, `libx265`, `aac` y los filtros que lista `vlog doctor`) | Todo el render y las mediciones | Sí |
| `exiftool` | Fechas, GPS y modelo de los archivos | Sí |
| `adb` y un teléfono Android | Solo para exportar la ruta por cable (`vlog rutas`); sin eso se importa un archivo con `--file` | Opcional |
| [Claude Code](https://claude.com/claude-code) | Quien dirige el flujo y ejecuta los subagentes de triage, cronología, edición y captions (ver [`docs/DIRECTOR.md`](docs/DIRECTOR.md)). Los comandos del CLI funcionan sin él. | Opcional |

## Instalación

```bash
git clone <url-del-repositorio> vlog-pipeline
cd vlog-pipeline
python3 -m venv venv
venv/bin/pip install -r requirements.txt
brew install ffmpeg exiftool            # macOS
brew install android-platform-tools     # opcional: adb
ln -s "$PWD/bin/vlog" ~/.local/bin/vlog # opcional: tener `vlog` en el PATH
vlog doctor
```

`bin/vlog` usa `venv/bin/python` (o `.venv/bin/python`, o lo que diga `$VLOG_PYTHON`). `vlog doctor` revisa ffmpeg (filtros y encoders), exiftool, las dependencias de Python, la tipografía, y avisa de lo opcional (adb, datos de mapas). Si el minimapa te interesa, bajá los mapas una vez:

```bash
vlog fetch-data      # GeoJSON de Natural Earth en vendor/naturalearth (dominio público)
```

La tipografía de los textos sale de `fonts.main`; si no la definís, se usa la primera que exista de una lista del sistema (Futura, Helvetica, Arial, DejaVu).

## Inicio rápido: un viaje nuevo

Todos los comandos se corren dentro de la carpeta del proyecto, o con `--project <carpeta>`.

```bash
# 1. Crear el proyecto. Pregunta tema, duración, resolución, zona horaria y modo de costo,
#    y rechaza crearlo si no hay lugar para los derivados (el doble de las fuentes).
vlog new mi-viaje --root ~/vlogs --drone /Volumes/<TARJETA_SD> --album ~/Downloads/album.zip
cd ~/vlogs/mi-viaje

# 2. Completar DIRECTION.md (el brief) y las fechas del viaje en project.yaml:
#    ingest.start_date / ingest.end_date, y ingest.owners para nombrar los dispositivos.
#    Ver examples/project.example.yaml y examples/DIRECTION.example.md.
vlog doctor

# 3. Fuentes
vlog rutas --from 2025-06-10 --to 2025-06-17        # por cable, o: --file Rutas.json
vlog album ~/Downloads/album.zip                     # descomprime fuera del proyecto y cuenta los archivos
vlog ingest && vlog sources build && vlog sources check
vlog proxies

# 4. Descarte y hojas de contacto
vlog prefilter
vlog sheets

# 5. Triage, edición, captions, música (los hace quien dirige; el CLI imprime cada prompt)
vlog triage-plan --pass 1        # un prompt por día; lanzar un subagente por grupo
vlog sheets --survivors && vlog triage-plan --pass 2
vlog triage-merge && vlog sharpness
vlog prompt editor               # luego: vlog edl-check
python -I pipeline/edl2guion.py . --edl edl.json --out guion.json

# 6. Mirar, aprobar, renderizar
vlog preview                     # <nombre>-preview.mp4
vlog approve preview             # solo con el OK explícito del dueño del video
vlog final && vlog render        # las salidas de `outputs:` en project.yaml

# En cualquier momento
vlog status                      # etapa actual, siguiente paso, tokens estimados; escribe STATUS.md
vlog clean                       # simulacro: qué derivados regenerables se podrían borrar
```

El detalle de cada etapa, quién la hace y cómo se verifica está en [`docs/DIRECTOR.md`](docs/DIRECTOR.md); lo que ve y decide quien hace el video, en [`docs/GUIA.md`](docs/GUIA.md).

## Modos de costo

El modo (`cost_mode` en `project.yaml`) fija qué modelo hace cada tarea, cuántas rondas tiene el editor y cuánta imagen se manda al triage.

| | `standard` | `low` |
|---|---|---|
| Editor (la EDL) | modelo grande, 2 rondas | modelo mediano, 1 ronda |
| Hojas de contacto | `standard` (más cuadros por video) | `low` (celdas más chicas) |
| Música | un subagente busca y filtra candidatos | la trae el dueño, o se elige de `config/music_default.json` |
| Captions | lugar y dato con fuente | solo lugar |
| Reel | obligatorio | opcional |
| Tokens por video (estimación) | ≈ 1,5 M | ≈ 0,8 M, en ventanas de 300 k |

Las cifras son **estimaciones** derivadas de un primer viaje, no mediciones de tu proyecto; salen de `workflow.stage_tokens` en [`config/defaults.yaml`](config/defaults.yaml) y conviene recalibrarlas con tu primer video. La tabla por etapa y modelo está en [`docs/DIRECTOR.md`](docs/DIRECTOR.md); `vlog profile` muestra el perfil vigente.

## Salidas y presets

| Preset | Formato | Cómo sale |
|---|---|---|
| `preview` | 960x540, H.264, usa proxies cuando sirven | Render rápido para mirar |
| `tv` (`final`) | 3840x2160, HEVC, AAC 256k | Render desde los originales; es el master |
| `celu` | 1920x1080, H.264 | Render nativo, con minimapa y captions a su escala |
| `chat` | 640x360, H.264, hasta 28 MB | Render nativo; se recomprime si pasa el límite |
| `reel` | 1080x1920, H.264, hasta 90 s | Otro guion (`guion-reel.json`); recorta los medios apaisados alrededor de `focus_x` |

Resoluciones, bitrates y codecs se pisan en `presets` (ver [`docs/CONFIG.md`](docs/CONFIG.md)). Sin VideoToolbox el codec cae solo a `libx264`/`libx265`.

## Configuración

Todo lo ajustable vive en YAML y se resuelve por capas: [`config/defaults.yaml`](config/defaults.yaml) < `~/.config/vlog-pipeline/config.yaml` < `project.yaml` del proyecto. Cada clave está explicada en [`docs/CONFIG.md`](docs/CONFIG.md); `vlog config` imprime el resultado fusionado.

## Fuentes de datos y licencias

El código de este repositorio es MIT. Lo que consulta o descarga tiene sus propias condiciones; usalo respetándolas.

| Dato o servicio | Para qué | Licencia y obligaciones |
|---|---|---|
| [Natural Earth](https://www.naturalearthdata.com/) | Rutas y límites del mapa regional del minimapa (`vlog fetch-data`) | Dominio público. No exige crédito; el pipeline lo ofrece («Made with Natural Earth») y el editor lo incluye en los créditos. |
| [OpenStreetMap](https://www.openstreetmap.org/copyright), vía [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) | Calles, parques y agua de los pueblos (`vlog osm`) | Datos bajo ODbL: hay que atribuir «© OpenStreetMap contributors» en el video. Overpass pide un uso moderado y un User-Agent que identifique a quien consulta (`http.contact`). **No se usan los mosaicos (tiles) de OSM**; el mapa se dibuja localmente. |
| [OSRM demo server](https://github.com/Project-OSRM/osrm-backend/wiki/Api-usage-policy) | Rellenar huecos de GPS ruteando por calles (`pipeline/routefill.py`, opcional) | Servidor de demostración (FOSSGIS): su política limita las consultas (el script hace como mucho una cada 1,2 s y guarda cada respuesta en caché), pide identificarse y no es para uso intensivo ni comercial. Los datos de ruta son ODbL: atribución OSM. |
| [Nominatim](https://operations.osmfoundation.org/policies/nominatim/) | Nombre del lugar de cada toma, por geocodificación inversa (`vlog ingest`) | Política pública: máximo una consulta por segundo, User-Agent identificable, resultados en caché (se agrupan por celdas de unos 1 km y se guardan en `inv/geocache.json`). Se desactiva con `ingest.geocode: false`. Atribución OSM. |
| Música | Banda sonora | Cada tema tiene su licencia y hay que leerla en la fuente. `config/music_default.json` trae cuatro temas de [Kevin MacLeod / Incompetech](https://incompetech.com/music/royalty-free/) bajo CC BY 4.0, que exigen atribución (la `credit_line` de cada uno va a la tarjeta de créditos). [Pixabay](https://pixabay.com/service/license-summary/) tiene su propia licencia; antes de subir un video a una plataforma con Content ID, evitá los temas con protección Content ID. |
| Tipografías | Textos del video | El repositorio no incluye ninguna. Usá una cuya licencia permita incrustarla en un video. |
| ffmpeg | Render | No se distribuye con este repositorio. Un ffmpeg con `libx264`/`libx265` es GPL. |

## Privacidad

- **Los originales no se tocan ni se copian.** El álbum se descomprime una vez fuera del proyecto y todo lo demás se indexa por ruta, tamaño y huella parcial.
- **Todo corre en tu máquina**, salvo las consultas de red de arriba. Dos de ellas mandan coordenadas de tus tomas a un servidor público: Nominatim (cada celda de ~1 km del inventario) y OSRM (los tramos que se rutean). Desactivá Nominatim con `ingest.geocode: false`; OSRM solo se usa si corrés `routefill.py`.
- **`media.json`, `route/` y `inv/` contienen tus posiciones y horarios.** No publiques una carpeta de proyecto.
- **Si dirigís el flujo con un asistente de IA**, las hojas de contacto (imágenes de tus tomas), las notas y los prompts van al proveedor del modelo que uses. Lo sensible (salud, dinero, trabajo, momentos poco favorecedores) se pone en el `avoid` de la cronología y del triage y no se menciona en los textos. Ningún subagente recibe herramientas de envío, y ningún mensaje a una persona sale sin el OK del dueño del video.
- El pipeline no envía telemetría ni abre cuentas.

## Limitaciones

- Pensado y probado en macOS; fuera de él no se registra el UUID de los volúmenes (`diskutil`) y el render usa codificación por software, más lenta.
- La exportación de la ruta por `adb` automatiza la interfaz del teléfono Android y depende de los textos de la pantalla (hoy en español). Si no coinciden, usá `--file` con una exportación manual o ajustá `adb.*`.
- La telemetría del dron que se lee es la de los `.SRT` de DJI; otras marcas funcionan como cámara común (sin posición ni ISO).
- Los textos del CLI, las plantillas de prompt y las categorías del triage están en español. Se pueden traducir editando `docs/prompts/` y las listas de `config/defaults.yaml`.
- La huella «rápida» de los archivos (SHA-1 del primer y último MiB más el tamaño) detecta cambios y duplicados probables, no garantiza identidad bit a bit.
- Las estimaciones de tokens no son mediciones.
- Se necesita espacio: los derivados (`proxy/`, `build/`) pueden ocupar el doble de las fuentes; `vlog clean` los lista y los borra a pedido.

## Estructura del repositorio

```
bin/vlog              entrada del CLI
pipeline/             el código: cli.py y un módulo por etapa
config/               defaults.yaml, plantilla del brief, lista corta de música
docs/                 guías, referencia de configuración, arquitectura y plantillas de prompt
examples/             project.yaml y brief de ejemplo (datos ficticios)
tests/                suite de unittest con carpetas temporales y datos inventados
```

## Documentación

- [`docs/GUIA.md`](docs/GUIA.md): cómo se vive el proceso desde quien hace el video.
- [`docs/DIRECTOR.md`](docs/DIRECTOR.md): el runbook de punta a punta, con modelos, costos y verificaciones.
- [`docs/ROLES.md`](docs/ROLES.md): director, subagentes y la regla de auditoría.
- [`docs/GUION.md`](docs/GUION.md): formato del guion y de todo lo que se puede pedir por toma.
- [`docs/CONFIG.md`](docs/CONFIG.md): cada clave de configuración.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): etapas, artefactos, modelo de datos, decisiones, caché y puntos de extensión.
- [`docs/prompts/`](docs/prompts/): las plantillas que rellena `vlog prompt` y `vlog triage-plan`.

## Contribuir y licencia

Ver [`CONTRIBUTING.md`](CONTRIBUTING.md) y [`CHANGELOG.md`](CHANGELOG.md). Licencia [MIT](LICENSE).

---

## English summary

**vlog-pipeline** turns raw trip footage (phone photos and videos, drone clips with DJI telemetry, a Google Maps timeline export and your notes) into a finished video. It is a set of Python and ffmpeg scripts driven by a `vlog` CLI, not a GUI or a service.

- **Idempotent, resumable stages.** `vlog status` derives progress from the files on disk and writes `STATUS.md` so you can resume from a fresh session.
- **Index, never copy.** Originals are read in place and never modified; the project folder stores derived files and a `sources.json` manifest that notices missing disks or changed files.
- **A model only where judgement is needed.** Deterministic CLI stages do the inventory, a no-LLM prefilter (blur, bursts, duplicates, screenshots, out-of-range dates), contact sheets and rendering. Prompt templates in `docs/prompts/` drive a director plus sub-agents (designed for Claude Code) for triage, chronology, the edit decision list and captions. Their JSON outputs are re-validated by the CLI, never trusted.
- **Content-hash render cache.** Editing one shot re-encodes only that shot. Native outputs: `tv` (4K), `celu` (1080p), `chat` (<= 28 MB), `reel` (vertical, <= 90 s).
- **Everything tunable is YAML**: `config/defaults.yaml` < `~/.config/vlog-pipeline/config.yaml` < `project.yaml`. See `docs/CONFIG.md` and `examples/`.

**Requirements:** macOS (Apple Silicon recommended; encoders fall back to libx264/libx265 elsewhere, untested), Python 3.12+, ffmpeg/ffprobe, exiftool; optional adb + Android phone and Claude Code.

**Install:** `python3 -m venv venv && venv/bin/pip install -r requirements.txt`, then `bin/vlog doctor`.

**Cost modes** (`standard`, `low`) choose the model per role; the token figures (about 1.5 M and 0.8 M per video) are estimates, not measurements.

**Data and licences.** Code: MIT. Natural Earth is public domain. OpenStreetMap data (Overpass, OSRM routing, Nominatim) is ODbL and requires "© OpenStreetMap contributors"; OSM tiles are not used; the Nominatim and OSRM demo usage policies apply (rate limits, identifying User-Agent via `http.contact`, caching). Music licences are yours to check; the bundled short list is CC BY 4.0 and requires attribution. Reverse geocoding sends the coordinates of your media to a public server unless you set `ingest.geocode: false`.

**Limitations:** Spanish-language CLI output and prompts, DJI-only telemetry, adb automation tied to the phone's UI labels, macOS-first.
