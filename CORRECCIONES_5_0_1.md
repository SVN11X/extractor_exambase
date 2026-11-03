# Correcciones 5.0.1

Base real: `SVN11X/extractor_exambase`, rama `main`, commit
`a3842cc294dac1449408d3fa73bb55f211d8998f`, el mismo que figura en los logs aportados.

## Lo que demuestra el registro

La ejecución `41558984612` seleccionó **Associate Data Practitioner**, con
Selenium, y guardó 5/103 preguntas de la página 1/21. Después recibió
`Verificación rechazada: 600010`. El programa terminó con código 2 y Actions
subió correctamente el artefacto `exambase-resultado`, de 754.281 bytes. No se
observan fallos de instalación ni de subida del ZIP. El guardado en Git no se
activó en esa ejecución; el artefacto es el respaldo disponible.

Cloudflare agrupa `600*` como fallos del desafío. El registro no permite determinar
por sí solo si lo causaron el navegador, la sesión, la red o una regla del sitio.
No se afirma que cambiar una librería resuelva ese rechazo.

## Qué se corrige

- Se comprueba primero si hay preguntas válidas de la página solicitada. Un aviso
  antiguo ya no impide capturar preguntas disponibles.
- Si una SPA conserva el script de la página anterior, se comprueba el DOM actual;
  nunca se acepta la página 1 como página 2.
- `estado_ejecucion.json` e `diagnostico_acceso.json` distinguen `blocked`,
  `partial`, `failed` y `complete`, con código, página, páginas guardadas y próxima
  página pendiente. El diagnóstico forma parte de los hashes del ZIP.
- El resumen y la anotación de Actions explican el rechazo y muestran el ID para
  reanudar. Se mantiene la salida 2 en una descarga parcial; no se oculta el fallo.
- La recuperación del artefacto usa Python y ya no depende de tener `gh`
  instalado. La URL temporal de descarga no recibe el token de GitHub.
- El historial de bancos muestra el rechazo y permite seleccionar el examen y
  su respaldo al reanudar.
- Se puede elegir `github` o `self-hosted`. Este último necesita un runner propio
  con etiqueta `exambase` y sesión gráfica abierta; los motores usan navegador
  visible. No incluye técnicas de camuflaje ni resolución automática del desafío.

Los logs no incluyen el HTML del rechazo. La prioridad del DOM corrige un caso
reproducido en pruebas, pero no se atribuye ese caso al rechazo concreto del log.

## Aplicar al repositorio

Con el árbol de trabajo limpio, desde tu checkout:

```bash
git switch main
git pull --ff-only
git am /ruta/Extractor_ExamBase_Windows.patch
git push
```

El parche se valida sobre el commit base indicado. Si tienes cambios locales,
consérvalos antes de aplicarlo. El ZIP completo contiene una instantánea de los
archivos corregidos. Esta entrega no se ha subido automáticamente a tu remoto.

## Reanudar la ejecución del registro

En Actions elige **Descargar examen de ExamBase**:

| Campo | Valor |
| --- | --- |
| `exam` | `google-associate-data-practitioner` |
| `mode` | `selenium` |
| `resume_run_id` | `41558984612` |
| `runner` | `github`, o `self-hosted` después de configurarlo |
| `save_to_repo` | Activar si deseas conservar la versión en Git; será pública si el repositorio es público |

Se recuperan las cinco preguntas ya guardadas y la siguiente página pendiente
es la 2. Con el mismo cliente, Cloudflare puede volver a rechazar el acceso.
Si caduca el artefacto y no había una copia en Git, necesitarás el ZIP que hayas
descargado; por terminal puedes usar `--resume-from /ruta/resultado.zip`.

## Runner propio con navegador visible

1. En **Settings → Actions → Runners → New self-hosted runner**, sigue los
   comandos que GitHub genere para tu sistema. Añade la etiqueta **exambase**.
2. En Windows instala Git for Windows para disponer de Bash, Chrome y Python
   compatibles. Para navegador visible, inicia el runner con `run.cmd` dentro de
   tu sesión de escritorio, en lugar de ejecutarlo como servicio sin escritorio.
   En Linux necesitas sesión gráfica y dependencias del navegador.
3. Deja el equipo encendido y la sesión abierta. En el frontend elige **Equipo
   con runner propio**, o `runner=self-hosted` en Actions. Si el runner no está
   conectado, el trabajo quedará en cola.
4. Instala Tesseract en ese equipo si deseas OCR; el workflow sólo instala los
   paquetes del sistema automáticamente en el runner Linux de GitHub.

Un runner ejecuta código del repositorio en tu equipo: úsalo sólo con workflows
de confianza. Elegir un equipo propio cambia dónde se ejecuta el trabajo; no
garantiza que el sitio acepte una sesión automatizada. Para garantizar una
recopilación desatendida se necesita acceso habilitado por el propietario, una
API o una exportación.

Fuentes oficiales: [códigos de Turnstile](https://developers.cloudflare.com/turnstile/troubleshooting/client-side-errors/error-codes/),
[runners propios](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners),
[etiquetas de runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow).

## Validación

Las pruebas reproducen con datos sintéticos el caso de 5/103 preguntas bloqueado
en la página 2 y su reanudación hasta 103/103, sin volver a pedir la página 1.
Cubren también avisos antiguos, scripts de otra página, hashes, ZIP de Actions,
recuperación sin `gh` y separación del token frente a la URL temporal. No son
una prueba de superar Cloudflare en ExamBase ni una ejecución en tu runner propio.
