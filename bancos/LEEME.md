# Bancos vigentes

Abre la carpeta del proveedor, luego la del examen, y descarga `resultado.zip`. El ZIP incluye un lector HTML estático, Markdown, JSONL para IA, imágenes y referencias. Revisa el informe del examen antes de usar el contenido.

Cada examen tiene una única carpeta, actualizada en el mismo lugar. `manifest_guardado.json` registra procedencia, estado y SHA-256 del ZIP. Si existe `progreso.zip`, corresponde a una actualización parcial; `resultado.zip` conserva la copia anterior más completa. El índice de máquinas es `index.json`, esquema 2.0.

La presencia de todas las preguntas y respuestas no garantiza que todos los metadatos de contexto estén verificados. El informe y el estado indican esa diferencia.
