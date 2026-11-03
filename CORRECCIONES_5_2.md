# Captura y diagnóstico · versión 5.2.0

Base real: `5490b4d7169c4f5d74b8fdf8ed222a7c55c9fe4d`, la actualización 5.1
publicada en `SVN11X/extractor_exambase`. Se conservan sus motores y bancos.

## Qué se pudo comprobar de tu ejecución

La API pública de GitHub identifica la ejecución `41619720711`, trabajo
`125862077527`, como exitosa. El solver se inició, el recopilador terminó y se
publicó el artefacto `exambase-resultado` (`13222473989`). El guardado en el
repositorio estuvo desactivado. La descarga anónima del artefacto devuelve 401 y
la descarga de los logs devuelve 403; no se pudo examinar el ZIP de esa ejecución
ni determinar exactamente qué preguntas/respuestas faltaron.

La revisión del código sí demuestra tres fallos que podían explicar resultados
incompletos o un estado verde engañoso:

- La finalización comprobaba el número de preguntas, pero no exigía respuestas.
- Se pulsaban todos los botones de respuesta casi simultáneamente y se esperaba
  un segundo fijo. Una actualización de la página podía sustituir los botones.
- Los datos estructurados iniciales tenían prioridad aunque el DOM posterior
  contuviera claves y explicaciones nuevas. Además, reanudar reutilizaba esas
  capturas incompletas sin intentar repararlas.

## Correcciones

Se incorpora **Scrapling 0.5** como motor `scrapling`, basado en la API del proyecto
oficial [D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling), commit consultado
`95cf9019ab5a5d6f3e9654b7ef1c6a26e29dc5c0`. Se instala con su extra `fetchers` y
utiliza `StealthySession`, registro de API y un solo intento de petición por página.
La sesión habilita el mecanismo de Cloudflare de la biblioteca, sin rotación de
proxies ni cambio automático a otros motores. No se ha probado contra ExamBase
desde esta entrega y no garantiza superar sus controles.

La captura compartida por Next, Playwright/Rebrowser y Selenium espera tarjetas,
pulsa un control **Reveal Answer** a la vez y comprueba que aparezca una marca
explícita. Vuelve a buscar la tarjeta después de cada actualización de la web.
La espera tiene límites; una respuesta que no llega queda pendiente. No pulsa
controles de verificación de acceso.

Se conservan metadatos estructurados, identificadores y contextos, y se añaden
claves/explicaciones del DOM sólo si coinciden número, enunciado, alternativas e
imágenes. Claves contradictorias se señalan como error, sin elegir una al azar.
Se reconocen marcas explícitas `Correct`, `Correct Answer` y atributos semánticos
de corrección. La palabra «Correct» dentro del texto de una alternativa no es
una clave. Las explicaciones no se usan para adivinar respuestas.

El estado, el informe y el resumen de Actions incorporan `answers_present`,
`answers_missing`, `answers_complete`, `pages_pending_answers` y
`pages_pending_images`. No se devuelve éxito con claves ausentes, enunciados o
alternativas vacíos, imágenes fallidas o conflictos. Una respuesta expresada
como imagen se conserva como tal y requiere revisión visual.

El lector HTML, Markdown y el inspector de Pages muestran el número de respuestas
conservadas. La cobertura numérica y la revisión académica siguen separadas.
Las explicaciones que no entrega la fuente permanecen señaladas, sin inventarlas.

## Objetos referenciados

Se conservan objetos recibidos junto a los datos de preguntas, en campos hermanos
de la API o embebidos: temas, series, casos de estudio, contextos, escenarios,
anexos y otros objetos con tipo e identificador. No se descartan sus imágenes o
campos originales. Los identificadores coincidentes permiten enlazarlos a las
preguntas; las relaciones inversas `question_id` y `question_ids` también se validan.
Referencias de tipo desconocido se dejan pendientes, sin asignar un objeto al azar.

`para_ia/referencias.json` contiene nodos, enlaces, referencias sin resolver,
archivos externos declarados que aún no se han descargado y preguntas cuyos
metadatos no se pudieron verificar. `contextos.json` conserva el contenido de los
objetos; el JSONL enlaza sus identificadores. Un DOM con preguntas y respuestas
puede seguir incompleto si faltan sus metadatos. Estos casos devuelven salida 2,
igual que una referencia rota o un archivo requerido pendiente.

## Detección de acceso

El diagnóstico separa rechazo de verificación, desafío pendiente, denegación con
evidencia de Cloudflare, límite HTTP 429, HTTP 401/403 sin evidencia de antibot,
autenticación y tiempo agotado del solver. Los avisos ocultos no bastan para
clasificar una página como bloqueo. Si hay preguntas pero un desafío impide sus
respuestas, se conservan las preguntas antes de detener el trabajo.

No se cambia automáticamente de motor, red o sesión después de un rechazo.
Ninguna librería garantiza superar la protección. Esta actualización mejora la
captura, la clasificación y la conservación del avance; no acredita una descarga
real completa del examen.

## Aplicar y reanudar

Con el repositorio limpio y actualizado en la rama correspondiente:

```powershell
git pull --rebase origin main
git am "$env:USERPROFILE\Downloads\Extractor_ExamBase_Windows.patch"
git push origin main
```

El parche corresponde a la base indicada arriba. Si hay conflictos de Git,
revísalos antes de continuar; no vuelvas a aplicar el parche 5.1 anterior.

En Pages o Actions selecciona **el mismo examen** de la ejecución anterior y:

| Opción | Valor |
| --- | --- |
| Motor | `scrapling` para capturar también la API, o `flaresolverr-next` |
| Runner | `github` |
| ID para reanudar | `41619720711` |
| Límite de páginas | `0` |
| Guardar también en el repositorio | Activado si quieres conservar el banco |

El avance se carga completo antes de reparar páginas. Se conservan las capturas
anteriores en `paginas_originales/previas/` cuando se reemplaza su HTML. Si una
página vuelve a bloquearse, las páginas posteriores del respaldo siguen en el
nuevo ZIP. Las páginas con preguntas y respuestas válidas no se solicitan de nuevo.
El artefacto anterior está disponible hasta su fecha de caducidad en GitHub.

Para usar Scrapling por terminal:

```powershell
python -m pip install -r requirements_actions.txt -r requirements_scrapling.txt
python -m patchright install chromium
python descargar.py --exam-url "URL_DEL_MISMO_EXAMEN" --mode scrapling --headed --resume-from resultado_anterior.zip --output salida_nueva
```

En Actions se prepara el navegador automáticamente y se utiliza Xvfb en el runner
de GitHub. No hace falta dejar abierto tu equipo. La operación se conserva como
parcial si el sitio no entrega contenido suficiente.

Para una auditoría exacta del resultado anterior se necesita su ZIP descargado
desde Actions, especialmente `informe_validacion.json`, `preguntas.json`, capturas
y HTML original. No envíes tokens ni perfiles del navegador.
