# Formato del guion (`guion.json`)

El guion es la lista de cortes que el director escribe y que `pipeline/render.py` convierte en video. Se ejecuta con `./venv/bin/python -I pipeline/render.py guion.json preview|final|tv|celu|chat|reel` (o `vlog preview` / `vlog final` / `vlog render [preset...]`).

## Estructura general

```json
{
  "name": "trip",
  "project": ".",
  "inventory": "inv/media.json",
  "proxy_dir": "proxy",
  "cache_dir": "build/preview",
  "out_dir": ".",
  "snap_to_beats": false,
  "output": {"fps": "30000/1001", "preview": {}, "final": {}},
  "style": {},
  "music": [],
  "shots": []
}
```

| Clave | Qué es |
|---|---|
| `name` | Prefijo del archivo de salida: `<out_dir>/<name>-preview.mp4` o `-final.mp4`. |
| `project` | Raíz del proyecto, relativa a la carpeta del guion (por defecto, esa carpeta). De ahí salen `inventory`, `proxy_dir` y `music/`. |
| `inventory` | Lista de medios. Por defecto `inv/media.json`. Los inventarios viejos (`inventory.json`, sin `id`) siguen andando: el id pasa a ser el nombre de archivo sin extensión. |
| `cache_dir`, `out_dir` | Dónde van segmentos/partes/audio cacheados (por defecto `<project>/build/<modo>`) y el video terminado (por defecto `<project>`). |
| `grading` | `true` (defecto) / `false`. Con `false` no se aplica color ni nitidez y los segmentos salen con el mismo hash de antes del grading, así que el caché viejo se reutiliza tal cual. |
| `snap_to_beats` | `true` ajusta las duraciones a los beats del tema vigente (ver abajo). |
| `output.fps` | Siempre `"30000/1001"` salvo razón fuerte. Se acepta una fracción o un número (30 o 29.97). |

## Presets de salida

Salidas que produce el proyecto (`outputs:` de `project.yaml`, ver "Salidas del proyecto"):

| Preset | Qué es | Cómo sale |
|---|---|---|
| `tv` | 3840x2160 HEVC (~58 Mb/s medidos), AAC 256k. Es el master; `final` es el mismo render con el archivo `<name>-final.mp4`. | Render desde originales: `<name>-tv.mp4` |
| `celu` | 1920x1080 H.264 ~8 Mb/s (libx264, tope 10 Mb/s), AAC 160k, `faststart`. | Transcode del master `tv` (si falta, lo renderiza primero) |
| `chat` | 640x360 H.264, AAC 64k, **<= 28 MB** (bitrate calculado por duración, tope 1,5 Mb/s; si pasa el límite reintenta con 15 % menos). | Transcode del master `tv` |
| `reel` | 1080x1920 (9:16, Instagram) H.264 12 Mb/s, AAC 160k, **máx. 90 s** (el guion se rechaza si dura más). | Render propio desde **otro guion** (`guion-reel.json`) |

Detalle de los presets de render (`preview`, `final`/`tv`, `reel`):

| | preview | final |
|---|---|---|
| Resolución | 960x540 | 3840x2160 |
| Fuentes | proxies (si sirven) | originales |
| Video | h264_videotoolbox, 4 Mb/s | hevc_videotoolbox `hvc1`, `bitrate` 60M (medido 48 Mb/s en un test; ~0,8x lo pedido) |
| Audio | AAC 128k | AAC 256k |

Los valores de fábrica están en `presets` de `config/defaults.yaml`; sin VideoToolbox (otro sistema o un ffmpeg sin él) el codec cae a `libx264`/`libx265`. Se pisan con `output.preview` / `output.final` / `output.reel` (en el guion o en `project.yaml`; `vlog new` escribe ahí la resolución elegida): `w`, `h`, `bitrate`, `seg_bitrate` (intermedios, 80M en final), `codec`, `audio_bitrate`. `output.shots_per_part` (por defecto 24 en preview, 4 en final) fija cuántos shots se codifican por ffmpeg: más shots es más memoria (en 4K cada input abierto retiene unos 250 MB).

