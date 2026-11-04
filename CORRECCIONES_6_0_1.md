# Correcciones 6.0.1 y diagnóstico de las ejecuciones

Base Git: `ef7a54b` (bancos guardados después del lote por proveedor). Esta actualización es incremental sobre 6.0.

## Qué muestran los registros

| Registro / ejecución | Resultado real |
| --- | --- |
| `logs_113512267613.zip` / `41889454061` | Professional Data Engineer: recopilación completa, 349 preguntas, 349 respuestas y 25 imágenes; artefacto y banco guardados correctamente. |
| `logs_113517443815.zip` / `41891340136` | Diez exámenes procesados: cinco completos y cinco parciales. El código de salida 2 corresponde a esa validación parcial; el banco y el artefacto sí se conservaron. |

Los cinco parciales del lote son:

| Examen | Captura del registro | Causa / corrección |
| --- | --- | --- |
| Cloud Digital Leader | 289 preguntas, 288 respuestas | La pregunta 288 conserva todas las alternativas con `is_correct: false` y el DOM tampoco marca ninguna correcta. Se mantiene pendiente. |
| Generative AI Leader | 75 preguntas y respuestas | 60 metadatos descartados por confundir el orden interno, que se reinicia por tema, con la numeración global visible. Reparados con las capturas guardadas. |
| Professional Cloud Architect | 155 de 360 preguntas | Fallo de navegación en la página 32: `net::ERR_HTTP_RESPONSE_CODE_FAILURE`. El registro no proporciona el estado HTTP; no permite atribuirlo específicamente a Cloudflare ni afirmar que fue un 403. Debe reanudarse. |
| Professional Cloud DevOps Engineer | 239 preguntas, 238 respuestas | La pregunta 202 tampoco tiene alternativa marcada en el objeto ni en el DOM guardado. Se mantiene pendiente. |
| Professional Cloud Network Engineer | 316 preguntas y respuestas | Diez metadatos pendientes en las páginas 29 y 30 por diferencias de numeración interna. Reparados con las capturas guardadas. |

## Cambios

- Se conserva la numeración global mostrada y el orden interno en `raw.source_order` y el JSONL para IA. La vinculación exige página, URL, contadores y coincidencia de enunciado, imágenes y alternativas, sin contenido duplicado ambiguo. Una página o contenido diferente conserva la advertencia y no recibe metadatos de otra pregunta.
- Al reanudar, primero se revisan las capturas JSON originales y previas. Se verifica su hash y su correspondencia con las preguntas del respaldo. Si alcanzan para completar el resultado, se regenera sin abrir una sesión ni enviar solicitudes al sitio.
- La excepción de navegación conserva el código del navegador y el HTTP cuando éste se observó. Un fallo de transporte sin estado HTTP no se presenta como un bloqueo confirmado. El lote se detiene ante ese fallo y conserva el avance.
- El resumen separa bancos parciales, exámenes nuevos y espera de reintento. Un cero de exámenes elegibles no se presenta como ausencia de parciales. La ejecución manual por proveedor puede continuar parciales sin esperar el intervalo automático; los bloqueos mantienen su pausa.
- El informe distingue claves no marcadas en los datos guardados. No se deduce una respuesta de la explicación para presentarla como si estuviera marcada por la fuente.

Se incluyen los dos bancos reparados. Generative AI Leader queda completo con 75 preguntas y respuestas; Cloud Network Engineer con 316 preguntas y respuestas y sus 12 imágenes. Se verificó igualdad de enunciados, alternativas y claves frente al respaldo y conservación de los hashes de imágenes. Las páginas originales permanecen como datos, sin convertirlas en HTML ejecutable. Se conserva el ID de la extracción de origen y se identifica el reprocesamiento local.

La corrección mantiene Scrapling como único motor y los formularios actuales de Actions. El acceso real a Cloud Architect y las dos claves no marcadas siguen pendientes de una nueva comprobación en la fuente. La versión no garantiza superar políticas de acceso del servidor.
