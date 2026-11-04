# Cambios 6.0.0

Base Git: `7b235082726f155665c126e2fc7523f4dfa15429`.

- Scrapling como único motor para exámenes y catálogo. Se retiran solvers, Selenium, Rebrowser y las rutas de descarga HTTP de los puntos de entrada. Beautiful Soup permanece como parser, Patchright como dependencia del navegador de Scrapling.
- Tres tareas con un campo cada una: actualizar examen, extraer proveedor y actualizar catálogo. Ejecución programada y cola persistente con límites y renovación por antigüedad.
- Una carpeta `bancos/<proveedor>/<examen>` con resultado vigente y un solo avance si la actualización quedó incompleta. Consolidación de las cinco versiones anteriores en tres exámenes.
- Se conservan los ZIP de lectura y JSONL para IA; se retiran web, extensión y publicación Pages.
- Alerta de Defender: se revisó el `lector.js` y los HTML señalados del ZIP almacenado de Professional Data Engineer. El lector sólo filtraba texto e imprimía; los HTML incluían arranque de Svelte, Google Analytics y Cloudflare Insights. La captura no muestra el nombre de la detección y no se dispone aquí de un análisis de Defender que confirme un falso positivo. El nuevo lector es estático y los HTML de origen se conservan como valores JSON con su hash original. No se pretende certificar ausencia de malware ni desactivar el antivirus.

La auditoría del banco migrado comprueba contenido y hashes de imágenes frente a los ZIP anteriores. Professional Data Engineer conserva 349 preguntas, 349 respuestas y 25 imágenes; Associate Cloud Engineer conserva 349 preguntas, 349 respuestas y 8 imágenes. Associate Data Practitioner conserva 103 preguntas, 103 respuestas y 9 imágenes y sigue parcial por 15 preguntas con metadatos pendientes. No se inventan explicaciones ni se declara completo ese banco.

La programación y el acceso real desde GitHub Actions requieren ejecutar los workflows tras aplicar la actualización. Las pruebas locales usan datos sintéticos y los bancos ya descargados.
