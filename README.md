# ExamBase · bancos de estudio 6.0.1

Recopilación mediante **Scrapling** y GitHub Actions. Cada examen tiene una carpeta vigente en `bancos/<proveedor>/<examen>/`. Se conservan preguntas, respuestas explícitas, imágenes, casos, escenarios y sus referencias, con validación de cobertura y hashes. La ejecución informa los pendientes reales.

En GitHub abre **Actions** y elige una tarea:

| Tarea | Campo que debes rellenar | Comportamiento |
| --- | --- | --- |
| Actualizar un examen | URL del examen | Inicia una actualización nueva si el banco está completo; recupera el avance si existe un parcial. |
| Extraer exámenes por proveedor | Slug, por ejemplo `google-cloud` | Descubre su catálogo y procesa un lote de exámenes nuevos, incompletos o pendientes de renovación. |
| Actualizar catálogo de proveedores | Slug o `all` | Actualiza los enlaces de un proveedor; `all` atiende el siguiente del turno. |

Descarga **exambase-resultado** en los artefactos de la ejecución o el `resultado.zip` del examen en [bancos](bancos). Abre `preguntas.html` para estudiar y `para_ia/LEEME_IA.md` para entregar el material a una IA. El lector es estático, sin JavaScript; usa Ctrl+F para buscar. Las capturas HTML de origen se conservan dentro de JSON como datos.

## Ejecución automática

La tarea por proveedor se programa diariamente a las **03:17, America/Santiago**. Recorre los proveedores por turnos, con hasta **10 exámenes y 240 minutos por lote**, y hasta **60 minutos de recopilación por examen**. Un lote pendiente continúa en otra ejecución. Las copias completas se renuevan cada 30 días; los parciales esperan al menos un día. Un rechazo de acceso detiene el lote y aplaza ese proveedor siete días. La actualización individual manual permite revisarlo antes.

El catálogo se revisa al atender un proveedor si lleva siete días sin actualizarse. Hay además una tarea semanal los lunes a las **02:17** para el siguiente índice. `automatizacion/config.json` permite cambiar proveedores y límites sin añadir campos a los formularios. `proveedores: ["all"]` recorre todos; `["google-cloud"]` limita el trabajo a ese proveedor; `["google-cloud", "all"]` lo coloca primero.

La programación empieza cuando estos archivos están en la rama predeterminada con Actions habilitado. GitHub puede retrasar ejecuciones programadas y desactivarlas por inactividad del repositorio. Cada trabajo necesita permisos de escritura de contenido para guardar bancos y avance. Consulta [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md).

## Banco vigente y recuperación

- `resultado.zip`: última copia completa disponible o mejor parcial cuando aún no existe una completa.
- `estado_ejecucion.json`, `informe_validacion.json`, `manifest_guardado.json`: estado, validación, origen y SHA-256 del ZIP vigente.
- `progreso.zip` y `progreso_estado.json`: un único avance de la actualización en curso cuando existe una copia anterior más completa. Al completarse, reemplaza el resultado y se retira ese avance.
- `bancos/index.json`: índice de exámenes, esquema 2.0. El ID de Actions es metadato, no parte de la ruta.

La migración consolida las carpetas antiguas por ejecución y conserva la mejor copia de cada examen. El historial anterior queda en Git. Los bancos existentes se reempaquetaron sin cambiar preguntas, respuestas, objetos ni hashes de imágenes. Un proveedor puede tener un alias de catálogo (`google-cloud`) y rutas de examen `google/...`; se conserva la identidad real de la URL para evitar duplicados.

## Validación y límites

La numeración global se vincula con el orden interno por tema usando el contenido visible; se conserva ese orden de origen en los datos para IA. Al reanudar, se intentan recuperar primero los metadatos desde las capturas guardadas. Si el respaldo queda completo, se regenera sin consultar el sitio. Si cambian los totales durante una reanudación, se conserva el respaldo y se realiza un único reinicio desde cero para evitar mezclar generaciones. Se comprueban identidad del examen, paginación, numeración continua, respuestas explícitas, referencias a objetos y archivos, descarga de imágenes y conservación de bytes. Una captura con preguntas completas pero metadatos pendientes se presenta como parcial. Una explicación vacía y una imagen descargada pendiente de revisión se informan por separado. OCR y respuestas de la fuente requieren revisión académica.

Scrapling es el único motor de acceso. Su navegador usa Patchright y el análisis HTML usa Beautiful Soup; son dependencias de la misma extracción. Se retiraron los motores alternativos, la extensión y GitHub Pages. Un desafío que requiera intervención puede impedir una ejecución desatendida; se guarda el parcial y el diagnóstico. No se garantiza que todos los proveedores permitan automatización.

Los ZIP de estudio ya no distribuyen `lector.js` ni capturas HTML ejecutables. Esto reduce código innecesario en la descarga; **no certifica un veredicto de antivirus**. Si Defender sigue alertando, conserva la cuarentena y solicita un análisis de los archivos específicos a [Microsoft Security Intelligence](https://www.microsoft.com/en-us/wdsi/filesubmission/). El nombre exacto de la detección y la versión de las definiciones ayudan a investigar.

Los bancos son visibles si el repositorio es público. Mantén únicamente contenido cuya descarga y redistribución tengas autorizadas. El Git guarda versiones históricas de los ZIP aunque el árbol actual tenga una sola ruta por examen.

## Desarrollo

Python 3.12. Instala `requirements_actions.txt`, `requirements_scrapling.txt` y `requirements_dev.txt`. Las pruebas no descargan exámenes: `python -m unittest discover -s tests -p 'test_*.py'` y `node --test tests/test_capture_script.mjs`. `extractor.py --input` conserva el conversor de muestras locales; la recopilación de red se ejecuta desde Actions.

Consulta [CORRECCIONES_6_0_1.md](CORRECCIONES_6_0_1.md) para el diagnóstico de los logs y los dos bancos reparados sin solicitudes nuevas.
