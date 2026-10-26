# Guía de uso: cómo hacer un video de viaje

Vos ponés el tema y los recursos. Quien dirige el flujo (una sesión de Claude Code, ver [`ROLES.md`](ROLES.md)) hace el resto y te muestra un preview para que mires. Todos los comandos también se pueden correr a mano.

## Antes de empezar (checklist)

1. **Tema y brief.** Una frase de qué querés contar, para quién es, cuánto debería durar y en qué pantalla se va a ver. Claude te lo pregunta con `vlog new <nombre>`.
2. **Tarjeta SD del dron.** Ponela en la Mac y revisá que aparezca montada en Finder, con la carpeta `DCIM`. Si no aparece, sacala y volvé a ponerla. No hace falta copiar nada: el pipeline la lee sin modificarla.
3. **Google Photos.** Entrá al álbum del viaje, tocá los tres puntos, "Descargar todo", y guardá el `.zip` en Descargas. Decile a Claude dónde quedó. El zip no se borra solo. No lo descomprimas con doble clic (rompe los acentos): lo hace `vlog album`.
4. **Rutas de Google Maps (Android).** Se exporta con `vlog rutas --from AAAA-MM-DD --to AAAA-MM-DD`. Antes, en el teléfono Android:
   - Ajustes > Acerca del teléfono > Información de software, tocá 7 veces "Número de compilación".
   - Ajustes > Opciones de desarrollador > activá "Depuración por USB".
   - Conectá el cable a la Mac, desbloqueá el teléfono y aceptá "¿Permitir depuración USB?".
   - Dejá el teléfono desbloqueado y no toques la pantalla mientras corre. El script solo toca "Exportar datos de Rutas" y se frena solo si ve algo raro; nunca toca "Borrar datos de Rutas". Esos textos son los del teléfono en español: con otro idioma o versión, ajustá `adb.entry_label`, `adb.export_label` y `adb.forbidden_words` (ver [`CONFIG.md`](CONFIG.md)). Si el teléfono pide confirmar el guardado, confirmalo vos.
   - Si no podés usar cable: exportá a mano y pasale el archivo con `--file`.
5. **Notas.** Tus notas de esas fechas (archivos de texto o Markdown, uno por día o uno por viaje): copialas a la carpeta `notes/` del proyecto. Las lee solo; si tenés notas en papel o documentos extra, pasale la ruta o una foto.
6. **Música.** Bajala vos de una fuente con licencia clara (por ejemplo Pixabay Music o Incompetech) y leé la licencia vigente en la página del tema. Evitá los temas con "Content ID shield" o "protección Content ID" si vas a subir el video a YouTube. Dejá los archivos en la carpeta `music/` del proyecto.

## Qué hace Claude, etapa por etapa

| Etapa | Comando | Qué pasa |
|---|---|---|
| Armar el proyecto | `vlog new` | Pregunta, crea la carpeta y chequea que haya lugar (el doble del tamaño de las fuentes). |
| Revisar herramientas | `vlog doctor` | Chequea ffmpeg (filtros y encoders), exiftool, las dependencias de Python, la tipografía y, como opcionales, adb y los datos de mapas. |
| Ruta del teléfono | `vlog rutas` | Exporta, baja y procesa el recorrido. |
| Álbum | `vlog album` | Descomprime en `originales/` (fuera del proyecto) y verifica que no falte ningún archivo. |
| Inventario | `vlog ingest` | Lista todo el material con fecha y GPS y lo agrupa por lugar y momento. |
| Fuentes | `vlog sources` | Indexa y verifica los originales (ver abajo). |
| Proxies | `vlog proxies` | Versiones livianas del dron para trabajar rápido. |
| Prefiltro | `vlog prefilter` | Sin IA: descarta lo borroso, ráfagas, duplicados, capturas de pantalla y lo que cae fuera de las fechas del viaje, y escribe por qué en `inv/prefilter.json`. |
| Contactos | `vlog sheets` | Hojas de miniaturas, solo de lo que sobrevivió, con el tamaño del modo de costo. |
| Triage | (Claude) | Dos pasadas: una barata marca los descartes obvios y otra califica lo que queda. |
| Selección y guion | (Claude) | Elige las mejores tomas y escribe la lista de cortes según el brief. |
| Preview | `vlog preview` | Video de baja resolución para que lo mires. |
| Final | `vlog final` | Render en la resolución final, solo cuando aprobaste el preview. |
| Salidas | `vlog render` | Produce las versiones que el proyecto declara en `outputs:` (`tv` 4K, `celu` 1080p, `chat` hasta 28 MB, `reel` vertical de hasta 90 s para Instagram con su propio guion). |
| Liberar espacio | `vlog clean` | Lista y borra lo regenerable; nunca toca originales ni videos finales. |

`vlog status` dice en qué etapa va, cuál sigue y cuántos tokens falta gastar, y deja el resumen en `STATUS.md` para retomar desde otra sesión. Todo se puede repetir: lo que ya está hecho se saltea.

## Modo de costo

