# ExamBase · Archivo de estudio 5.1.0

Elige un examen en el frontend de **GitHub Pages**, inicia su recopilación en **GitHub Actions** y descarga un paquete para estudiar o usar con una IA. Puedes conservar cada ejecución en el repositorio y repetir el procedimiento con otro examen sin reinstalar la herramienta.

La versión 5.1.0 añade **FlareSolverr-next**, **FlareSolverr** y **Rebrowser**, compatibilidad con un servicio propio **CloudProxy** y un workflow de diagnóstico con **Rebrowser Bot Detector**. Puedes elegir el motor en la web. Actions inicia y cierra automáticamente el contenedor de Next o FlareSolverr; mantiene una sesión durante la descarga. Consulta [MOTORES_ACCESO_5_1.md](MOTORES_ACCESO_5_1.md) para instalar la actualización, elegir el motor y retomar el parcial de tu última ejecución.

Empieza por [PUBLICAR_GITHUB_PAGES.md](PUBLICAR_GITHUB_PAGES.md). Para el motor remoto consulta [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md). [LEEME.md](LEEME.md) mantiene las instrucciones de la extensión de Edge/Chrome para uso local.

El paquete contiene `preguntas.html` con buscador y respuestas desplegables, `preguntas.md`, JSON original, JSONL para IA, imágenes, originales e informe. El modo Python incluye hashes SHA-256 y OCR opcional con Tesseract; el OCR siempre queda sin verificar. La extensión incluye JSONL y conserva las imágenes, sin ejecutar OCR dentro del navegador.

**Guardar en repositorio** crea `bancos/<examen>/<ejecución>/` con ZIP, material e informe. `bancos/index.json` alimenta el historial del frontend. La carpeta `web/` es lo único que publica el workflow de Pages. Si guardas bancos en un repositorio público, sus archivos son públicos en GitHub aunque no estén en Pages. Puedes usar un repositorio privado como motor y otro público para la interfaz.

El motor predeterminado es `flaresolverr-next`: solicita el contenido mediante su API local y usa JavaScript para abrir respuestas y capturar imágenes dentro de la sesión. `rebrowser` usa el paquete Python con parches de Playwright y Chrome con pantalla virtual en Actions. Se conservan Playwright estándar, Selenium, Beautiful Soup y HTTP. No se acumulan motores ni se cambia automáticamente de motor tras un rechazo.

El nuevo acceso todavía requiere una prueba real en tu runner: el registro `41563383011` contiene 5/103 preguntas y un rechazo real `600010` en la página 2. No demuestra que las bibliotecas nuevas lo superen. Ninguna garantiza evitar todos los bloqueos; un `status=ok` del solver tampoco basta. Se comprueban URL, página y numeración antes de aceptar contenido. Los resultados incompletos siguen generando un ZIP reanudable.

Para repetir: conecta el repositorio desde la web, elige un examen y pulsa **Preparar paquete**. Para retomar una descarga parcial indica su ID de ejecución. La herramienta comprueba que corresponda al mismo examen. Cada nueva descarga empieza una recopilación nueva salvo que pidas reanudar.

Pruebas locales: `python -m pip install -r requirements_actions.txt -r requirements_rebrowser.txt`, `python -m unittest discover -s tests -p 'test_*.py'` y `node --test tests/*.mjs`. Las pruebas no descargan exámenes del sitio. Para revisar los workflows también se necesita PyYAML.
