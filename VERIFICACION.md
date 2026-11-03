# Verificación de la entrega 5.0

El proyecto incluye una web estática para Pages y workflows de descarga, catálogo
y publicación. Los logs aportados identifican `SVN11X/extractor_exambase` y prueban
que el workflow 5.0 se ejecutó en GitHub: conservó 5/103 preguntas y un artefacto
antes del rechazo Cloudflare `600010`. El archivo **CORRECCIONES_5_0_1.md** describe
la actualización local y el parche sobre su base real. La corrección no se ha
subido ni ejecutado en el remoto desde esta entrega.

## Archivo de preguntas aportado

Se revisó `resultado_exambase(3).zip` y se generó por separado
`resultado_exambase_revisado.zip`, sin volver a recopilar el examen:

| Comprobación | Resultado |
| --- | --- |
| Preguntas y numeración | 349/349, sin duplicados ni números ausentes |
| Páginas | 70/70 |
| Claves explícitas de respuesta | 349 |
| Imágenes originales | 25/25, archivos presentes, tamaños y firmas de imagen revisados |
| Explicaciones ausentes en la fuente | 26 |
| Preguntas con metadatos de contexto pendientes de revisar | 199 capturadas desde DOM |
| Conflictos reales de contexto detectados | 0; se retiraron 19 avisos falsos por orden de propiedades tras comparar los originales |
| OCR | 13 imágenes con texto detectado; 12 sin texto detectado. Las 25 requieren revisión visual |
| Marcadores del HTML | Se recuperaron `<timestamp>`, `<sensorid>` y `<actorname>` en las preguntas 29 y 44; su formato capturado permanece señalado para revisión |
| Formato para IA | 349 líneas JSONL con identificadores estables, procedencia, referencias a contextos e imágenes |
| Integridad | CRC del ZIP y hashes SHA-256 por archivo |

Explicación ausente en preguntas: 47, 54, 69, 103, 126, 146, 166, 183, 189,
190, 217, 228, 231, 243, 256, 269, 287, 295, 296, 321, 323, 324, 325, 326,
333 y 341. No se completaron con texto inventado.

Beautiful Soup se contrastó con las 70 capturas HTML aportadas: obtuvo las mismas
349 claves de respuesta que el resultado conservado. Esto verifica la extracción
de las claves; no su corrección técnica o la vigencia del material.

## Comprobaciones del proyecto

Pasaron 63 pruebas Python y 48 JavaScript en la versión 5.0.1. Se revisó la sintaxis de los workflows
y de sus bloques Bash, y se generaron y reabrieron ZIP de prueba.

El navegador verificó búsqueda, filtros, selección por URL, rechazo de dominios
ajenos, diálogo de conexión e inspección del ZIP real: 349 preguntas, 25 imágenes,
26 explicaciones ausentes, cero imágenes faltantes y cero conflictos. Se revisó
el diseño de escritorio y la disposición a 360 píxeles de ancho.

Las llamadas a GitHub se probaron con respuestas simuladas; el token no aparece en
propiedades serializadas, URLs ni almacenamiento del navegador. No se introdujeron
credenciales reales ni se inició un workflow desde esta entrega. Selenium se
probó con el driver simulado y su parser contra los HTML reales; falta probar el
arranque y el acceso al examen en el runner concreto.

Las pruebas nuevas cubren el bloqueo de página 2 con conservación de 5 preguntas,
reanudación sintética hasta 103/103 sin volver a pedir la página 1, prioridad de
preguntas válidas frente a avisos antiguos, rechazo de scripts de otra página,
recuperación de artefactos sin GitHub CLI y diagnóstico incluido en los hashes.
Se verificó en navegador el selector de runner y sus requisitos; no se ejecutó
una descarga real en un runner propio ni se superó Cloudflare con esta entrega.

La cobertura completa no equivale a revisión académica completa. Las imágenes,
los metadatos DOM y las explicaciones ausentes permanecen señalados en el informe.
