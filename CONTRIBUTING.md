# Contribuir

Gracias por querer sumar. El proyecto es chico y prefiere cambios acotados.

## Antes de empezar

1. Armá el entorno: `python3 -m venv venv && venv/bin/pip install -r requirements.txt`, y tené `ffmpeg` y `exiftool` en el `PATH`. `bin/vlog doctor` dice qué falta.
2. Corré los tests: `venv/bin/python -I -m unittest discover -s tests`. Deben pasar antes y después de tu cambio. Los tests usan carpetas temporales y datos inventados; no necesitan material propio.

## Reglas del código

- Nada de comentarios dentro del código. El porqué de un cambio va en el mensaje del commit, en la descripción del pull request o en `docs/ARCHITECTURE.md`. Lo único admitido son docstrings de tipos y las directivas de herramientas.
- Todo valor que un usuario pueda querer cambiar (rutas, tipografías, umbrales, nombres de modelo, listas) va en `config/defaults.yaml` y se documenta en `docs/CONFIG.md`. Un test verifica que cada clave esté documentada.
- No agregues datos personales a código, tests, ejemplos ni documentación: nombres, rutas absolutas, coordenadas de lugares privados, mails. Los tests y los ejemplos usan datos ficticios.
- Una etapa nueva del CLI tiene que ser idempotente (rehacerla no rompe nada) y reanudable (lo ya hecho se saltea).
- Si cambia el costo en tokens de una etapa, actualizá `workflow.stage_tokens` y las tablas de `docs/DIRECTOR.md` (un test compara ambas).

## Pull requests

- Un cambio por pull request, con una descripción que diga qué problema resuelve y cómo lo probaste.
- Si tocás el render, comprobá que los hashes de caché de un guion existente no cambien, a menos que el cambio sea justamente visual. Un cambio de caché que no es visual obliga a todos los usuarios a re-renderizar.
- Mensajes de commit en imperativo y sin firmas de herramientas.

## Licencia

Al contribuir aceptás que tu aporte se publique bajo la licencia MIT del repositorio.
