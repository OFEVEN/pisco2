# -*- coding: utf-8 -*-
"""
utils_data.py
==============
Funciones de carga y detección automática de estructura de datos:

  - Lectura del NetCDF de PISCO (precipitación diaria), con detección
    automática del nombre de la variable y de las dimensiones (lat/lon/time),
    ya que PISCO NO tiene un estándar fijo entre versiones.
  - Descarga del NetCDF desde Google Drive (enlace público) si no está local.
  - Lectura de puntos (nombre, lat, lon) desde un archivo Excel subido por
    el usuario.
  - Lectura de una cuenca desde un shapefile comprimido en .zip subido por
    el usuario.
"""

import io
import os
import re
import zipfile
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

# Nombres candidatos típicos que ha usado PISCO en distintas versiones
VAR_CANDIDATES = ["pr", "precip", "precipitacion", "precipitación",
                   "pp", "Pp", "PP", "precipitation", "z", "variable", "tp"]
LAT_CANDIDATES = ["lat", "latitude", "y", "Y"]
LON_CANDIDATES = ["lon", "longitude", "x", "X"]
TIME_CANDIDATES = ["time", "T", "Time", "fecha"]


# =============================================================================
# 1. NETCDF PISCO
# =============================================================================

def download_from_gdrive(url_or_id, dest_path):
    """
    Descarga un archivo público de Google Drive usando gdown.
    Acepta tanto un ID de archivo como una URL completa de Drive.
    Si el archivo ya existe localmente, no vuelve a descargar.
    """
    import gdown

    dest_path = Path(dest_path)
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return str(dest_path)

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Aceptar tanto IDs sueltos como URLs completas
    if url_or_id.startswith("http"):
        gdown.download(url=url_or_id, output=str(dest_path), quiet=False, fuzzy=True)
    else:
        gdown.download(id=url_or_id, output=str(dest_path), quiet=False)

    if not dest_path.exists() or dest_path.stat().st_size == 0:
        raise RuntimeError(
            "No se pudo descargar el archivo desde Google Drive. "
            "Verifica que el enlace sea público ('Cualquier persona con el "
            "enlace puede ver') y que el ID/URL sea correcto."
        )
    return str(dest_path)


def _find_first_match(names, candidates):
    for c in candidates:
        if c in names:
            return c
    # búsqueda flexible por coincidencia parcial (case-insensitive)
    lower_map = {n.lower(): n for n in names}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def detect_dims(ds):
    """Detecta los nombres reales de las dimensiones lat/lon/time en el dataset."""
    all_dims = list(ds.dims)
    all_coords = list(ds.coords)
    pool = list(set(all_dims + all_coords))

    lat_name = _find_first_match(pool, LAT_CANDIDATES)
    lon_name = _find_first_match(pool, LON_CANDIDATES)
    time_name = _find_first_match(pool, TIME_CANDIDATES)

    if not (lat_name and lon_name and time_name):
        raise ValueError(
            f"No se pudieron detectar las dimensiones lat/lon/time. "
            f"Dimensiones disponibles: {all_dims}"
        )
    return lat_name, lon_name, time_name


def detect_precip_variable(ds, lat_name, lon_name, time_name):
    """
    Detecta la variable de precipitación:
      1. Prueba primero los nombres candidatos conocidos de PISCO.
      2. Si no hay coincidencia, busca la primera variable 3D (time, lat, lon).
    """
    match = _find_first_match(list(ds.data_vars), VAR_CANDIDATES)
    if match:
        return match

    for name, da in ds.data_vars.items():
        if lat_name in da.dims and lon_name in da.dims and time_name in da.dims:
            return name

    raise ValueError(
        f"No se pudo detectar automáticamente la variable de precipitación. "
        f"Variables disponibles: {list(ds.data_vars)}. "
        f"Indícala manualmente con el parámetro 'var_name'."
    )


