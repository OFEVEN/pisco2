# Dashboard de Precipitación PISCO — Perú

Dashboard en **Streamlit** para explorar el producto de precipitación diaria
PISCO (SENAMHI): series por punto/cuenca, mapas diarios, climatología,
anomalías, precipitación máxima, y el Índice de Precipitación Antecedente
(API), con exportación a Excel y PNG.

## Estructura del proyecto

```
pisco_dashboard/
├── app.py                 # Aplicación principal (Streamlit)
├── utils_data.py           # Carga de NetCDF, Excel de puntos, shapefile de cuenca
├── utils_processing.py     # Cálculos: series, climatología, anomalías, API
├── utils_plot.py           # Mapas y series temporales
├── requirements.txt
└── README.md
```

## 1. Ejecutar en tu computadora

```bash
pip install -r requirements.txt
streamlit run app.py
```

Se abrirá en `http://localhost:8501`.

## 2. Cargar el archivo PISCO

En la barra lateral tienes dos opciones:

- **Google Drive (enlace público):** pega el ID o la URL del archivo
  `Pisco_dairio_1ene1981_16abri2026.nc`. El archivo debe estar compartido
  como **"Cualquier persona con el enlace puede ver"**. El dashboard lo
  descarga una sola vez (con `gdown`) y lo cachea.
- **Ruta local:** si vas a desplegar el dashboard con el archivo ya
  incluido en el servidor (ver nota de tamaño más abajo), indica la ruta.

> **Nota sobre el tamaño del archivo:** un NetCDF diario 1981-2026 a
> resolución PISCO (~0.1°) puede pesar varios GB. La lectura se hace de
> forma perezosa (`dask`), por lo que no se carga todo en memoria de una
> vez, pero **la descarga inicial y el disco disponible sí importan**.
> Revisa la sección 4 sobre límites del hosting gratuito.

## 3. Desplegar gratis y sin restricciones de acceso — Streamlit Community Cloud

Streamlit Community Cloud (streamlit.io/cloud) es gratuito y publica la
app en una URL pública tipo `https://tuapp.streamlit.app`, accesible para
cualquier persona sin necesidad de cuenta ni login.

Pasos:

1. Sube esta carpeta (`pisco_dashboard/`) a un repositorio de **GitHub**
   (puede ser público).
2. Entra a https://share.streamlit.io/ con tu cuenta de GitHub.
3. Clic en **"New app"**, selecciona el repositorio, la rama, y como
   archivo principal `app.py`.
4. Deploy. En unos minutos tendrás la URL pública.
5. Comparte esa URL: cualquier usuario podrá usar el dashboard completo
   (cargar el NetCDF desde el enlace de Drive que tú definas, o uno que
   cada usuario indique) sin pedirle credenciales.

### Alternativas gratuitas equivalentes
- **Hugging Face Spaces** (con SDK "Streamlit"): mismo código, sin cambios.
- **Render.com** (plan free, con Dockerfile) si necesitas más control de
  recursos, aunque con más pasos de configuración.

## 4. Límites del plan gratuito a tener en cuenta

- Streamlit Community Cloud (free tier) ofrece ~1 GB de RAM y almacenamiento
  limitado. Si el NetCDF completo (1981-2026 diario) pesa varios GB:
  - Considera **recortar el NetCDF al dominio de Perú** y/o **comprimirlo**
    (NetCDF4 con compresión `zlib`) antes de subirlo a Drive.
  - El uso de `dask`/lectura perezosa en `utils_data.py` evita cargar todo
    el arreglo en memoria; los cálculos (climatología, anomalías) solo
    materializan el subconjunto de tiempo/espacio solicitado.
  - Si el dashboard se usa intensamente, evalúa un hosting con más recursos
    (Render, un VPS pequeño, o Hugging Face Spaces con más RAM en su tier
    pagado) — igual gratis para el usuario final, solo cambia dónde corre.

## 5. Formatos de entrada esperados

**Excel de puntos** (pestaña "Puntos"): columnas `nombre`, `lat`, `lon`
(nombres de columna flexibles: también acepta `latitud`/`longitud`,
`estación`, etc.)

**Shapefile de cuenca** (pestañas "Cuenca" y "API"): un `.zip` que
contenga como mínimo `.shp`, `.shx`, `.dbf` (y de preferencia `.prj`
con el sistema de coordenadas).

## 6. Notas técnicas

- El nombre de la variable de precipitación y de las dimensiones
  (lat/lon/time) se **detectan automáticamente**, ya que PISCO no ha
  mantenido un estándar fijo entre versiones.
- Las máscaras de cuenca usan la geometría real del shapefile (no solo
  el rectángulo delimitador), vía `regionmask`.
- El API se calcula de forma recursiva: `API_t = k · API_(t-1) + P_t`.
