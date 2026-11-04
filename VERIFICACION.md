# Verificación de la entrega 5.2.4

## Comprobaciones de 5.2.4

Pasaron 106 pruebas Python y 52 JavaScript. El resumen real del workflow se
ejecutó con resultados completos, parciales y bloqueados. Un resultado completo
con revisión pendiente muestra 8/8 imágenes guardadas y el ZIP preparado. El
caso parcial conserva sus instrucciones de reanudación.

El ZIP real de `41843218758` se comprobó con el inspector de Pages y se volvió
a procesar localmente desde el respaldo. Ambas comprobaciones conservaron
349 respuestas y 8/8 imágenes presentes. El estado registra 27 explicaciones
ausentes y mantiene la revisión de contenido pendiente. Se verificó que sus
campos de explicación están vacíos en las capturas estructuradas.

La nueva presentación del resumen de Actions queda por comprobar en la próxima
ejecución publicada.

## Comprobaciones de 5.2.3

Pasaron 106 pruebas Python y 52 JavaScript. La regresión nueva comprueba que una
página visible se guarda antes de releerla y que un resultado estructurado posterior
recupera identificadores y un caso de estudio conservando las claves anteriores.
También comprueba el límite de dos lecturas y la parada ante una comprobación de
acceso pendiente, incluso con respuestas visibles completas.

La reproducción local con el ZIP real de `41825863020` conservó las 349 preguntas,
las 349 respuestas y las imágenes. Al reproducir las mismas capturas incompletas,
el proceso mantuvo las 115 preguntas con metadatos pendientes y terminó como parcial.
La recuperación desde el sitio con esta versión queda por comprobar en Actions.

## Comprobaciones de 5.2.2

Pasaron 105 pruebas Python y 52 JavaScript. La prueba de reanudación carga un
ZIP con respuestas completas y metadatos pendientes en una página. Una respuesta
de navegación simulada entrega un caso de estudio en un fragmento diferido.
El extractor solicita sólo la página pendiente, descarta respuestas ajenas y
conserva las claves del respaldo junto a los identificadores y al objeto recuperado.

El log de `41749148063` confirma las 103 preguntas y sus 103 respuestas. El
artefacto requiere autenticación. La recuperación de los metadatos de las páginas
2, 11 y 20 queda por confirmar con 5.2.2 en GitHub Actions.

## Comprobaciones de 5.2.1

Pasaron 102 pruebas Python y 52 JavaScript. Las pruebas reproducen el cambio de
documento durante la comprobación, una comprobación que sigue pendiente y la
reanudación con 103 preguntas, 68 respuestas y un contexto compartido. El estado
marca las siete páginas pendientes y la primera es la 2. Otra prueba confirma
que una respuesta recuperada del DOM se guarda junto al contexto estructurado
del respaldo. La ejecución de ExamBase queda por comprobar en GitHub Actions.

## Comprobaciones nuevas de 5.2.0

Pasaron 100 pruebas Python y 52 JavaScript. Cubren respuestas que llegan tarde,
tarjetas sustituidas por la SPA, respuestas ausentes pese a contar todas las
preguntas, conservación de todo el respaldo tras un bloqueo y reparación por
página. Se comprueba que texto de una alternativa no se confunda con una marca
de respuesta correcta y que no se mezclen claves contradictorias.

Se instaló Scrapling 0.5 y se probaron su integración y cierre mediante una sesión
simulada: captura de API, metadatos, objetos hermanos y ausencia de cabeceras
privadas en la exportación. Se validan identificadores, referencias inversas,
objetos tipados, referencias desconocidas y el grafo de IA. Un DOM sin metadatos
suficientes queda parcial incluso con todas las preguntas y claves.

La API pública de GitHub confirmó el estado exitoso de `41619720711` y la existencia
del artefacto; su ZIP requiere autenticación y no se pudo auditar. No se ejecutó
una nueva descarga en tu cuenta ni se superó un desafío real. La prueba de carga
de archivo en el navegador de revisión agotó el tiempo de espera; el nuevo
contador se verificó mediante pruebas de modelo, y su revisión visual queda pendiente.

Base del parche: `5490b4d7169c4f5d74b8fdf8ed222a7c55c9fe4d`. La entrega incluye
el repositorio completo, sus bancos existentes y un parche comprobado con `git am`.

El proyecto incluye una web estática para Pages y workflows de descarga, catálogo,
diagnóstico y publicación. El último log aportado, ejecución `41563383011`, prueba
que la recuperación y el guardado en `bancos/` funcionaron: quedaron 5/103 preguntas
y un rechazo real Cloudflare `600010` en la página 2. La actualización 5.1.0 añade
FlareSolverr-next, FlareSolverr, Rebrowser y compatibilidad CloudProxy. Consulta
**MOTORES_ACCESO_5_1.md**. No se ha subido ni ejecutado en el remoto desde esta entrega.

## Comprobaciones nuevas de 5.1.0

Pasaron 83 pruebas Python y 49 JavaScript. Las nuevas pruebas recorren la API v1
mediante un servidor HTTP local, sesiones, captura posterior al JavaScript,
imágenes en caché de navegador y generación del ZIP para persona e IA. Verifican
que HTTP 200 y `status=ok` no acepten un desafío como preguntas, que un rechazo
600010 quede registrado y que las cookies de prueba no aparezcan en las salidas.
Se comprueban el cierre y la propiedad del contenedor mediante comandos simulados,
incluido un fallo al publicar el puerto, y el diagnóstico vacío falla explícitamente.

Se revisó en navegador real la selección del examen, los motores y sus ayudas,
el requisito de conexión para abrir el diagnóstico y el campo de reanudación. Se
comprobó la disposición sin desbordamiento horizontal en marcos de 360 y 768 px,
y el cambio de motor y runner en la vista de 360 px, además del escritorio.

Rebrowser se instaló e importó con su versión fijada. En este entorno no hay
Docker ni Chrome local: el contenedor, Chrome con Xvfb, el detector público y la
descarga real de ExamBase siguen pendientes de prueba en el runner. Las pruebas
locales no demuestran que se haya superado Cloudflare. El parche se entrega sobre
la base real `bc65e69174ce8583b225111958fdc4a6dea4c2d1` y se comprueba con `git am`.

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

## Comprobaciones conservadas de las versiones anteriores

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