Al crear el proyecto elegís `standard` (≈1,5 M de tokens por video, con el editor más fuerte y búsqueda de música) o `low` (≈0,8 M, pensado para un plan de entrada: hojas más chicas, editor Sonnet en una ronda, sin búsqueda de música —traés vos el tema o se elige de una lista corta— y reel opcional). En `low` el trabajo se parte en ventanas de 5 horas y se retoma donde quedó. Son estimaciones, no mediciones. Detalle y tabla completa: [`DIRECTOR.md`](DIRECTOR.md).

## Dónde vive cada cosa (regla de almacenamiento)

El proyecto **indexa** los archivos que usa; no los copia ni los mueve. Los originales se leen siempre de donde están y nunca se modifican. Dentro de la carpeta del proyecto solo se guardan cosas editadas o derivadas.

- **Originales (fuera del proyecto):** tarjeta SD del dron (solo lectura), álbum de Google Photos descomprimido en `<disco>/originales/AAAA-MM <nombre del álbum>/` (carpeta configurable con `storage.originals_dir` en `project.yaml`), y las exportaciones del teléfono. La excepción es `route/Rutas.json`: se queda en el proyecto porque la exportación del teléfono es efímera.
- **Derivados (dentro del proyecto):** `build/` (caché de segmentos, previews, finales), `proxy/`, `sheets/`, `inv/`, `guion.json`, `DIRECTION.md`.
- **`sources.json`:** manifiesto del proyecto. Lista cada raíz (tipo `drone_sd`, `album`, `phone_export`, `notes`, `doc`, `music`; ruta absoluta; UUID del volumen) y, por cada archivo usado, `size`, `mtime` y un `quick_hash` (SHA-1 del primer y último MiB). `media.json` y el guion siguen funcionando con rutas absolutas: se resuelven a través de la raíz.

| Comando | Qué hace |
|---|---|
| `vlog sources build` | Arma o actualiza `sources.json` desde `media.json`, ruta, notas y música. |
| `vlog sources list` | Raíces, cantidad de archivos y si están alcanzables. |
| `vlog sources check [--deep]` | Solo lectura. Dice qué archivos faltan (por ejemplo, SD sin montar) o cambiaron. `--deep` también compara el `quick_hash`. |
| `vlog sources relink <raíz> <ruta-nueva>` | Re-apunta una raíz que cambió de lugar (el álbum movido, otra letra de volumen). No toca archivos. Se niega si la ruta nueva no tiene los archivos (`--force` lo fuerza). |
| `vlog sources add <tipo> <ruta>` | Registra a mano una carpeta o archivo como fuente. |
| `vlog clean` | Simulacro por defecto: tabla de derivados por clase (`segcache`, `proxies`, `sheets`, `review`, `previews`) con su tamaño. Los videos listados en `outputs` de `project.yaml` (finales) se conservan siempre. |
| `vlog clean --apply --drop segcache,proxies` | Borra solo las clases pedidas (`--keep` excluye). Nunca toca raíces de fuentes. |

**Mover el álbum:** `mv` en el mismo volumen (instantáneo) y después `vlog sources relink album <carpeta nueva>`. **Borrar el zip de Descargas:** recién cuando `vlog sources check` pasa y `vlog album` confirma que la cantidad de archivos coincide; el comando nunca lo borra por su cuenta.

## Mapita, textos de lugar y versión vertical

- **Minimapa:** en la esquina de arriba a la derecha aparece un círculo con el recorrido y el lugar y la fecha de esa toma. Hace falta `vlog fetch-data` una vez (mapas de Natural Earth) y, para ver calles de un pueblo, `vlog osm`. Se prende en `project.yaml` (`minimap: {enabled: true}`); si una toma no lo quiere, pedí "sin minimapa en esa".
- **Textos de lugar:** abajo a la izquierda, un renglón con el lugar y otro, más tenue, con un dato (se pide por toma: "poné el lugar en la toma de la iglesia"). No salen en tomas de menos de 2,5 s ni mientras está el título.
- **Versión para Instagram:** Claude arma un guion aparte (hasta 90 s). Las tomas horizontales se recortan a vertical; si el recorte tapa algo importante, decí hacia dónde correr el encuadre ("en la toma del dron, más a la izquierda").
- **Versiones del video:** `tv` para el televisor, `celu` para el teléfono, `chat` para mandar por WhatsApp (menos de 28 MB).

## Qué revisás vos y cómo pedir cambios

Mirá el preview en la Mac (el archivo `<nombre>-preview.mp4` en la carpeta del proyecto). Fijate: orden de los lugares, tomas que sobran o faltan, temblores, textos, música. Pedí los cambios con tiempos y palabras simples: "sacá la toma de los 2:10", "más gente y menos paisaje en el pueblo", "la música muy fuerte en la parte de la comida". Quien dirige toca la lista de cortes y vuelve a renderizar solo lo que cambió.

## Tiempos medidos en una máquina de referencia

- Inventario: 17 segundos para 160 tomas del dron (Apple Silicon).
- Proxies del dron: más o menos 0,4 veces el tiempo real (10 minutos de dron tardan unos 4 minutos).
- Preview: unos 8 segundos al volver a renderizar, gracias al caché, cuando cambia poco.
