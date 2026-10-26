# Reel vertical (Sonnet): el corte resumen de 9:16

El reel es un guion aparte (`guion-reel.json`, hasta 90 s) que sale de la EDL ya aprobada; no es una segunda edición desde cero. Se imprime rellena con `vlog prompt reel`. En modo low es opcional: solo si el dueño lo pide o `reel` figura en `outputs`.

Parámetros: `{{project}}`, `{{title}}`, `{{edl}}`, `{{guion_reel}}`, `{{max_s}}`, `{{brief}}`, `{{media}}`, `{{triage}}`, `{{sharpness}}`, `{{music_policy}}`.

Reglas del director:
- Se lanza después del OK del dueño al preview del video principal, con modelo Sonnet.
- Verificar: duración <= 90 s (el render la rechaza si pasa), todos los ids existentes y ninguna toma que la EDL principal descartó. Si el encuadre vertical tapa algo importante, se corrige con `focus_x` por toma, no rehaciendo el reel.
- La música del reel va aparte (`shortmix.py` acorta un tema a la duración exacta).

=== PROMPT ===
Armá el reel vertical de «{{title}}» (Instagram, 1080x1920) a partir de la EDL aprobada {{edl}}. Escribí {{guion_reel}}. Leé el brief ({{brief}}) solo para el tono y lo prohibido.

Reglas:
1. Duración total entre 60 y {{max_s}} s, contando fundidos. Ritmo rápido: planos de 1,5 a 3 s (el dron hasta 4).
2. Usá SOLO tomas que ya están en la EDL principal; elegí lo mejor: `keep 3` primero, después `keep 2` de tomas con personas, y un puñado de planos de dron como paisaje.
3. Orden: gancho en los primeros 2 s (la toma más fuerte), luego un recorrido por los actos en orden cronológico y un cierre emotivo. Sin tarjetas de acto; un solo título corto arriba.
4. Los medios apaisados se recortan a 9:16 alrededor de `focus_x` (0 a 1, defecto 0,5). Para tomas con la persona o el punto de interés descentrado, indicá `focus_x` leyendo `desc` del triage.
5. Fotos verticales (3:4) se componen sobre su fondo desenfocado; no las recortes.
6. Sin captions de dato, solo el lugar en las tomas que cambian de sitio. Sin audio de clip salvo una risa o voz corta que sume.
7. No uses tomas `blurry` ni `avoid`.

Formato: el mismo guion que {{project}}/guion.json (`docs/GUION.md`): `{"name", "project": ".", "inventory": "inv/media.json", "proxy_dir": "proxy", "out_dir": "build", "output": {"fps": "30000/1001"}, "style": {...}, "music": [], "shots": [{"id", "in", "out", "dur", "focus_x", "title", "caption", "transition"}]}`. Solo JSON válido en {{guion_reel}}.

Tu respuesta final es 3 líneas: duración total, cantidad de planos y cuáles llevan `focus_x`.