Los proxies de teléfono de video vertical vienen con barras negras dentro de 640x360: no sirven como fuente del fondo desenfocado, así que en preview esos shots usan el original (avisa en el reporte). Los proxies del dron sí se usan.

## Shots

Cada shot es un objeto. El tipo sale de su clave: `card`, `map`, o `id` (o `src`) de un medio, cuyo `kind` en `media.json` decide si es video o foto.

Campos comunes:

| Campo | Valor | Efecto |
|---|---|---|
| `transition` | `"fade"` (defecto) / `"cut"` | Cómo entra este shot. `fade` es un xfade de `style.xfade` s (0,6); `cut` es corte seco. El primero ignora el campo. |
| `xfade` | segundos | Pisa la duración del fundido de entrada de este shot. |
| `title` | `{"text","sub","dur"}` | Lower-third (PNG Pillow, fondo oscuro, tipografía `fonts.main`; un texto largo se parte en renglones, no se achica). `dur` en segundos (defecto el menor entre 3,5 s y la duración del shot). |
| `snap` | bool | Si participa del beat snap. Defecto `true`, salvo en `card`. |
| `grade`, `sharpen` | ver "Color y nitidez" | Solo fotos y videos. |

### Video: `{"id": "drone.DJI_0417", "in": 4, "out": 11}`
`in`/`out` en segundos de la fuente. En vez de `out` se puede dar `dur` (segundos de salida). `speed` (defecto 1). `audio`: `"keep"` o `"mute"` (defecto). Si el video pide más de lo que tiene se recorta y avisa. `fit`: `"blur"` (defecto) o `"fill"` (recorta para llenar). `gain_db`: ajuste extra del audio del clip.

### Foto: `{"id": "phone_a.20250613_110520", "dur": 4, "zoom": "in", "focus": [0.5, 0.35]}`
`dur` (defecto `style.photo_dur`, 3 s). `zoom`: `in` (defecto, 8 %), `out`, `pan` (barrido horizontal con zoom 14 %, `dir`: `right|left|down|up`) o `none`. `focus`: `[x, y]` entre 0 y 1 sobre la foto; el zoom termina (o empieza, en `out`) centrado ahí con `style.focus_zoom` (14 %). Los JPEG se leen con su orientación EXIF. El zoom es `perspective` con coordenadas float por frame (sin saltos de píxel).

### Minimapa (`minimap`)

Círculo de navegación arriba a la derecha con la ruta recorrida, el punto naranja centrado y debajo una etiqueta apilada (lugar + fecha, de tamaño fijo). Sale solo del GPS y la hora del medio (`lat`, `lon`, `time_art` de `media.json`; en un video se suma `in`), del lugar de `captions.json`/`route/labels.json` y de `route/route_filled.json` (si existe; si no, `route.json`). En un pueblo con calles OSM en `vendor/osm/` (se bajan con `vlog osm`; radio `urban_km`) dibuja calles; fuera, mapa regional de `radius_km`. El mapa regional sale de Natural Earth (`vlog fetch-data`). `lat_min` descarta los puntos de la ruta al sur de esa latitud, `places.natural_earth` suma ciudades de referencia y `places.always` fija cuáles se rotulan siempre (ver [`CONFIG.md`](CONFIG.md)).

**Rachas.** Una racha es una secuencia de shots consecutivos con minimapa; la rompen una tarjeta, un mapa, un shot sin GPS o `"minimap": false`, y el cambio de `act` (`break_on_act`, `true` por defecto). Dentro de la racha el minimapa queda en pantalla de corrido: en cada corte cambia el punto y la etiqueta al instante, sin fundido, y en un fundido cruzado entre dos shots de la misma racha cambia en su punto medio. Entra con un fundido de 0,4 s cuando termina el fundido de entrada del primer shot de la racha y sale con otro de 0,4 s que termina donde empieza el fundido hacia la tarjeta, el mapa o el shot siguiente (o 1 s antes del final del video). Se superpone al ensamblar cada parte, no en los segmentos: los segmentos no dependen del minimapa y cambiarlo recodifica sólo las partes que toca.

