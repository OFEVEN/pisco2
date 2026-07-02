# -*- coding: utf-8 -*-
"""
app.py — Dashboard PISCO Precipitación Perú
=============================================
Aplicación Streamlit que integra:
  1. Carga del NetCDF diario de PISCO (desde Google Drive o ruta local).
  2. Series diarias/mensuales por puntos (manual o Excel) -> Excel.
  3. Precipitación media diaria/mensual por cuenca (shapefile .zip) -> Excel.
  4. Mapa diario de precipitación para cualquier fecha.
  5. Mapas climáticos mensuales/anuales por periodo.
  6. Mapas de anomalías diaria/mensual/anual.
  7. Mapas de precipitación máxima diaria por periodo.
  8. Índice de Precipitación Antecedente (API) por punto o cuenca -> Excel.

Ejecutar localmente:
    streamlit run app.py

Desplegar gratis (público, sin restricciones de acceso):
    Streamlit Community Cloud -> ver README.md
"""

import io
import datetime as dt

import numpy as np
import pandas as pd
import streamlit as st

from utils_data import (
    download_from_gdrive, load_pisco_dataset,
    load_points_from_excel, load_basin_from_zip,
)
from utils_processing import (
    point_daily_series, to_monthly, basin_daily_series,
    monthly_climatology_maps, annual_climatology_map,
    daily_anomaly_map, monthly_anomaly_map, annual_anomaly_map,
    max_daily_precip_map, compute_api,
)
from utils_plot import plot_map, plot_timeseries, PERU_BBOX

st.set_page_config(page_title="Dashboard PISCO Precipitación - Perú", layout="wide")


# =============================================================================
# UTILIDADES DE EXPORTACIÓN
# =============================================================================