def load_pisco_dataset(path, var_name=None, chunk_time=365):
    """
    Abre el NetCDF de PISCO de forma perezosa (dask), estandariza los nombres
    de dimensiones a ('time', 'lat', 'lon') y devuelve el DataArray de
    precipitación ya identificado.

    Retorna
    -------
    da : xr.DataArray  (dims: time, lat, lon)
    meta : dict con nombres originales detectados, por si se necesitan.
    """
    ds = xr.open_dataset(path, chunks={TIME_CANDIDATES[0]: chunk_time} if False else "auto")

    lat_name, lon_name, time_name = detect_dims(ds)
    if var_name is None:
        var_name = detect_precip_variable(ds, lat_name, lon_name, time_name)

    da = ds[var_name]
    rename_map = {}
    if lat_name != "lat":
        rename_map[lat_name] = "lat"
    if lon_name != "lon":
        rename_map[lon_name] = "lon"
    if time_name != "time":
        rename_map[time_name] = "time"
    if rename_map:
        da = da.rename(rename_map)

    # Asegurar orden de dimensiones y longitudes en formato -180/180
    if float(da.lon.max()) > 180:
        da = da.assign_coords(lon=(((da.lon + 180) % 360) - 180)).sortby("lon")

    da = da.sortby("lat")
    da.name = "precip"

    meta = {
        "var_name_original": var_name,
        "lat_name_original": lat_name,
        "lon_name_original": lon_name,
        "time_name_original": time_name,
        "n_time": da.sizes["time"],
        "fecha_inicio": str(da.time.min().values)[:10],
        "fecha_fin": str(da.time.max().values)[:10],
    }
    return da, meta


# =============================================================================
# 2. PUNTOS DESDE EXCEL
# =============================================================================

NAME_COL_CANDIDATES = ["nombre", "name", "estacion", "estación", "id", "punto"]
LATCOL_CANDIDATES = ["lat", "latitud", "latitude", "y"]
LONCOL_CANDIDATES = ["lon", "lng", "longitud", "longitude", "x"]


def load_points_from_excel(file_like):
    """
    Lee un Excel subido por el usuario con columnas de nombre, latitud y
    longitud (nombres de columna flexibles). Devuelve un DataFrame con
    columnas estandarizadas: ['nombre', 'lat', 'lon'].
    """
    df = pd.read_excel(file_like)
    cols_lower = {c.lower().strip(): c for c in df.columns}

    def find_col(candidates):
        for c in candidates:
            if c in cols_lower:
                return cols_lower[c]
        return None

    col_name = find_col(NAME_COL_CANDIDATES)
    col_lat = find_col(LATCOL_CANDIDATES)
    col_lon = find_col(LONCOL_CANDIDATES)

    if col_lat is None or col_lon is None:
        raise ValueError(
            f"No se encontraron columnas de latitud/longitud en el Excel. "
            f"Columnas disponibles: {list(df.columns)}. "
            f"Usa encabezados como 'lat'/'lon' o 'latitud'/'longitud'."
        )

    out = pd.DataFrame({
        "nombre": df[col_name] if col_name else [f"Punto_{i+1}" for i in range(len(df))],
        "lat": df[col_lat].astype(float),
        "lon": df[col_lon].astype(float),
    })
    return out


# =============================================================================
# 3. CUENCA DESDE SHAPEFILE (.zip)
# =============================================================================

def load_basin_from_zip(zip_file_like):
    """
    Extrae un shapefile de cuenca desde un .zip subido por el usuario
    (debe contener .shp, .shx, .dbf y, preferentemente, .prj) y lo devuelve
    como GeoDataFrame en EPSG:4326 (lat/lon).
    """
    import geopandas as gpd

    tmpdir = tempfile.mkdtemp(prefix="cuenca_")
    with zipfile.ZipFile(zip_file_like) as zf:
        zf.extractall(tmpdir)

    shp_files = list(Path(tmpdir).rglob("*.shp"))
    if not shp_files:
        raise ValueError(
            "El .zip no contiene ningún archivo .shp. Verifica que incluya "
            "los archivos .shp, .shx, .dbf (y .prj) de la cuenca."
        )

    gdf = gpd.read_file(shp_files[0])

    if gdf.crs is None:
        # Sin sistema de referencia definido: se asume WGS84 geográfico
        gdf = gdf.set_crs(epsg=4326)
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    return gdf
