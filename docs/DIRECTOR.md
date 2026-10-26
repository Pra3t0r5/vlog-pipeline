# Runbook del director: un video nuevo, de punta a punta

Para la sesión principal (el director). Léelo entero al empezar o al retomar; después `vlog status` dice dónde estás. Roles y regla de auditoría: `docs/ROLES.md`. Formato del guion: `docs/GUION.md`. Cómo lo vive el dueño: `docs/GUIA.md`.

## Reglas que valen en todos los pasos

1. **Solo el director habla con el dueño y decide.** Ningún subagente recibe herramientas de envío, y ningún mensaje a una persona sale sin el OK del dueño para ese mensaje.
2. **Lo que reporta un subagente es una afirmación, no una prueba.** Cada paso de abajo dice cómo verificarla con un chequeo que el subagente no escribió (el CLI revalida los archivos del triage, `vlog edl-check` revalida la EDL, `zipinfo -1` y `ls` cuentan archivos).
3. **Un subagente por tarea acotada, con la plantilla de `docs/prompts/`.** Se rellenan con datos del proyecto: `vlog prompt chronology|captions|editor|reel` y `vlog triage-plan --pass 1|2`. No se improvisa un prompt largo a mano: cada token de más se paga en cada uno.
4. **Los originales no se modifican y nada se borra sin pedirlo.** Fuentes solo lectura; `vlog clean` es simulacro por defecto.
5. **El costo es una decisión del dueño, no del director.** El modo (`cost_mode`) se pregunta en la intake y se respeta; si falta cuota, se corta en el límite de una etapa y se retoma (ver «Reanudar»).

## Modos de costo

`cost_mode: standard | low` en `project.yaml` (`vlog new <nombre> --cost-mode low`; `vlog profile` muestra el perfil vigente). Los perfiles viven en `config/defaults.yaml` (`costmode.profiles`) y los lee `pipeline/costmode.py`; un `project.yaml` puede pisar un modelo o una cantidad de rondas.

| | standard | low |
|---|---|---|
| Cronología | haiku | haiku |
| Triage pasada 1 | haiku | haiku |
| Triage pasada 2 | sonnet | sonnet |
| Código y scripts | sonnet | sonnet |
| Editor (EDL) | opus | sonnet |
| Captions | sonnet | sonnet |
| Reel | sonnet | sonnet |
| Investigación | sonnet | no |
| Hojas de contacto | standard | low |
| Rondas del editor | 2 | 1 |
| Iteraciones de preview | 2 | 1 |
| Música | search | user_or_list |
| Reel | required | optional |
| Presupuesto por ventana | sin tope | 300.000 tokens |

- **Música en standard:** un subagente Sonnet acotado busca y filtra candidatos; evitar temas con «Content ID shield» si el video va a YouTube. **En low:** el dueño trae el tema; si no tiene, se elige de `config/music_default.json` (cuatro temas de Kevin MacLeod, CC BY 4.0) y su `credit_line` va a la tarjeta de créditos. Sin búsqueda.
- **Reel en low:** solo si el dueño lo pide o `reel` está en `outputs`.
- **Captions en low:** solo `place` (de GPS, ruta y cronología); `line` queda `null`: sin subagente de investigación.

### Costo estimado por etapa (tokens)

Línea base medida en un primer viaje: unos 6 M en total, de los cuales ~3,5 M fueron construir el pipeline (una vez) y ~2–2,5 M el video: triage de 46 hojas con celdas de 256 px 0,66 M, editor Opus en 3 rondas 0,75 M, cronología con Haiku 0,27 M, reel 0,26 M, búsqueda de música 0,3 M. Lo de abajo son **estimaciones** (no mediciones) para el video siguiente: salen de esa línea base y de lo que cambia (prefiltro, hojas más baratas, triage en dos pasadas, plantillas fijas, un solo turno de lectura por subagente, editor con una o dos rondas). El triage de ese primer viaje gastó ~5,2 veces los tokens de imagen de las hojas (0,66 M sobre 127 k) por releer contexto; el contrato de las plantillas apunta a ~3 veces. Recalibrar `workflow.stage_tokens` (en `config/defaults.yaml`) con los números reales del primer video.