def df_to_excel_bytes(sheets: dict):
    """Recibe un dict {nombre_hoja: DataFrame} y devuelve un .xlsx en bytes."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name[:31])
    buffer.seek(0)
    return buffer


def fig_to_png_bytes(fig):
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    buffer.seek(0)
    return buffer


# =============================================================================
# CARGA DE DATOS (CACHEADA)
# =============================================================================

st.sidebar.title("⚙️ Configuración de datos")

modo_fuente = st.sidebar.radio(
    "Fuente del NetCDF PISCO",
    ["Google Drive (enlace público)", "Ruta local en el servidor"],
)

if modo_fuente == "Google Drive (enlace público)":
    gdrive_input = st.sidebar.text_input(
        "ID o URL pública de Google Drive del archivo "
        "'Pisco_dairio_1ene1981_16abri2026.nc'",
        help="El archivo debe estar compartido como 'Cualquier persona con "
             "el enlace puede ver'.",
    )
    local_path = "./data/Pisco_diario_1981_2026.nc"
else:
    local_path = st.sidebar.text_input("Ruta local del archivo .nc", value="./data/Pisco_diario_1981_2026.nc")
    gdrive_input = None


@st.cache_resource(show_spinner="Cargando NetCDF de PISCO (puede tardar varios minutos la primera vez)...")
def get_dataset(gdrive_input, local_path):
    if gdrive_input:
        path = download_from_gdrive(gdrive_input, local_path)
    else:
        path = local_path
    da, meta = load_pisco_dataset(path)
    return da, meta


cargar = st.sidebar.button("📥 Cargar / actualizar datos PISCO")

if "da" not in st.session_state:
    st.session_state["da"] = None
    st.session_state["meta"] = None

if cargar or (st.session_state["da"] is None and modo_fuente == "Ruta local en el servidor"):
    try:
        da, meta = get_dataset(gdrive_input, local_path)
        st.session_state["da"] = da
        st.session_state["meta"] = meta
        st.sidebar.success("Datos cargados correctamente.")
    except Exception as e:
        st.sidebar.error(f"Error al cargar los datos: {e}")

da = st.session_state["da"]
meta = st.session_state["meta"]

if meta:
    st.sidebar.markdown(
        f"**Variable detectada:** `{meta['var_name_original']}`  \n"
        f"**Periodo:** {meta['fecha_inicio']} a {meta['fecha_fin']}  \n"
        f"**Pasos temporales:** {meta['n_time']}"
    )

st.title("🌧️ Dashboard de Precipitación PISCO — Perú")

if da is None:
    st.info("Carga el archivo NetCDF de PISCO desde la barra lateral para comenzar.")
    st.stop()

FECHA_MIN = pd.Timestamp(meta["fecha_inicio"]).date()
FECHA_MAX = pd.Timestamp(meta["fecha_fin"]).date()


# =============================================================================
# TABS
# =============================================================================

tabs = st.tabs([
    "📍 Puntos (diario/mensual)",
    "🗺️ Cuenca (diario/mensual)",
    "📅 Mapa diario",
    "📊 Climatología",
    "📈 Anomalías",
    "🌧️ Precip. máxima",
    "💧 API (Índice de Precipitación Antecedente)",
])

# -----------------------------------------------------------------------
# TAB 1: PUNTOS
# -----------------------------------------------------------------------
with tabs[0]:
    st.header("Series diarias y mensuales por puntos")

    modo_puntos = st.radio("Selección de puntos", ["Manual", "Subir Excel"], horizontal=True, key="modo_puntos")

    if modo_puntos == "Manual":
        st.caption("Agrega filas con nombre, latitud y longitud.")
        puntos_df = st.data_editor(
            pd.DataFrame({"nombre": ["Punto_1"], "lat": [-12.05], "lon": [-75.2]}),
            num_rows="dynamic", key="editor_puntos",
        )
    else:
        excel_puntos = st.file_uploader("Excel con columnas nombre/lat/lon", type=["xlsx", "xls"], key="up_puntos")
        puntos_df = load_points_from_excel(excel_puntos) if excel_puntos else None

    rango_fechas_pts = st.date_input(
        "Rango de fechas a procesar", value=(FECHA_MIN, FECHA_MAX),
        min_value=FECHA_MIN, max_value=FECHA_MAX, key="rango_pts",
    )

    if st.button("Procesar puntos", key="btn_puntos") and puntos_df is not None and len(puntos_df) > 0:
        with st.spinner("Extrayendo series..."):
            sheets = {}
            resultados = {}
            for _, row in puntos_df.iterrows():
                df_d = point_daily_series(da, float(row["lat"]), float(row["lon"]))
                df_d = df_d.loc[str(rango_fechas_pts[0]):str(rango_fechas_pts[1])]
                df_m = to_monthly(df_d)
                sheets[f"{row['nombre']}_diario"] = df_d
                sheets[f"{row['nombre']}_mensual"] = df_m
                resultados[row["nombre"]] = (df_d, df_m)

        st.success(f"{len(resultados)} punto(s) procesado(s).")
        for nombre, (df_d, df_m) in resultados.items():
            st.subheader(nombre)
            c1, c2 = st.columns(2)
            with c1:
                st.pyplot(plot_timeseries(df_d, "precip_mm", f"Precipitación diaria - {nombre}"))
            with c2:
                st.pyplot(plot_timeseries(df_m, "precip_mm_mensual", f"Precipitación mensual - {nombre}", kind="bar"))

        excel_bytes = df_to_excel_bytes(sheets)
        st.download_button("⬇️ Descargar Excel (diario + mensual)", data=excel_bytes,
                            file_name="precipitacion_puntos.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -----------------------------------------------------------------------
# TAB 2: CUENCA
# -----------------------------------------------------------------------
with tabs[1]:
    st.header("Precipitación media diaria y mensual por cuenca")
    zip_cuenca = st.file_uploader("Shapefile de la cuenca (.zip con .shp/.shx/.dbf/.prj)", type=["zip"], key="up_cuenca")

    rango_fechas_cu = st.date_input(
        "Rango de fechas a procesar", value=(FECHA_MIN, FECHA_MAX),
        min_value=FECHA_MIN, max_value=FECHA_MAX, key="rango_cuenca",
    )

    if st.button("Procesar cuenca", key="btn_cuenca") and zip_cuenca is not None:
        with st.spinner("Enmascarando la cuenca y calculando el promedio espacial (puede tardar)..."):
            gdf = load_basin_from_zip(zip_cuenca)
            df_d = basin_daily_series(da, gdf)
            df_d = df_d.loc[str(rango_fechas_cu[0]):str(rango_fechas_cu[1])]
            df_m = to_monthly(df_d)

        st.success("Cuenca procesada.")
        c1, c2 = st.columns(2)
        with c1:
            st.pyplot(plot_timeseries(df_d, "precip_mm", "Precipitación media diaria - Cuenca"))
        with c2:
            st.pyplot(plot_timeseries(df_m, "precip_mm_mensual", "Precipitación media mensual - Cuenca", kind="bar"))

        excel_bytes = df_to_excel_bytes({"cuenca_diario": df_d, "cuenca_mensual": df_m})
        st.download_button("⬇️ Descargar Excel (cuenca)", data=excel_bytes,
                            file_name="precipitacion_cuenca.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -----------------------------------------------------------------------
# TAB 3: MAPA DIARIO
# -----------------------------------------------------------------------
with tabs[2]:
    st.header("Mapa diario de precipitación")
    fecha_mapa = st.date_input("Fecha", value=FECHA_MAX, min_value=FECHA_MIN, max_value=FECHA_MAX, key="fecha_mapa_diario")

    if st.button("Generar mapa", key="btn_mapa_diario"):
        with st.spinner("Generando mapa..."):
            campo = da.sel(time=str(fecha_mapa), method="nearest")
            fig = plot_map(campo, f"Precipitación diaria PISCO — {fecha_mapa}", cmap="YlGnBu", units="mm")
        st.pyplot(fig)
        st.download_button("⬇️ Descargar mapa (PNG)", data=fig_to_png_bytes(fig),
                            file_name=f"precip_diaria_{fecha_mapa}.png", mime="image/png")

# -----------------------------------------------------------------------
# TAB 4: CLIMATOLOGÍA
# -----------------------------------------------------------------------
with tabs[3]:
    st.header("Mapas climáticos mensuales y anuales")
    rango_clim = st.date_input(
        "Periodo de la climatología", value=(FECHA_MIN, FECHA_MAX),
        min_value=FECHA_MIN, max_value=FECHA_MAX, key="rango_clim",
    )
    tipo_clim = st.radio("Tipo de climatología", ["Mensual (12 mapas)", "Anual (1 mapa)"], horizontal=True)

    if st.button("Generar climatología", key="btn_clim"):
        with st.spinner("Calculando climatología (puede tardar varios minutos)..."):
            if tipo_clim.startswith("Mensual"):
                clim = monthly_climatology_maps(da, str(rango_clim[0]), str(rango_clim[1]))
                meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
                cols = st.columns(3)
                figs_zip = {}
                for m in range(1, 13):
                    fig = plot_map(clim.sel(month=m), f"Climatología {meses[m-1]} ({rango_clim[0]}–{rango_clim[1]})",
                                    cmap="YlGnBu", units="mm")
                    cols[(m - 1) % 3].pyplot(fig)
                    figs_zip[meses[m-1]] = fig_to_png_bytes(fig)
                st.session_state["clim_figs"] = figs_zip
            else:
                clim = annual_climatology_map(da, str(rango_clim[0]), str(rango_clim[1]))
                fig = plot_map(clim, f"Climatología anual ({rango_clim[0]}–{rango_clim[1]})",
                                cmap="YlGnBu", units="mm")
                st.pyplot(fig)
                st.download_button("⬇️ Descargar mapa (PNG)", data=fig_to_png_bytes(fig),
                                    file_name="climatologia_anual.png", mime="image/png")

# -----------------------------------------------------------------------
# TAB 5: ANOMALÍAS
# -----------------------------------------------------------------------
with tabs[4]:
    st.header("Mapas de anomalías (diaria, mensual, anual)")
    tipo_anom = st.selectbox("Tipo de anomalía", ["Diaria", "Mensual", "Anual"])

    c1, c2 = st.columns(2)
    with c1:
        baseline = st.date_input("Periodo base (climatología de referencia)",
                                  value=(FECHA_MIN, FECHA_MAX), min_value=FECHA_MIN, max_value=FECHA_MAX,
                                  key="baseline_anom")
    with c2:
        if tipo_anom == "Diaria":
            fecha_obj = st.date_input("Fecha objetivo", value=FECHA_MAX, min_value=FECHA_MIN, max_value=FECHA_MAX, key="fecha_anom")
        elif tipo_anom == "Mensual":
            anio_obj = st.number_input("Año", min_value=FECHA_MIN.year, max_value=FECHA_MAX.year, value=FECHA_MAX.year)
            mes_obj = st.number_input("Mes", min_value=1, max_value=12, value=FECHA_MAX.month)
        else:
            anio_obj = st.number_input("Año", min_value=FECHA_MIN.year, max_value=FECHA_MAX.year, value=FECHA_MAX.year, key="anio_anom_anual")

    if st.button("Generar anomalía", key="btn_anom"):
        with st.spinner("Calculando anomalía..."):
            if tipo_anom == "Diaria":
                anom, obs, clim = daily_anomaly_map(da, str(fecha_obj), str(baseline[0]), str(baseline[1]))
                titulo = f"Anomalía diaria — {fecha_obj}"
            elif tipo_anom == "Mensual":
                anom, obs, clim = monthly_anomaly_map(da, int(anio_obj), int(mes_obj), str(baseline[0]), str(baseline[1]))
                titulo = f"Anomalía mensual — {int(anio_obj)}-{int(mes_obj):02d}"
            else:
                anom, obs, clim = annual_anomaly_map(da, int(anio_obj), str(baseline[0]), str(baseline[1]))
                titulo = f"Anomalía anual — {int(anio_obj)}"

            fig = plot_map(anom, titulo, diverging=True, units="mm (anomalía)")
        st.pyplot(fig)
        st.download_button("⬇️ Descargar mapa de anomalía (PNG)", data=fig_to_png_bytes(fig),
                            file_name=f"anomalia_{tipo_anom.lower()}.png", mime="image/png")

# -----------------------------------------------------------------------
# TAB 6: PRECIPITACIÓN MÁXIMA
# -----------------------------------------------------------------------
with tabs[5]:
    st.header("Precipitación máxima diaria por periodo")
    rango_max = st.date_input(
        "Periodo a evaluar (mes, año o rango libre)", value=(FECHA_MIN, FECHA_MAX),
        min_value=FECHA_MIN, max_value=FECHA_MAX, key="rango_max",
    )

    if st.button("Generar mapa de máximos", key="btn_max"):
        with st.spinner("Calculando máximos..."):
            max_map, fecha_max = max_daily_precip_map(da, str(rango_max[0]), str(rango_max[1]))
            fig = plot_map(max_map, f"Precipitación máxima diaria ({rango_max[0]}–{rango_max[1]})",
                            cmap="YlOrRd", units="mm")
        st.pyplot(fig)
        st.download_button("⬇️ Descargar mapa (PNG)", data=fig_to_png_bytes(fig),
                            file_name="precip_maxima.png", mime="image/png")

# -----------------------------------------------------------------------
# TAB 7: API
# -----------------------------------------------------------------------
with tabs[6]:
    st.header("Índice de Precipitación Antecedente (API)")
    origen_api = st.radio("Calcular API para:", ["Un punto (manual)", "Una cuenca (.zip)"], horizontal=True)
    k_api = st.slider("Coeficiente de recesión k", 0.50, 0.99, 0.85, 0.01)
    rango_api = st.date_input(
        "Rango de fechas", value=(FECHA_MIN, FECHA_MAX),
        min_value=FECHA_MIN, max_value=FECHA_MAX, key="rango_api",
    )

    if origen_api == "Un punto (manual)":
        c1, c2 = st.columns(2)
        with c1:
            lat_api = st.number_input("Latitud", value=-12.05, format="%.4f")
        with c2:
            lon_api = st.number_input("Longitud", value=-75.20, format="%.4f")
        zip_api = None
    else:
        zip_api = st.file_uploader("Shapefile de la cuenca (.zip)", type=["zip"], key="up_cuenca_api")

    if st.button("Calcular API", key="btn_api"):
        with st.spinner("Calculando API..."):
            if origen_api == "Un punto (manual)":
                df_d = point_daily_series(da, lat_api, lon_api)
                nombre_serie = f"Punto ({lat_api:.3f}, {lon_api:.3f})"
            else:
                if zip_api is None:
                    st.warning("Sube el archivo .zip de la cuenca.")
                    st.stop()
                gdf = load_basin_from_zip(zip_api)
                df_d = basin_daily_series(da, gdf)
                nombre_serie = "Cuenca"

            df_d = df_d.loc[str(rango_api[0]):str(rango_api[1])]
            df_api = compute_api(df_d, k=k_api)

        st.success("API calculado.")
        st.pyplot(plot_timeseries(df_api, "API", f"API (k={k_api}) — {nombre_serie}"))

        excel_bytes = df_to_excel_bytes({"API_diario": df_api})
        st.download_button("⬇️ Descargar Excel (API)", data=excel_bytes,
                            file_name="API_resultado.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.markdown("---")
st.caption(
    "Dashboard de precipitación PISCO — datos de SENAMHI. "
    "Desarrollado en Streamlit. Sin restricciones de acceso a los datos: "
    "cualquier usuario con el enlace puede utilizar todas las funciones."
)
