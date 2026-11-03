# ExamBase · Archivo de estudio 5.0.1

Elige un examen en el frontend de **GitHub Pages**, inicia su recopilación en **GitHub Actions** y descarga un paquete para estudiar o usar con una IA. Puedes conservar cada ejecución en el repositorio y repetir el procedimiento con otro examen sin reinstalar la herramienta.

La versión 5.0.1 corrige la detección de páginas que conservan scripts o avisos anteriores, añade diagnósticos de acceso y permite elegir un runner propio con navegador visible. El error Cloudflare `600010` observado en el registro de GitHub sigue siendo un rechazo de acceso del sitio: no se presenta como una descarga completa ni se reintenta automáticamente. Consulta [CORRECCIONES_5_0_1.md](CORRECCIONES_5_0_1.md) para aplicar el parche y reanudar.

Empieza por [PUBLICAR_GITHUB_PAGES.md](PUBLICAR_GITHUB_PAGES.md). Para el motor remoto consulta [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md). [LEEME.md](LEEME.md) mantiene las instrucciones de la extensión de Edge/Chrome para uso local.

El paquete contiene `preguntas.html` con buscador y respuestas desplegables, `preguntas.md`, JSON original, JSONL para IA, imágenes, originales e informe. El modo Python incluye hashes SHA-256 y OCR opcional con Tesseract; el OCR siempre queda sin verificar. La extensión incluye JSONL y conserva las imágenes, sin ejecutar OCR dentro del navegador.

**Guardar en repositorio** crea `bancos/<examen>/<ejecución>/` con ZIP, material e informe. `bancos/index.json` alimenta el historial del frontend. La carpeta `web/` es lo único que publica el workflow de Pages. Si guardas bancos en un repositorio público, sus archivos son públicos en GitHub aunque no estén en Pages. Puedes usar un repositorio privado como motor y otro público para la interfaz.

Motores incluidos: Playwright, Selenium estándar con Selenium Manager y lectura del DOM con Beautiful Soup; también HTTP para páginas entregadas como HTML. Mantienen sesiones durante una ejecución, respetan las pausas y guardan avances. GitHub no hereda tu sesión local. Un desafío interactivo puede impedir una descarga desatendida: se conserva un ZIP parcial. Estos motores no resuelven CAPTCHAs ni garantizan superar Cloudflare.

Para repetir: conecta el repositorio desde la web, elige un examen y pulsa **Preparar paquete**. Para retomar una descarga parcial indica su ID de ejecución. La herramienta comprueba que corresponda al mismo examen. Cada nueva descarga empieza una recopilación nueva salvo que pidas reanudar.

Pruebas locales: `python -m pip install -r requirements_actions.txt`, `python -m unittest discover -s tests -p 'test_*.py'` y `node --test tests/*.mjs`. Las pruebas no descargan exámenes del sitio.