| Etapa | Quién | standard | low |
|---|---|---|---|
| Brief y DIRECTION.md | director | 40 k | 30 k |
| Ruta del teléfono | cli | 10 k | 8 k |
| Álbum de Google Photos | cli | 8 k | 6 k |
| Inventario y fuentes | cli | 25 k | 15 k |
| Proxies | cli | 5 k | 5 k |
| Cronología de las notas | subagente | 150 k | 100 k |
| Prefiltro sin LLM | cli | 5 k | 5 k |
| Hojas de contacto | cli | 8 k | 6 k |
| Triage pasada 1 | subagente | 220 k | 140 k |
| Triage pasada 2 | subagente | 180 k | 110 k |
| Fusión del triage y nitidez | cli | 8 k | 8 k |
| Editor | subagente | 400 k | 200 k |
| Captions y lugares | subagente | 60 k | 40 k |
| Música y créditos | director | 120 k | 15 k |
| Guion desde la EDL | cli | 20 k | 15 k |
| Preview | cli | 80 k | 50 k |
| OK del dueño al preview | dueño | 0 | 0 |
| Final y salidas | cli | 30 k | 30 k |
| Reel vertical (opcional en low) | subagente | 120 k | 80 k |
| **Total** | | **1489 k** | **783 k** |

## La secuencia

Convención: «CLI» = lo hace un comando sin LLM; «OK» = hay que mostrar algo al dueño y esperar su respuesta antes de seguir.

| # | Paso | Comando o plantilla | Modelo (standard / low) | Mostrar al dueño | Verificar |
|---|---|---|---|---|---|
| 0 | Orientarse | `vlog status` (lee/escribe `STATUS.md`) | director | — | Que el «Siguiente» coincida con lo que el dueño cree que falta |
| 1 | Intake | `vlog new <nombre> --cost-mode <modo>`; preguntar tema, duración, pantalla, quiénes, fechas del viaje (`ingest.start_date/end_date`), salidas y modo; completar `DIRECTION.md` | director | **OK:** el brief completo (actos, prioridades, prohibido, título) | `vlog status` ya no pide el brief; el espacio en disco lo revisa `vlog new` |
| 2 | Herramientas | `vlog doctor` | CLI | — | Cero «FALTA» |
| 3 | Fuentes | `vlog rutas --from … --to …`, `vlog album <zip>`, `vlog ingest`, `vlog sources build`, `vlog proxies` | CLI | Qué cable y qué zip faltan (ver `docs/GUIA.md`) | `vlog album` cuenta contra `zipinfo -1`; `vlog sources check` pasa; la SD sigue en solo lectura |
| 4 | Cronología | `vlog prompt chronology` | Haiku / Haiku | — | Un objeto por fecha del viaje, `conflicts` leídos por el director y resueltos con GPS y Rutas |
| 5 | Prefiltro | `vlog prefilter` | CLI | Una línea: tomas antes y después | `inv/prefilter.json`: suma de razones = descartadas; abrir 3 descartes por `blurry` y 3 por `variant` en `sheets` o en disco |
| 6 | Hojas | `vlog sheets` (preset del modo) | CLI | — | `sheets/manifest.json`: `total_tokens_est`, ninguna hoja sobre ~1,2 k |
| 7 | Triage, pasada 1 | `vlog triage-plan --pass 1` imprime un prompt por día; lanzar un subagente por grupo (en paralelo) | Haiku / Haiku | — | Repetir `vlog triage-plan --pass 1`: tiene que decir «nada pendiente»; contar rechazos con `jq` y mirar 3 al azar contra su hoja |
| 8 | Triage, pasada 2 | `vlog sheets --survivors`, luego `vlog triage-plan --pass 2` | Sonnet / Sonnet | — | Igual que 7; mirar la hoja de dos `keep 3` y de dos `avoid` |
| 9 | Fusión y nitidez | `vlog triage-merge && vlog sharpness` | CLI | — | `triage/merged.json` con todos los códigos; `inv/variants.json` existe |
| 10 | Editor (EDL) | `vlog prompt editor` a un subagente; después `vlog edl-check` | Opus (2 rondas) / Sonnet (1 ronda) | — | `vlog edl-check` sin errores; las excepciones de `exceptions` leídas una por una; si hay errores se devuelven literales al editor dentro de las rondas del modo, el resto se corrige a mano |
| 11 | Captions | `vlog prompt captions` a un subagente; produce `captions.json` (`place`, `line`, `confidence`, `sources`) | Sonnet / Sonnet (solo `place`) | — | Cada `line` tiene fuente; las de confianza baja se anulan |
| 12 | Música y créditos | standard: subagente de búsqueda acotado; low: el dueño o `music_default.json`. Armar `music/credits.json` y la mezcla a la duración de la EDL (`musicmix.py`) | Sonnet / ninguno | **OK:** el tema elegido (un enlace y una frase) | Licencia leída en la fuente; `credit_line` copiada tal cual a la tarjeta de créditos |
| 13 | Guion | `./venv/bin/python -I pipeline/edl2guion.py <carpeta del proyecto> --edl edl.json --out guion.json` | CLI | — | `vlog edl-check` otra vez si la EDL cambió; cantidad de shots y duración que imprime |
| 14 | Preview | `vlog preview` (hasta 2 iteraciones en standard, 1 en low) | CLI | **OK:** el archivo `<nombre>-preview.mp4` y qué mirar (orden, tomas que sobran, temblores, textos, música) | Mirar 3 cuadros (`./venv/bin/python -I pipeline/review.py guion.json <preview.mp4> build/review` arma tiras de contacto); los cambios que pide el dueño se aplican con el guion, no con otra ronda de editor |
| 15 | Aprobación | `vlog approve preview` solo después del «sí» explícito | director | — | `approvals.json` tiene la fecha |
| 16 | Final y salidas | `vlog final` y `vlog render` | CLI | El resultado y dónde está | Tamaños (`chat` ≤ 28 MB) y duración con `ffprobe` |
| 17 | Reel | `vlog prompt reel`; subagente; `vlog render reel` | Sonnet / opcional | **OK:** el reel antes de dar el trabajo por cerrado | ≤ 90 s, ids de la EDL aprobada |
| 18 | Cierre | `vlog status`, `vlog clean` (simulacro) y avisar qué se puede liberar | director | **OK:** si se borra lo regenerable | Los finales listados en `outputs` no figuran para borrar |

