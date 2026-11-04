# Verificación 6.0.0

Base: `7b235082726f155665c126e2fc7523f4dfa15429`. Revisión y pruebas locales; no se lanzaron extracciones reales ni se habilitaron tareas en el repositorio remoto.

## Pruebas

- `python -m unittest discover -s tests -p 'test_*.py'`: 94 pruebas, incluidas actualización en ruta estable, conservación de copia completa ante un parcial, reanudación automática, rollback de publicación, hash de respaldo, rotación de proveedores, presupuesto, catálogo incompleto, bloqueo de acceso, alias, migración idempotente y reinicio de una captura al cambiar los totales.
- `node --test tests/test_capture_script.mjs`: 3 pruebas de hidratación y recuperación de respuestas.
- `python verificar_bancos.py`: auditoría de los tres bancos, CRC, SHA-256 del ZIP y de cada archivo inventariado. 692 archivos comprobados.
- Validación local de sintaxis YAML y parámetros de los tres workflows y la acción compartida. Se comprobó la sintaxis actual de `queue: max` y `schedule.timezone` con la documentación oficial de GitHub.
- `git diff --check` y compilación de Python.
- El parche se aplica con `git am` sobre la base indicada en una copia limpia; se compara su árbol con el de la entrega. El ZIP completo se exporta de los archivos versionados.

## Bancos consolidados

| Examen | Preguntas/respuestas | Imágenes guardadas | Recopilación |
| --- | --- | --- | --- |
| Google Professional Data Engineer | 349/349 | 25/25 | Completa |
| Google Associate Cloud Engineer | 349/349 | 8/8 | Completa |
| Google Associate Data Practitioner | 103/103 | 9/9 | Parcial: metadatos de 15 preguntas pendientes |

La migración verificó igualdad de preguntas y contextos y conservación de hashes de imágenes frente a la mejor versión anterior. Los cinco directorios por ejecución se consolidaron en tres rutas. Se comprobó que los ZIP de estudio no incluyen JavaScript independiente ni HTML de origen activo. El HTML del lector no contiene scripts y aplica una política de contenido restrictiva; las respuestas están desplegadas para imprimir.

No se realizó un análisis con Microsoft Defender y no puede confirmarse el falso positivo de las capturas. Tampoco se realizó una prueba visual en navegador de esta entrega; las pruebas del lector verifican estructura, escape y ubicación de imágenes. El acceso real y la programación de GitHub deben comprobarse al ejecutar los workflows en la rama predeterminada. Una política del servidor puede requerir intervención y dejar un resultado parcial verificable.
