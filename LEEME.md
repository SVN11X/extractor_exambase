# Extractor ExamBase · versión 5

Elige el examen en el frontend de GitHub Pages, en la extensión o directamente en GitHub Actions. Lee **PUBLICAR_GITHUB_PAGES.md** para publicar el selector y conservar cada descarga en el repositorio. Los totales de preguntas y páginas se detectan para cada examen.

## Elegir examen en Edge o Chrome

1. Abre **ExamBase — recopilador de estudio**.
2. Elige **Proveedor** → **Ver exámenes**. La página del proveedor se abre para recuperar su lista. Vuelve al panel y selecciona el examen en la lista.
3. También puedes pegar la URL del examen o de una página de sus preguntas. **Usar pestaña abierta** toma el enlace de un examen que tengas abierto.
4. Pulsa **Seleccionar examen** y después **Iniciar / reanudar**.

Cada examen guarda por separado sus preguntas, imágenes y progreso. Para cambiar mientras hay un recorrido activo, pulsa **Pausar** primero. El banco anterior permanece guardado y puedes volver a seleccionarlo para continuar o exportarlo.

El catálogo adjunto contenía 192 proveedores y anunciaba 1.657 exámenes. Esta versión incluye los proveedores y tres ejemplos; las listas completas de cada proveedor se obtienen cuando pulsas **Ver exámenes**. El nombre comercial del grupo puede diferir del segmento de su URL: Google Cloud usa enlaces `/exams/google/...`, por ejemplo. Se conservan los enlaces reales del catálogo.

Admite rutas de examen de `exambase.com` y los siete sitios de exámenes destacados con URL explícita en el HTML adjunto. Un sitio externo necesita que concedas el permiso que te solicite la extensión; la detección depende de que conserve el formato de página compatible. No se afirma que se hayan probado en vivo los 1.657 exámenes ni todos los sitios destacados.

## Actualizar conservando las 349 preguntas que ya descargaste

1. Pausa el recorrido anterior y cierra sus paneles.
2. Copia los archivos nuevos de `extension_navegador` dentro de la **misma carpeta extension_navegador que ya cargaste**, reemplazándolos y conservando la ruta.
3. En `edge://extensions`, pulsa **Recargar**, la flecha circular, en la tarjeta del recopilador. Mantén la extensión instalada.
4. Abre su panel. El banco anterior de Professional Data Engineer conserva sus claves originales y debe seguir apareciendo con sus 349 preguntas. Elegir otro examen no las reemplaza.

## Primera instalación

En `edge://extensions` o `chrome://extensions`, activa **Modo de desarrollador** → **Cargar descomprimida** → carpeta `extension_navegador`, que contiene `manifest.json`. Luego abre la extensión desde su icono. Se requiere Chromium 120 o posterior.

## Ejecución sin estar presente

La extensión conserva las mejoras de la versión 3.2: proceso de fondo, alarmas, reintentos de pestañas temporalmente ocupadas, checkpoints, prevención opcional de suspensión automática y descarga del ZIP sin mantener abierto el panel. Deja el navegador y el equipo encendidos. Una verificación con un fallo explícito o que no llegue a mostrar las preguntas sigue pudiendo requerir atención personal.

Para ejecutar en un servidor sin tu PC, sigue **GITHUB_ACTIONS.md**. Los logs aportados muestran una ejecución real con rechazo Cloudflare `600010` tras 5/103 preguntas. Las correcciones 5.0.1 todavía deben aplicarse al remoto; consulta **CORRECCIONES_5_0_1.md**. Si el sitio rechaza el acceso, se guarda un parcial. También puedes configurar un runner propio con navegador visible, que requiere dejar el equipo encendido; tampoco garantiza superar una verificación.

## Resultado

Cada resultado contiene preguntas, alternativas, claves explícitas, explicaciones, formatos especiales, contextos, imágenes originales e informe de validación. La extensión conserva los originales, una versión legible en HTML y Markdown, y `para_ia/` con JSONL y una guía. Las imágenes se colocan junto al campo al que pertenecen. Los ZIP de exámenes nuevos llevan un nombre derivado del examen; el banco original mantiene `resultado_exambase.zip`.

La transcripción de imágenes y revisión de diagramas queda pendiente. No se inventan explicaciones que la fuente no incluya. La cobertura de páginas completa se distingue de la revisión de todo el contenido.

## Contenido del paquete y validación

- `extension_navegador/`: selector y recopilador en tu navegador habitual.
- `.github/workflows/descargar-examen.yml`: ejecución manual por selección o URL y reanudación desde artefactos.
- `descargar.py`: versión por terminal para ejecución desatendida HTTP, Playwright o Selenium.
- `web/`: frontend estático listo para GitHub Pages.
- `paquetes.py`: lector con buscador, datos para IA, hashes y OCR opcional.
- `persistir_banco.py`: guardado de versiones por examen y ejecución.
- `catalogo.json`: proveedores y datos del catálogo aportado.
- `GITHUB_ACTIONS.md`: instrucciones de configuración, ejecución y límites.
- Herramientas anteriores y muestra: se conservan por compatibilidad; la muestra contiene sólo cinco preguntas.

Se verificaron 48 pruebas JavaScript y 63 pruebas Python, además de la sintaxis YAML/Bash de los workflows. Incluyen separación de exámenes, conservación del progreso, reanudación de parciales, diagnóstico de acceso, recuperación sin GitHub CLI, guardado de versiones, JSONL, hashes, API simulada e integridad de ZIP. Se probó anteriormente el ZIP real de 349 preguntas en el inspector; sus pendientes se detallan en **VERIFICACION.md**. La reanudación hasta 103/103 se verificó con datos sintéticos y no demuestra superar Cloudflare en el sitio.