**Escala por formato.** El diámetro es una fracción del lado corto del cuadro, según el formato de salida (`tv`, `celu`, `chat`, `reel`; `preview` usa los de `tv`). La ruta, el punto y el anillo escalan con él. La etiqueta usa la misma escala tipográfica fija que los captions (lugar a `caption.place`, fecha a `caption.line`) y los mismos márgenes: el tamaño del texto no cambia de un shot a otro. Un nombre largo se parte en 2 renglones en límites de palabra en lugar de achicarse. Si un título o una tarjeta del acto ya nombra el lugar (`suppress_redundant_place`), la etiqueta muestra solo la fecha.

```yaml
minimap:
  enabled: true
  opacity: 0.6
  position: top-right
  label_scale: 1.0
  radius_km: 120
  urban_km: 1.2
  break_on_act: true
  presets:
    tv: {diameter: 0.14, label_max_w: 0.20}
    celu: {diameter: 0.14, label_max_w: 0.22}
    chat: {diameter: 0.18, label_max_w: 0.30}
    reel: {diameter: 0.19, label_max_w: 0.55, margin_y: 0.13}
```

`enabled` es `false` por defecto; los valores de `presets` también tienen el mismo defecto en el código y `project.yaml` sólo pisa lo que cambia. `diameter`: fracción del lado corto; `label_size` multiplica (junto con `label_scale`) la escala tipográfica compartida; `label_max_w`: ancho máximo de la etiqueta (fracción del ancho); `margin_x`/`margin_y` (fracción del ancho y del alto): por defecto los de los captions. `size` (fracción del lado corto) pisa `diameter` en todos los formatos. Config en `project.yaml` o en el guion (gana). Por shot: `"minimap": false` lo apaga; `"minimap": {"opacity": 0.4, "place": "Mirador"}` pisa cualquier clave (y `place` fuerza la etiqueta). El PNG recortado se cachea por shot y formato (`minimap-<hash>.png`) y la clave de la parte incluye los intervalos y los PNG.

### Caption por shot (`caption`)

`{"id": "...", "dur": 5, "caption": {"place": "Iglesia del pueblo", "line": "Construida en el siglo XVII"}}`. Texto abajo a la izquierda, sin caja (tipografía `fonts.main` en blanco, sombra suave y trazo fino, igual que la etiqueta del minimapa). `line` puede ser `null` y `place` también (si hay `line`).

**Rachas.** Los shots consecutivos con el mismo `caption.place` forman una racha (la cortan una tarjeta, un mapa, un shot sin caption, un cambio de `act` o un shot con `title`). El lugar queda en pantalla toda la racha: entra con un fundido de 0,5 s que empieza 0,5 s después de que el primer shot se ve entero (o cuando termina su título) y sale con otro que termina donde empieza el fundido hacia lo que sigue. No hay fundido en cada corte: solo la descripción cambia, con un fundido cruzado centrado en el corte. Se superpone al ensamblar cada parte, como el minimapa: los segmentos no llevan captions y editarlos recodifica solo las partes que toca.

**Permanencia mínima.** Cada descripción necesita `caption.min_line_s` + `caption.line_s_per_word` por palabra en pantalla (1,5 s + 0,3 s por palabra). Si su shot es demasiado corto, la descripción sigue en el shot siguiente de la racha (`caption.on_short_shot: persist`; con `skip` se omite) y la del shot siguiente entra cuando la anterior cumplió su tiempo; los shots cortos de una racha muestran solo el lugar. Una descripción que no llega a cumplir su tiempo antes de terminar la racha se omite y avisa. Una racha de menos de `caption.min_shot_s` (2,5 s) no lleva caption. Si el título del shot (o la tarjeta del acto) ya nombra el lugar, o la etiqueta del minimapa del primer shot de la racha lo repite, el renglón del lugar se omite y queda la descripción (`caption.suppress_redundant_place`); `vlog edl-check` avisa de estas repeticiones.

El tamaño es fijo por formato (no se ajusta al largo del texto), como fracción del lado corto con un mínimo en píxeles, y es el mismo que usa la etiqueta del minimapa. En `caption.presets` de `project.yaml`:

```yaml
caption:
  presets:
    tv: {place: 0.0252, line: 0.021, min_place_px: 16, min_line_px: 13}
    celu: {place: 0.0275, line: 0.0225, min_place_px: 20, min_line_px: 16}
    chat: {place: 0.045, line: 0.0375, min_place_px: 13, min_line_px: 11, max_w: 0.6}
    reel: {place: 0.0525, line: 0.0425, min_place_px: 46, min_line_px: 37, max_w: 0.88, margin_y: 0.20}
```

`max_w` es el ancho máximo del texto (fracción del ancho), `margin_x`/`margin_y` los márgenes. Un lugar largo se parte en 2 renglones; la descripción, en los que haga falta. En el reel el caption sube a 20 % del alto. `vlog overlay-check` genera stills de un shot sintético con minimapa y caption en cada preset para revisar los tamaños.

### Reencuadre (`focus_x`)

Solo importa cuando el medio se recorta (`fit: "fill"`): `focus_x` (0 a 1, defecto 0,5) elige el punto horizontal del medio sobre el que se centra el recorte. En el reel todo medio apaisado se recorta a 9:16 así por defecto; los verticales exactos (9:16) llenan el cuadro y los verticales 3:4 se componen sobre su fondo desenfocado sin perder bordes. `fit: "blur"` sigue disponible por shot.

### Tarjeta: `{"card": {...}, "dur": 4}`
```json
{"card": {"title": "Nombre del pueblo · 13 de junio", "sub": "texto chico",
          "lines": ["Alice y Bob · Junio 2025"],
          "music_credits": true,
          "bg": {"id": "drone.DJI_0001", "at": 20}}, "dur": 4}
```
`bg` puede ser `{"id": ..., "at": segundos}` (cuadro de un video o foto, desenfocado y oscurecido) o `{"color": "#1b1511"}`; sin `bg`, color sólido `style.card_color`. `lines` son renglones chicos; con `music_credits: true` se agregan los créditos de `music/credits.json` (ver abajo). Los textos largos se parten en renglones en límites de palabra para entrar en el 86 % del ancho (solo una palabra que no entra sola se achica). Las tarjetas no participan del beat snap salvo `"snap": true`.

### Mapa: `{"map": "ruta/al/clip.mp4", "in": 0, "dur": 6}`
Clip prerenderizado (por ejemplo con `routemap.py`). Ruta absoluta o relativa al guion/proyecto. Se convierte a la resolución y fps de salida.

## Reel vertical (`reel`)

`render.py guion-reel.json reel` (o `vlog render reel`) usa un guion aparte, de hasta 90 s, con el mismo formato. Cambia el diseño: 1080x1920, medios apaisados recortados a 9:16 alrededor de `focus_x`, título en el tercio medio (a 60 % del alto, ajustado al 88 % del ancho), caption y minimapa reubicados para esquivar la interfaz de Instagram (arriba 13 %, abajo 20 %) y dimensionados por su lado corto (el ancho) y un `shots_per_part` de 8. El caché es `build/reel` (separado). Prueba medida: 15 s, 4 shots, 30 s de render.

## Salidas del proyecto (`outputs`)

```yaml
outputs:
- tv
- celu
- chat
- preset: reel
  guion: guion-reel.json
```

`vlog render` produce todas en ese orden (`vlog render tv celu` produce solo esas). Los archivos son `<out_dir>/<name>-<preset>.mp4` y `vlog clean` los trata como finales (nunca los borra). Las entradas viejas con ruta (`build/x-final.mp4`) se siguen respetando. `celu` (1920x1080) y `chat` (640x360) se renderizan nativos, cada uno con su caché (`build/celu`, `build/chat`) y sus minimapa y caption a su escala; ya no se transcodifican desde `tv`. `chat` se recomprime con x264 si pasa de 28 MB.

## Relación de aspecto

Todo medio que no sea 16:9 (tolerancia `style.aspect_tol`, 2 %) se compone encima de una copia de sí mismo escalada para llenar, desenfocada (`bg_sigma` 6 sobre 480x270) y oscurecida (`bg_dim` 0,55). Aplica a fotos verticales, fotos 4:3, videos verticales y mapas. Nunca hay barras negras. En fotos el zoom actúa sobre el conjunto fondo + foto.

