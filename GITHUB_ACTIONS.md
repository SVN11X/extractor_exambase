# Ejecutar el extractor en GitHub Actions

El flujo está preparado en `.github/workflows/descargar-examen.yml`. Se ejecuta
en un servidor de GitHub; tu PC puede estar apagado después de iniciarlo.
Puedes usarlo desde el frontend de Pages siguiendo [PUBLICAR_GITHUB_PAGES.md](PUBLICAR_GITHUB_PAGES.md).

## Qué está preparado y qué falta comprobar

Puedes elegir un examen, detectar su total de preguntas y páginas, recopilarlo,
descargar imágenes, generar un ZIP y conservar resultados parciales. El flujo
incluye reanudación desde el artefacto de una ejecución anterior del mismo examen.

El flujo no se ha subido ni ejecutado en tu cuenta. Las pruebas locales utilizan
archivos aportados y páginas simuladas; no demuestran que ExamBase acepte al
servidor de GitHub.

**La limitación de Cloudflare sigue existiendo.** El servidor no tiene la sesión
de tu Edge. El modo browser usa Chromium estándar de Playwright, sin técnicas de
camuflaje ni resolución de CAPTCHAs. Si aparece una verificación que no termina,
guarda lo recuperado y termina con estado parcial. No habrá una ventana que puedas
verificar desde el formulario de Actions. Para un funcionamiento fiable cuando el
sitio bloquea a los servidores, el dueño tendría que ofrecer una exportación/API
o habilitar acceso automatizado.

Cloudflare documenta esos límites aquí:
<https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/>.

## Preparar el repositorio

1. Crea un repositorio vacío en GitHub. Puede ser privado para controlar quién
   accede al código y a los resultados. Su cuota de Actions dependerá de tu plan.
2. Descomprime el paquete y entra en la carpeta **extractor_exambase**. Deben quedar
   `descargar.py`, `catalogo.json` y `.github` en la raíz del repositorio, no dentro
   de otra carpeta adicional.
3. Sube el contenido de esa carpeta, incluida `.github`. Desde Git Bash dentro
   de ella, para un repositorio nuevo y vacío:

```bash
git init
git add .
git commit -m "Añadir extractor ExamBase con selección de examen"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
git push -u origin main
```

Sustituye `TU_USUARIO/TU_REPOSITORIO` por tu repositorio. Las carpetas temporales
de salida están en `.gitignore`. El workflow puede guardar los paquetes finales
en `bancos/` cuando activas `save_to_repo`.

## Elegir y ejecutar

1. Abre el repositorio → **Actions** → **Descargar examen de ExamBase** → **Run workflow**.
2. En **exam**, elige uno de los tres ejemplos verificados o **personalizado**.
3. Si elegiste personalizado, pega la URL del examen en **exam_url**. Admite la
   portada del examen o una página de preguntas. No pegues el índice general ni
   el índice de un proveedor.
4. En **mode**, elige:
   - `http`: descarga HTML con Python; sólo sirve si el sitio entrega las preguntas
     sin una verificación que necesite JavaScript.
   - `browser`: abre Chromium en el servidor, espera a que cargue el contenido y
     utiliza los controles normales de mostrar respuestas. También puede ser bloqueado.
   - `selenium`: usa Chrome estándar con Selenium Manager para elegir el driver y
     Beautiful Soup para leer el DOM. Las mismas limitaciones de verificación aplican.
5. Deja **page_limit = 0** para todas las páginas. El delay admite de 5 a 120 segundos.
6. Pulsa **Run workflow**. Puedes cerrar tu navegador.
7. Al terminar, abre la ejecución y descarga **exambase-resultado** en **Artifacts**.
   Dentro está el ZIP del examen y `estado_ejecucion.json`.
8. Activa **save_to_repo** si quieres guardar cada ejecución en Git. El workflow
   conserva ZIP, HTML, Markdown, JSONL, imágenes y originales en una carpeta por
   examen y ejecución. Si el repositorio es público, esos bancos serán públicos.

El menú de Actions tiene tres ejemplos y un campo URL. El frontend de Pages
incluye buscador, proveedor, URL personalizada, historial y revisión local del ZIP;
su catálogo se actualiza con el workflow `actualizar-catalogo.yml`. El catálogo
inicial es parcial y no pretende contener los 1.657 exámenes anunciados.

Un resultado completo puede tener explicaciones ausentes en la fuente o imágenes
pendientes de transcribir. Consulta el informe; las claves no se corrigen ni se
inventan explicaciones. El código de salida 2 significa cobertura parcial, bloqueo
o presupuesto de tiempo agotado; el artefacto se conserva aunque la ejecución
aparezca en rojo, siempre que el programa haya podido crear el resultado.

## Reanudar una descarga parcial

Cada ejecución tiene un límite de trabajo de 300 minutos para dejar margen a la
creación y subida del ZIP. El flujo completo tiene un límite de 330 minutos.

1. Copia el número de la URL de la ejecución anterior: el número situado después
   de `/actions/runs/`.
2. Inicia otro **Run workflow** con el **mismo examen**.
3. Introduce ese número en **resume_run_id**.

El flujo recupera el artefacto, valida que sea del mismo examen y reutiliza las
páginas e imágenes que ya están guardadas. Los artefactos de este flujo se
conservan durante siete días; si venció, se intenta la copia de `bancos/` cuando
habías activado el guardado en repositorio.
Si la ejecución anterior no consiguió siquiera detectar el examen y guardó cero
preguntas, vuelve a empezar dejando `resume_run_id` vacío.

No se guardan ni se transfieren cookies o perfiles del navegador. No debes copiar
tu perfil de Edge ni subir credenciales al repositorio. El token automático de
GitHub se usa para recuperar artefactos y, si lo eliges, escribir los bancos.
La protección de rama o una política de organización puede impedir ese commit;
el artefacto se sube antes del guardado para conservar el resultado en ese caso.

## Ejecución por terminal

```bash
python descargar.py --exam-url "https://www.exambase.com/exams/google/associate-data-practitioner" --mode http --output salida --delay 10
```

Para modo browser instala primero las dependencias:

```bash
python -m pip install -r requirements_actions.txt
python -m playwright install chromium
python descargar.py --exam-url "https://www.exambase.com/exams/google/associate-data-practitioner" --mode browser --output salida --delay 10
```

En Linux, Playwright puede necesitar sus dependencias de sistema. El workflow las
instala con `python -m playwright install --with-deps chromium`.

Para Selenium cambia `--mode browser` por `--mode selenium`; necesita Chrome
disponible o descargable mediante Selenium Manager. `--ocr` usa Tesseract si está
instalado; se marca toda transcripción como automática y sin verificar. Puedes
enriquecer un resultado anterior sin volver a descargar preguntas:

```bash
python paquetes.py --input resultado_anterior.zip --output resultado_revisado --ocr
```

Documentación: <https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow>,
<https://cli.github.com/manual/gh_run_download> y
<https://playwright.dev/python/docs/ci-intro>.
