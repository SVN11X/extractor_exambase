# Inicio

La herramienta funciona desde GitHub Actions. Consulta [README.md](README.md) para las tareas y [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md) para activarlas.

- Un examen: **Actions → Actualizar un examen**, introduce su URL.
- Un proveedor: **Actions → Extraer exámenes por proveedor**, introduce su slug.
- Automático: el workflow programado atiende proveedores por turnos y conserva la cola.

Descarga `resultado.zip` desde la carpeta del examen en `bancos/` o desde el artefacto `exambase-resultado`. Usa `preguntas.html` para estudiar y `para_ia/` junto con imágenes para una IA. El lector no necesita instalación ni ejecuta JavaScript.

El banco se actualiza en una ruta fija. Un resultado parcial no reemplaza una copia completa. Revisa siempre `informe_validacion.json`.