## Audio

Por shot: `audio: "keep"` mezcla el audio del clip original (siempre desde el original, aunque el preview use proxy), normalizado hacia `style.clip_lufs` (-18) con el `audio_lufs` de `media.json` (tope +15 dB), con fundidos de `style.clip_fade` (0,25 s) o menos. Los drones no tienen audio: se ignora `keep` y avisa.

Música:
```json
"music": [
  {"file": "music/a.mp3", "from_shot": 0, "to_shot": 9, "gain_db": 0},
  {"file": "music/b.mp3", "from_shot": 10, "to_shot": 24}
]
```
`from_shot`/`to_shot` son índices base 0 inclusivos (defecto: todo el video). Cada tema se normaliza a `style.music_lufs` (-16 LUFS, tp -1,5) con loudnorm en dos pasadas; la medición y el wav quedan en la caché. Temas de actos contiguos se unen con `acrossfade` de `style.music_xfade` (2 s) que termina justo cuando empieza el acto nuevo. Si un tema es más corto que su tramo se repite en bucle (avisa). Fundido de entrada `music_fade_in` y de salida final `music_fade_out` (3 s). Bajo los clips con `keep` la música baja `style.duck_db` (-8 dB, `sidechaincompress`; `duck_offset_db` calibra el umbral: medido -8,1 dB). Un tema cuyo archivo no existe se omite con aviso; sin ningún tema queda el audio de los clips, y sin clips, silencio AAC. `music` como objeto suelto (formato viejo) se acepta como un único tema.

`music/credits.json`: lista de `{"slot","file","credit"}` o `{"file","title","artist","source"}`. Solo las entradas con `file` (y usado en `music`) generan renglones en las tarjetas con `music_credits: true`.

## Beat snap

Con `"snap_to_beats": true` cada shot (salvo `snap: false` y tarjetas) se estira o acorta hasta que su corte (el punto medio del fundido, o el corte seco) caiga en un beat del tema que suena, usando `snap.py`. Límites: ±`style.snap_tolerance` (35 %) de la duración pedida, un piso por las transiciones y los frames que el video realmente tiene (si no llega, el corte queda fuera de pulso y avisa). Los beats se calculan con `beats.py` sobre el wav normalizado y se cachean; un tema puede traer `"beats": "archivo.json"` (salida de `beats.py`). Sin temas disponibles no hace nada y avisa. Medido con temas de prueba: cortes a 3-35 ms de un beat (techo: un frame). `snap.py` coloca los cortes en orden: cada uno cae en el pulso más cercano a (cursor + duración preferida) dentro de [mínimo, máximo], con un bono para los tiempos fuertes (`downbeats`).

## Color y nitidez (grading)

Cada foto y video recibe un retoque liviano elegido solo (tarjetas y mapas no). Está pensado para un televisor de 45": corrige, no estiliza. `pipeline/grade.py` decide y arma los filtros; `render.py` los inserta en el segmento y el plan entra en el hash, así que prender, apagar o editar un perfil recodifica solo los segmentos afectados.

Por shot, en el guion:

| Campo | Valor | Efecto |
|---|---|---|
| `grade` | `"auto"` (defecto) / `"none"` / `"night"` / `"day_drone"` / `"day_phone"` | Perfil de color. `none` deja el shot como salió de la cámara. |
| `sharpen` | `"auto"` (defecto) / `true` / `false` | Nitidez chica (`cas` 0,4 sobre luma). `auto` solo la aplica a tomas con zoom confirmadas como blandas. |

### Perfiles

| Perfil | Qué hace |
|---|---|
| `night` | Curva que levanta sombras y medios bajos y vuelve a identidad desde 0,82: las luces no se tocan. Vibrance 0,08. Antes de levantar, `hqdn3d` suave elegido por ISO del SRT (<=300: 1,5:2:3:3; <=800: 2,5:3:5:5; más: 3,5:4:6:6) porque levantar sombras amplifica el ruido. |
| `day_drone` | Curva S suave (negro en 0,045, medios +0,02), vibrance 0,3, hombro de luces 1 -> 0,98 (sin blancos quemados). |
| `day_phone` | Igual pero más leve (vibrance 0,18): el teléfono ya procesa fuerte. |

