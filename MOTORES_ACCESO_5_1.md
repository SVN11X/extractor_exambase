# Motores de acceso · versión 5.1.0

Esta actualización incorpora los proyectos solicitados al flujo de descarga.
El motor se elige en Pages → **Opciones de descarga** o en Actions → **mode**.
La web sigue siendo estática: el navegador y el servicio se ejecutan en el runner.

## Qué se incorporó

| Proyecto solicitado | Uso en el extractor | Preparación en Actions |
| --- | --- | --- |
| [rix1337/flaresolverr-next](https://github.com/rix1337/flaresolverr-next) | Motor `flaresolverr-next`, predeterminado. API v1 y `executeJs` para abrir respuestas y capturar HTML e imágenes en la misma sesión. | Descarga e inicia `ghcr.io/rix1337/flaresolverr-next:latest` con Docker. |
| [FlareSolverr/FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) | Motor `flaresolverr`, compatible con la API clásica. HTML y descarga de imágenes con su User-Agent y cookies en memoria. | Inicia `ghcr.io/flaresolverr/flaresolverr:latest`. No ofrece `executeJs`. |
| [NoahCardoza/CloudProxy](https://github.com/NoahCardoza/CloudProxy) | Motor `cloudproxy`, API v1, sesiones y `download:true` para imágenes. | Sólo una instancia existente en un runner propio. No se instala su pila antigua Node 15/Puppeteer 3. |
| [rebrowser/rebrowser-patches](https://github.com/rebrowser/rebrowser-patches) | Motor `rebrowser` mediante el paquete Python oficial del proyecto, `rebrowser-playwright==1.64.102`. Conserva Playwright estándar como opción separada. | Instala Chrome estable y utiliza un navegador con pantalla virtual Xvfb en Linux. |
| [rebrowser/rebrowser-bot-detector](https://github.com/rebrowser/rebrowser-bot-detector) | Workflow `diagnosticar-navegador.yml` y programa `diagnosticar_navegador.py`. Guarda las señales observadas como JSON. | Se inicia por separado; no prueba acceso a ExamBase ni garantiza que Cloudflare acepte el navegador. |

Cada ejecución crea una sesión propia del solver, la reutiliza para las páginas y
la destruye al salir. No reutiliza sesiones entre ejecuciones ni importa tu perfil
de Edge. El servicio sólo se publica en `127.0.0.1`; no se abre un proxy en Internet.
El contenedor se identifica con una etiqueta propia y sólo se elimina si coincide
su propietario. CloudProxy externo permanece encendido.

Next devuelve el HTML después de ejecutar los controles de respuestas; el campo
`solution.response` anterior al JavaScript no se confunde con esa captura. Se
comprueban URL, número de página, preguntas y totales. Un `status=ok` o HTTP 200 del
solver no convierte un desafío o una página anterior en una descarga válida.

Las imágenes devueltas por Next se reutilizan sin volver a pedirlas. Una imagen
rechazada dentro de la sesión se registra como tal. Los recursos externos al
origen del examen quedan pendientes de revisión. El motor clásico puede dejar
pendientes respuestas dinámicas; el informe las conserva como ausentes.

## Aplicar la actualización al repositorio existente

Base real del parche: `bc65e69174ce8583b225111958fdc4a6dea4c2d1`, commit de
`SVN11X/extractor_exambase` que guarda el resultado de la ejecución `41563383011`.
El ZIP completo conserva ese banco y el resto de archivos del repositorio.

Con un clon limpio situado en esa base, ejecuta desde Git Bash:

```bash
git switch -c motores-5-1 bc65e69174ce8583b225111958fdc4a6dea4c2d1
git am /ruta/Extractor_ExamBase_Windows.patch
```

Revisa los cambios y súbelos a tu rama de publicación con tu procedimiento habitual.
Si tu rama ya tiene cambios posteriores, aplica el parche en una rama y resuelve
los conflictos allí. El ZIP contiene una carpeta `extractor_exambase/`; para una
instalación nueva usa su contenido como raíz, incluida `.github/`.

## Retomar tu descarga

Una vez actualizados los workflows y Pages:

1. Selecciona **Google Associate Data Practitioner** o pega su URL.
2. En **Opciones de descarga**, selecciona `FlareSolverr-next`.
3. En **Dónde ejecutar**, deja **Servidor de GitHub**.
4. En **ID de una ejecución para reanudar**, introduce **41563383011**.
5. Activa **Guardar también en el repositorio** si deseas otra versión del banco.
6. Pulsa **Preparar paquete**. Puedes cerrar Pages y apagar tu ordenador.

También puedes iniciar **Descargar examen de ExamBase** directamente desde Actions:
`mode=flaresolverr-next`, `runner=github`, `resume_run_id=41563383011`,
`page_limit=0`. El respaldo guardado contiene cinco preguntas; se reanuda en la
página 2. Otro examen debe iniciarse sin ese ID.

Si Next no funciona en el runner, una ejecución independiente puede seleccionar
`rebrowser`. No se encadenan automáticamente motores ni sesiones tras un rechazo.
Con un rechazo final se conserva el parcial y el código, y el trabajo termina con
salida 2. La pausa sigue admitiendo entre 5 y 120 segundos.

Los resultados conservan el lector HTML, Markdown, `preguntas.json`,
`para_ia/preguntas.jsonl`, imágenes, originales, informe y hashes. No se inventan
respuestas o explicaciones para completar el informe.

## Usar un solver desde tu terminal

Requiere Python 3.11+, dependencias de `requirements_actions.txt` y Docker iniciado.
El servicio utiliza la API local `http://127.0.0.1:8191/v1`.

```bash
python -m pip install -r requirements_actions.txt
python solver_service.py start --engine flaresolverr-next --state-file salida/solver_runtime.json
python descargar.py --exam-url "https://www.exambase.com/exams/google/associate-data-practitioner" --mode flaresolverr-next --delay 10 --output salida
python solver_service.py stop --state-file salida/solver_runtime.json
```

Ejecuta el cierre aunque la descarga termine con salida 2. El workflow lo hace en
un paso `always()`. Para otra descarga usa una carpeta de salida nueva. El digest
real de la imagen descargada queda en `solver_runtime.json`, junto al artefacto;
las imágenes `latest` pueden cambiar. No se montan perfiles o carpetas del host.

Para el motor clásico sustituye `flaresolverr-next` por `flaresolverr` en ambos
comandos. Para una instancia ya iniciada usa `solver_service.py start --external`;
el extractor admite `--solver-url http://127.0.0.1:PUERTO/v1`. El endpoint debe ser
local. El workflow usa el puerto 8191.

CloudProxy exige su servicio local ya preparado: selecciona `cloudproxy` y un
runner propio con etiqueta `exambase`. No se instala Docker/CloudProxy antiguo, no
se configura un servicio de CAPTCHA de pago y no se cierra un servicio ajeno.

## Usar Rebrowser desde tu terminal

```bash
python -m pip install -r requirements_actions.txt -r requirements_rebrowser.txt
python -m rebrowser_playwright install chrome
python descargar.py --exam-url "https://www.exambase.com/exams/google/associate-data-practitioner" --mode rebrowser --headed --delay 10 --output salida_rebrowser
```

En Linux sin pantalla, instala Xvfb y xauth, prepara Chrome con
`python -m rebrowser_playwright install --with-deps chrome` y ejecuta el último
comando con el prefijo `xvfb-run -a`. En un runner propio con pantalla, la sesión
gráfica debe estar disponible para el usuario que ejecuta el servicio de Actions.

## Diagnóstico y alcance de las comprobaciones

En Pages → **Opciones de descarga** → **Diagnosticar el navegador**, abre el
workflow en GitHub y pulsa **Run workflow**. Admite `rebrowser`, `browser` o
`flaresolverr-next`. Descarga el artefacto `exambase-diagnostico` para ver las
señales del detector público. No activa artificialmente todos sus tests; conserva
las señales y sus valoraciones originales. Un detector sin resultados es un fallo
de diagnóstico, no una prueba superada.

Se probaron la API v1 con un servidor HTTP local, sesiones, cierre, HTML posterior
al JavaScript, imágenes, rechazo 600010 con HTTP 200 y creación del ZIP para persona
e IA. Cookies de prueba no aparecen en el ZIP ni en la salida. El arranque de
Docker se comprobó con simulaciones de sus comandos y de propiedad del contenedor.
Se importó el paquete Rebrowser fijado. No hay Docker ni un navegador Chrome local
en el entorno de desarrollo: falta comprobar el arranque real de los contenedores,
el detector público y el acceso a ExamBase en el runner. No se inició una ejecución
remota ni se acredita haber superado su protección.

El fork Next consultado fija una versión de Chromium en su imagen; su compatibilidad
con los desafíos del sitio puede cambiar. Ninguno de estos proyectos garantiza
ausencia de detección o elimina bloqueos asociados a la red de un servidor.

Fuentes de implementación consultadas en GitHub, con sus commits de referencia:

| Proyecto | Commit consultado |
| --- | --- |
| flaresolverr-next | `84a5e210aa559a2a11278b22686a0bb7ec14faf4` |
| FlareSolverr | `cc2224b21e31c09a713eb25690a8e8dcdf50d8d8` |
| CloudProxy | `d827a95897d5eab880f81581ec9b81d4db8a10aa` |
| rebrowser-patches | `31b51356499600f71126aae532f3d57abdc92272` |
| rebrowser-bot-detector | `55fa59b9da0610563d896aa956f145ef00431a6b` |
