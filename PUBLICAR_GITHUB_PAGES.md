# Publicar una vez y reutilizar

El proyecto está preparado para GitHub, pero este ZIP no está conectado a una cuenta ni a un repositorio concreto. No incluye tokens, sesiones ni bancos completos de preguntas.

## 1. Sube el proyecto

Crea tu repositorio y sube **el contenido de extractor_exambase**, con `web/`, los scripts Python y `.github/` en la raíz. Conserva los archivos ocultos `.github/`, `.gitignore` y `web/.nojekyll`. Para un repositorio nuevo con rama `main`, desde esa carpeta:

```bash
git init -b main
git add .
git commit -m "Añadir archivo de estudio ExamBase"
git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
git push -u origin main
```

Usa tu sesión habitual de GitHub o GitHub CLI para autenticarte. No añadas un token a la URL del remoto. Si ya existe un repositorio, integra estos archivos en su checkout y revisa el diff antes de hacer commit.

## 2. Activa Pages

En **Settings → Pages → Build and deployment → Source**, elige **GitHub Actions**. Ejecuta **Actions → Publicar frontend en GitHub Pages → Run workflow**. El enlace del sitio aparece en la ejecución y en Settings → Pages. El workflow publica sólo `web/` y usa rutas relativas compatibles con `/nombre-del-repositorio/`. Si tu rama principal se llama de otra manera, ajusta el filtro `branches: [main]` de `publicar-pages.yml`, o usa Run workflow.

GitHub Free permite Pages desde repositorios públicos. Para conservar los resultados privados puedes separar:

| Repositorio | Contenido | Uso |
| --- | --- | --- |
| Público para Pages | `web/` y workflow `publicar-pages.yml` | Interfaz pública sin credenciales ni preguntas |
| Privado para el motor | Proyecto completo y workflows de descarga/catálogo | Ejecuciones y bancos de preguntas |

También puedes usar un único repositorio según tu plan de GitHub y la visibilidad que desees. La interfaz permite conectar cualquier repositorio que tenga los workflows de este proyecto.

## 3. Conecta la interfaz

Abre la web y pulsa **Conectar GitHub**. Introduce usuario, repositorio del motor y un **fine-grained personal access token** limitado a ese repositorio, con **Actions: Read and write** y **Contents: Read**. Metadata en lectura se concede automáticamente. El token se usa sólo en memoria dentro de esa pestaña; no se escribe en el código, almacenamiento del navegador, URL ni archivos descargados. Al desconectar, recargar o cerrar la pestaña tendrás que introducirlo de nuevo. No lo envíes por chat.

El `GITHUB_TOKEN` propio de Actions es el que guarda los resultados y el catálogo. No necesitas dar Contents en escritura al token que introduces en el frontend. Si una política de organización o protección de rama impide el push del workflow, el artefacto seguirá disponible y la ejecución indicará el fallo de guardado. Configura permisos de Actions y una rama apta para los commits automáticos si deseas usar esa opción.

## 4. Elige y descarga

Busca un examen del catálogo o usa **Tengo el enlace**. Los contadores se confirman al leer la primera página. El catálogo inicial es parcial: incluye el índice de proveedores y los exámenes cargados explícitamente, sin simular que contiene los 1.657 exámenes anunciados. **Actualizar catálogo** carga el índice guardado en tu repositorio y solicita otra actualización del proveedor seleccionado; vuelve a pulsarlo cuando termine para recuperar la lista nueva. Si el sitio rechaza la lectura se conservan las entradas anteriores. Siempre puedes pegar una URL admitida.

Elige el motor y la pausa, marca **Guardar también en el repositorio** si corresponde y pulsa **Preparar paquete**. Al enviarse a Actions puedes cerrar la web y apagar tu ordenador. En **Descargas** verás las ejecuciones y los bancos guardados. Los enlaces de GitHub pueden pedir iniciar sesión para descargar artefactos o archivos privados. El artefacto de Actions contiene el ZIP del examen más el estado de ejecución; extrae ambos niveles si lo abres manualmente.

El guardado se activa por defecto al conectar un repositorio privado. En uno público se deja desactivado y se informa de que los bancos serán visibles si lo activas. El frontend no sube tu ZIP a servidores al usar **Revisar un archivo**.

## 5. Repetir o reanudar

Para otro examen repite el paso 4; el código y las versiones anteriores permanecen en el repositorio. Para reanudar un parcial, indica su ID de Actions en las opciones. Se usa su artefacto o la copia del repositorio si ya caducó. El motor rechaza respaldos de otro examen y cambios de numeración; no mezcla bancos.

Los artefactos se conservan 7 días; los commits de `bancos/` no dependen de esa caducidad. El guardado de archivos se limita a 95 MiB por archivo para evitar rechazos de Git. El historial crece con cada ejecución: revisa el tamaño del repositorio al conservar muchos exámenes. No sobrescribas una ejecución guardada: inicia otra si quieres una nueva versión.

## Ejecución desatendida y verificaciones

Actions ejecuta el proceso sin tu ordenador, siempre que la web entregue el contenido a ese entorno. Selenium y Beautiful Soup son alternativas de navegación y análisis, no un permiso de acceso. Si una verificación no se completa en 60 segundos o se rechaza, se conserva un parcial con el motivo; no se intenta resolver el desafío. Para garantizar funcionamiento desatendido con una web protegida, el propietario debe ofrecer un acceso de automatización, una exportación o una regla de acceso adecuada. El proyecto `undetected-chromedriver` advierte que no oculta la IP y que puede fallar en centros de datos; por eso no se presenta como una solución garantizada para GitHub Actions.

Referencias oficiales: [Pages con workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [Selenium Manager](https://www.selenium.dev/documentation/selenium_manager/), [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) y [limitaciones de undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver#what-this-is-not).

La entrega 5.0.1 incluye ZIP completo y parche `git am` sobre el commit real `a3842cc294dac1449408d3fa73bb55f211d8998f` de `SVN11X/extractor_exambase`. Consulta **CORRECCIONES_5_0_1.md** para aplicarlo, configurar un runner propio o reanudar el parcial del registro.