Vibrance (no saturación) sube más los colores apagados que los saturados, así que protege la piel. En los perfiles de día, si el tono medio es neutro (relación R/B entre 0,90 y 1,04) se agrega un calor de 0,02 en medios; si la toma ya es cálida o azul de cielo, no se toca. Los filtros convierten a RGB con matriz bt709 explícita y vuelven a yuv420p con bt709.

### Qué elige `auto`

- **Noche** (`night`) en dron: ISO mediano del SRT >= 250, o obturador más lento que 1/200 s. En cualquier medio: hora local posterior a `grade.sunset` (19:15) y luma media < 95. Un shot de teléfono tomado de noche pero ya bien expuesto (luma >= 95) queda sin grading.
- **Día** en el resto: `day_drone` para el dron, `day_phone` para el teléfono.
- **Nitidez**: la toma se marca con zoom si el dron tiene `dzoom_ratio` > 10000 (1,0x) en >= 25 % de los cuadros usados o `focal_len` cambia; en fotos de teléfono si EXIF `DigitalZoomRatio` > 1,05 o `FocalLengthIn35mmFormat` > 30 mm. Se aplica `cas` solo si además la varianza del laplaciano (gris de 1024 px) es menor que 800 en dron o 1000 en teléfono. El video de teléfono no trae metadatos de zoom: nunca se marca solo, usá `"sharpen": true`.

Las mediciones (luma, varianza, SRT, EXIF) salen del original y quedan en `build/gprobe/`; si falta el original se avisa y el shot queda sin grading automático.

### Comparar antes y después

```
./venv/bin/python -I pipeline/gradecompare.py guion.json 86 90 15 --out build/grade
```

Por índice de shot escribe `compare-NN-<id>.jpg` (arriba cuadro completo, abajo recorte 1:1; izquierda antes, derecha después) e imprime luma media, p5/p50/p95, % de píxeles > 250 y saturación media de cada lado.

Fuentes de las prácticas: [FFmpeg filters (curves, vibrance, cas, hqdn3d)](https://ffmpeg.org/ffmpeg-filters.html), [AMD FidelityFX CAS](https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/blob/main/docs/techniques/contrast-adaptive-sharpening.md), [Mixing Light: orden de denoise y sharpen](https://mixinglight.com/color-tutorial/edge-sharpening-denoise-workflow), [dvinfo: denoise antes o después del grade](https://www.dvinfo.net/forum/archive/index.php/t-513369.html), [Adobe: corrección de color en video de viaje](https://www.adobe.com/learn/premiere-pro/web/color-correct-travel-video).

## Caché y reporte

Cada segmento se cachea por el hash de su contenido (fuente, recorte, estilo, resolución, fps, título): editar un shot recodifica solo ese shot y la parte de 4 shots que lo contiene; insertar uno no invalida los siguientes. Un ffmpeg a la vez, con `nice -n 10`. Cada segmento se verifica contra el conteo de frames esperado. Al final se imprime duración, shots, aciertos de caché por segmentos/partes/audio, tiempo por etapa, resumen del beat snap y avisos.

## Estilo (`style`)

Todas las claves tienen defecto (ver `style` en `config/defaults.yaml` y [`CONFIG.md`](CONFIG.md); `project.yaml` y el guion las pisan): `font`, `xfade`, `transition`, `photo_dur`, `card_dur`, `zoom_amt`, `focus_zoom`, `pan_zoom`, `bg_sigma`, `bg_dim`, `card_dim`, `card_color`, `aspect_tol`, `fade_in`, `fade_out`, `clip_lufs`, `clip_gain_max`, `clip_fade`, `music_lufs`, `music_tp`, `music_xfade`, `music_fade_in`, `music_fade_out`, `duck_db`, `duck_offset_db`, `snap_tolerance`.
