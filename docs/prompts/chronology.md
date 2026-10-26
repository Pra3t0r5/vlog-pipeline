# Cronología (Haiku): de las notas a notes/chronology.json

Extracción mecánica por fecha, sin juicio de edición. Se imprime ya rellena con `vlog prompt chronology`.

Parámetros: `{{project}}`, `{{from}}`, `{{to}}`, `{{notes_files}}`, `{{out_file}}`.

Reglas del director:
- Un solo subagente Haiku. Para bajar tokens, en `notes/` dejar solo lo que corresponde al viaje (las notas diarias de esas fechas y los documentos extra); el plan lista los archivos y su tamaño.
- Verificar: contar los días del archivo contra el rango de fechas, y abrir una fecha al azar contra su nota. Los `conflicts` se leen enteros: son lo que el director resuelve con el GPS y Rutas, no el subagente.
- La cronología es contexto para el triage y el editor, no verdad de fecha: manda el GPS/hora del recurso, después `route/route.json`, por último las notas.

=== PROMPT ===
Extraé una cronología del viaje a partir de las notas. Es una tarea mecánica: copiá y ordená lo que dicen las notas, sin inventar ni interpretar.

Viaje: del {{from}} al {{to}}. Archivos a leer (leelos todos en un único turno, en paralelo):
{{notes_files}}

Escribí con la herramienta Write un único archivo JSON en {{out_file}} con esta forma exacta:
{
 "days": [
  {"date": "AAAA-MM-DD", "weekday": "lun", "base": "dónde se durmió",
   "places": ["lugares visitados"], "meals": [{"what": "comida", "where": "lugar"}],
   "architecture": ["iglesias, edificios, plazas mencionados"],
   "milestones": ["hechos importantes del día"],
   "family_moments_happy": ["momentos felices o divertidos con las personas"],
   "avoid": ["lo que NO debe mostrarse: momentos de cansancio, salud, trabajo, temas privados"],
   "quotes": ["frases textuales de las notas, máx. 3"],
   "source": ["archivo.md"]}
 ],
 "conflicts": [{"what": "qué dos fuentes se contradicen y cómo", "sources": ["archivo1", "archivo2"]}]
}

Reglas:
- Un objeto por fecha del rango, en orden. Si una fecha no tiene notas, igual va, con listas vacías.
- Cada dato sale de una nota; nombrá el archivo en `source`. No agregues datos que no estén.
- Si dos notas fechan distinto un mismo hecho (por ejemplo un cuaderno corrido un día), no elijas: anotalo en `conflicts` con los archivos.
- En `avoid` va todo lo sensible o privado (salud, plata, trabajo, discusiones, momentos de cansancio o poco favorecedores), aunque la nota lo cuente como anécdota. En duda, va a `avoid`.
- Nada de juicios ni sugerencias de edición.

Tu respuesta final es UNA línea: "N días, M conflictos".
