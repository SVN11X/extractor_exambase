# Uso de GitHub Actions

1. Incorpora la actualización a la rama predeterminada del repositorio.
2. En **Settings → Actions → General → Workflow permissions**, permite lectura y escritura. Si una política de tu organización lo impide, el artefacto sigue siendo descargable, pero el trabajo marcará el error al guardar en Git.
3. Abre **Actions → Actualizar un examen → Run workflow**, pega la URL y ejecuta. La URL puede ser la portada o una página de preguntas de un examen admitido por el catálogo.
4. Abre la ejecución y revisa su resumen. **exambase-resultado** incluye carpetas por proveedor/examen y `resumen.md`. Los artefactos duran 14 días; `bancos/` conserva el resultado vigente.

No se requieren tokens personales, ID de respaldo, selección de motor, tiempos de espera ni campos de frontend. Se usa `GITHUB_TOKEN` con permiso `contents: write`, suministrado por GitHub al workflow. Las tres tareas comparten una cola para serializar escrituras y conservar hasta 100 solicitudes pendientes.

## Actualizar manualmente

**Actualizar un examen** fuerza una actualización al existir una copia completa. Si la extracción anterior quedó parcial, primero intenta reparar sus metadatos desde las capturas conservadas y después la reanuda automáticamente, incluidas las páginas con respuestas, imágenes o referencias pendientes. El hash del respaldo se verifica antes de usarlo. Si necesitas descartar voluntariamente un parcial corrupto, revisa su diagnóstico y retíralo mediante un cambio Git explícito; la tarea no lo destruye silenciosamente.

**Extraer exámenes por proveedor** admite un slug de `catalogos/catalogo.json`, por ejemplo `google-cloud`, `microsoft` o `cisco`. Procesa exámenes elegibles respetando el límite por lote y la antigüedad configurada. La ejecución manual puede reanudar parciales sin esperar el intervalo automático (los rechazos de acceso conservan su pausa). Repite la misma tarea para completar lotes pendientes; para renovar inmediatamente un examen completo usa la tarea individual.

## Programación

El workflow por proveedor corre diariamente a las 03:17 de America/Santiago. El catálogo adicional corre los lunes a las 02:17, misma zona. Cambia los cron en `.github/workflows/` si necesitas otro horario. La programación de GitHub opera sobre la rama predeterminada y puede retrasarse. En repositorios públicos GitHub deshabilita las tareas programadas tras 60 días sin actividad; puedes volver a habilitarlas desde Actions.

La cola `automatizacion/estado.json` guarda el siguiente proveedor, el último examen y los aplazamientos por acceso. No se crea una matriz de cientos de trabajos simultáneos. Hasta 10 exámenes se atienden secuencialmente por lote; un límite de tiempo deja el resto pendiente. El resumen separa exámenes nuevos, bancos parciales y espera de reintento. Cero elegibles por antigüedad no significa que todos los bancos estén completos.

Edita `automatizacion/config.json` para elegir proveedores, intervalo mínimo, presupuesto, máximo por lote, minutos por examen y frecuencia de renovación. La actualización `catalogo --vendor all` avanza un proveedor por ejecución; la tarea por proveedor también descubre el índice correspondiente cuando caduca. Un catálogo con menos enlaces que el contador actual anunciado (o el último conocido si la página no lo incluye) se conserva para revisión y no se declara completo.

## Conservación del resultado

La publicación usa una carpeta temporal y un reemplazo recuperable. Una recopilación parcial conserva la copia anterior más completa y un solo punto de avance. Si cambian los totales al reanudar, se inicia una captura nueva una sola vez, conservando el respaldo. El índice se reconstruye de los manifiestos vigentes; una publicación fallida devuelve la carpeta anterior. `migrar_bancos.py` consolida automáticamente las versiones antiguas y es reanudable e idempotente.

Los jobs duran como máximo 330 minutos (catálogo: 60); el presupuesto interno es menor para reservar tiempo de empaquetado y guardado. Una cancelación forzada de GitHub o un fallo del runner antes de la conservación puede perder el trabajo no publicado de ese job. Los resultados publicados en ejecuciones anteriores permanecen disponibles.

Scrapling usa una sesión de navegador por examen; las imágenes provienen de esa sesión. No hay cambio automático a Selenium, FlareSolverr, Rebrowser o clientes alternativos. Si aparece un bloqueo que exige intervención, la ejecución conserva un ZIP parcial y marca el diagnóstico. Consulta el código y página del fallo; ninguna dependencia garantiza acceso desatendido al sitio.

Al retirar el workflow de Pages se deja de publicar la interfaz. Si había un despliegue activo, puedes retirarlo desde **Settings → Pages → Unpublish site**. Eliminar archivos de la rama no despublica por sí solo un despliegue anterior.
