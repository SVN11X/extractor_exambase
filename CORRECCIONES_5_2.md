# Captura y diagnóstico · versión 5.2.4

El parche 5.2.4 se aplica sobre `13db896a7dc3a704fa207f55c35bdb84c2eb990c`
de `SVN11X/extractor_exambase`.

## Estado de imágenes y revisión del contenido

El resultado de `41843218758` conserva 349 preguntas y respuestas, 8 imágenes
descargadas y todos los metadatos. Se comprobaron los ocho archivos y sus hashes.
Las 27 explicaciones señaladas tienen el campo `solution_text` vacío en sus
capturas estructuradas.

La versión 5.2.4 muestra las imágenes guardadas y pendientes en el estado, el
diagnóstico y el resumen de Actions. Cuando la recopilación está completa, el
resumen presenta el ZIP como listo para descargar. El aviso de revisión visual
describe la comprobación del contenido y del OCR. Las explicaciones vacías se
enumeran como contenido ausente en el paquete.

El inspector de Pages cuenta los archivos presentes dentro del ZIP y detecta
también las imágenes que carecen de una ruta local. Al cargar sólo un JSON,
solicita el ZIP para comprobar los archivos asociados.

## Recuperación automática de metadatos

El ZIP de `41825863020` conserva 349 preguntas y respuestas de **Google Associate
Cloud Engineer**. En 23 páginas el HTML inicial contiene `captcha_required` y las
preguntas visibles se conservaron desde el DOM, con identificadores por verificar.

La versión 5.2.3 guarda primero la captura visible y realiza una segunda lectura
de esa página antes de avanzar. Usa la misma sesión y el intervalo configurado.
Los identificadores y vínculos se toman del resultado estructurado recibido y se
combinan con las respuestas ya guardadas cuando el contenido coincide.

Se realiza como máximo una segunda lectura por página y ejecución. Una comprobación
de acceso pendiente detiene el proceso aunque las respuestas visibles estén completas.
Si la segunda lectura entrega sólo DOM, se conserva el parcial y sus metadatos se
mantienen pendientes de verificación. `pages_retried_for_metadata` registra qué
páginas recibieron esta segunda lectura.

## Qué se pudo comprobar de tu ejecución

La ejecución `41749148063` recuperó las 35 respuestas pendientes de **Google
Associate Data Practitioner**. Guardó 103/103 preguntas, 103/103 respuestas y
un objeto. El log identifica 15 preguntas con metadatos por verificar en las
páginas 2, 11 y 20 y registra cero referencias sin resolver. El ZIP de esa
ejecución permite reparar esas páginas conservando sus respuestas.

El log de `41743648444` registra 103 preguntas, 68 respuestas y un objeto
conservado de **Google Associate Data Practitioner**. Quedan 35 respuestas y
metadatos por verificar en las páginas 2, 5, 8, 11, 14, 17 y 20. No se detectaron
referencias rotas. Scrapling se detuvo al desaparecer el marco de Turnstile
mientras intentaba pulsar la casilla de verificación.

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
La versión 5.2.1 desactiva el clic de verificación de la biblioteca. Si detecta
una comprobación pendiente, espera hasta 20 segundos en la misma pestaña. Si el
sitio abre la página durante ese tiempo, captura sus preguntas y respuestas. Si
la comprobación sigue pendiente, registra el estado y conserva el ZIP parcial.

La versión 5.2.2 lee el HTML recibido para la página actual, las respuestas JSON
de navegación y acciones, y los fragmentos diferidos de SvelteKit. Usa sólo las
respuestas que la pestaña ya recibió. La validación comprueba página, numeración
y totales antes de usar un resultado estructurado. La compatibilidad con el
protocolo se comprobó con el [código oficial de SvelteKit](https://github.com/sveltejs/kit/blob/fe4deb1b76d876bdca56db489388c98ed74973f5/packages/kit/src/runtime/server/data/index.js).

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
revísalos antes de continuar.

En Pages o Actions selecciona **el mismo examen** de la ejecución anterior y:

| Opción | Valor |
| --- | --- |
| Examen | Google Associate Cloud Engineer |
| Motor | `scrapling` |
| Runner | `github` |
| ID para reanudar | `41843218758` |
| Límite de páginas | `0` |
| Guardar también en el repositorio | Activado si quieres conservar el banco |

El avance se carga completo antes de reparar páginas. Se conservan las capturas
anteriores en `paginas_originales/previas/` cuando se reemplaza su HTML. Si una
página vuelve a bloquearse, las páginas posteriores del respaldo siguen en el
nuevo ZIP. Las páginas con contenido y referencias completos se reutilizan.
El artefacto anterior está disponible hasta su fecha de caducidad en GitHub.

Para usar Scrapling por terminal:

```powershell
python -m pip install -r requirements_actions.txt -r requirements_scrapling.txt
python -m patchright install chromium
python descargar.py --exam-url "URL_DEL_MISMO_EXAMEN" --mode scrapling --headed --verification-wait 180 --resume-from resultado_anterior.zip --output salida_nueva
```

En Actions el navegador se ejecuta en el servidor de GitHub. Si el sitio exige
interacción, descarga el ZIP parcial y usa el comando local. La opción
`--verification-wait 180` deja hasta tres minutos para completar la comprobación
en la ventana visible.

Para una auditoría exacta del resultado anterior se necesita su ZIP descargado
desde Actions, especialmente `informe_validacion.json`, `preguntas.json`, capturas
y HTML original. No envíes tokens ni perfiles del navegador.