### Qué decide el director y qué no

- Se pregunta al dueño, no se supone: el brief, el modo de costo, la música (en low), si hay reel, cualquier corte que cambie el sentido del video.
- Si dos fuentes se contradicen en fecha o lugar: manda el GPS/hora del recurso, después `route/route.json`, por último las notas. Un conflicto que cambia el relato se muestra al dueño.
- Lo sensible (salud, plata, trabajo, momentos de cansancio o poco favorecedores) va al `avoid` de la cronología y del triage, y no se menciona en textos del video.

## Reanudar entre sesiones y ventanas de 5 horas

- Todo lo que cuesta tokens es **idempotente y por unidad**: el triage retoma por día (los grupos ya válidos no se vuelven a pedir), las hojas ya hechas se saltean, el prefiltro y las hojas son comandos sin LLM.
- `vlog status` imprime la etapa siguiente, los tokens restantes y, en low, el plan por ventanas (cada una por debajo del presupuesto de referencia de `costmode.py`; ajustarlo a la cuota real del plan). Además escribe `STATUS.md` en el proyecto.
- **Al cortar una ventana:** terminar la unidad en curso (un grupo de triage, una ronda del editor), correr `vlog status` y avisar al dueño cuánto falta. **Al abrir una sesión nueva:** leer este archivo, `DIRECTION.md` y `STATUS.md`; correr `vlog status`; no rehacer lo que figura como hecho.
- Las aprobaciones del dueño viven en `approvals.json`, no en la conversación.

## Claves de `project.yaml` que usa este flujo

```yaml
cost_mode: low
sheets: {preset: low}
ingest: {start_date: "2025-06-10", end_date: "2025-06-20"}
prefilter: {blurry_z: -1.5, variant_phash: 14, variant_seconds: 90}
people: [alice, bob]
edit: {drone_share_max: 0.45}
edl: edl.json
```

Todas salvo `cost_mode` tienen valor por defecto. `ingest.start_date/end_date` (o `rutas`, o `trip: {from, to}`) activan el descarte fuera de fechas.

## Lo medido en un viaje de referencia

Prefiltro sobre las 1101 tomas de `inv/media.json` de ese viaje: 855 sobreviven (screenshot 34, fuera de fecha 1, duplicado 65, ráfaga 36, borrosa 78, variante 32). De las 110 tomas del montaje final, el prefiltro habría descartado 2, ambas variantes de nitidez casi empatada; ninguna borrosa. Hojas sobre esos 855 sobrevivientes, contra 127 522 tokens de las 46 hojas originales (965 tomas, celdas de 256 px): standard 67 hojas, ~68,6 k tokens (−46 %, máx. 1189 por hoja); low 46 hojas, ~43,0 k tokens (−66 %, máx. 1075 por hoja).
