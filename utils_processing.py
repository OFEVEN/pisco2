# -*- coding: utf-8 -*-
"""
utils_processing.py
=====================
Funciones de cálculo sobre el DataArray de precipitación PISCO (dims:
time, lat, lon):

  - Series diarias/mensuales por punto (nearest neighbor) o por cuenca
    (promedio espacial enmascarado con la geometría de la cuenca).
  - Climatología mensual y anual para un periodo dado.
  - Anomalías diaria, mensual y anual respecto a una climatología base.
  - Mapa de precipitación máxima diaria para un periodo dado.
  - Índice de Precipitación Antecedente (API), recursivo, para series
    puntuales o de cuenca.
"""

import numpy as np
import pandas as pd
import xarray as xr


# =============================================================================
# 1. SERIES POR PUNTO
# =============================================================================

def point_daily_series(da, lat, lon, tolerance=0.15):
    """
    Extrae la serie diaria de precipitación en el punto de grilla más
    cercano a (lat, lon). 'tolerance' es la distancia máxima (en grados)
    aceptada; si el punto cae fuera de la grilla de PISCO, lanza error.
    """
    try:
        serie = da.sel(lat=lat, lon=lon, method="nearest", tolerance=tolerance)
    except KeyError:
        raise ValueError(
            f"El punto (lat={lat}, lon={lon}) está fuera del dominio de "
            f"PISCO o demasiado lejos de la grilla disponible."
        )
    df = serie.to_series().rename("precip_mm").to_frame()
    df.index.name = "fecha"
    return df


def to_monthly(df_daily, col="precip_mm"):
    """Agrega una serie diaria a totales mensuales (suma)."""
    s = df_daily[col]
    monthly = s.resample("MS").sum(min_count=1)
    return monthly.rename("precip_mm_mensual").to_frame()


# =============================================================================
# 2. SERIE POR CUENCA (promedio espacial enmascarado)
# =============================================================================

def basin_mask(da, gdf):
    """
    Construye una máscara booleana (lat, lon) True dentro de la geometría
    de la cuenca (unión de todas las features del GeoDataFrame), usando
    regionmask.
    """
    import regionmask

    geom_union = gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") \
        else gdf.geometry.unary_union
    region = regionmask.Regions([geom_union])
    mask3d = region.mask_3D(da, lon_name="lon", lat_name="lat")
    return mask3d.isel(region=0)


def basin_daily_series(da, gdf):
    """
    Calcula el promedio espacial diario de precipitación dentro de la
    cuenca (máscara exacta de la geometría, no solo el rectángulo bbox).
    """
    mask = basin_mask(da, gdf)
    da_masked = da.where(mask)
    serie = da_masked.mean(dim=["lat", "lon"], skipna=True)
    df = serie.to_series().rename("precip_mm").to_frame()
    df.index.name = "fecha"
    return df


# =============================================================================
# 3. CLIMATOLOGÍA (mensual y anual) PARA UN PERIODO
# =============================================================================

def monthly_climatology_maps(da, start, end):
    """
    Climatología mensual (12 mapas): para cada mes calendario (1-12),
    el promedio de los totales mensuales de precipitación en el periodo
    [start, end].

    Retorna un DataArray con dimensión 'month' (1..12), (lat, lon).
    """
    sub = da.sel(time=slice(start, end))
    monthly_totals = sub.resample(time="MS").sum(min_count=1, skipna=True)
    clim = monthly_totals.groupby("time.month").mean(dim="time", skipna=True)
    return clim  # dims: month, lat, lon


def annual_climatology_map(da, start, end):
    """
    Climatología anual: promedio de los totales anuales de precipitación
    en el periodo [start, end]. Retorna un DataArray (lat, lon).
    """
    sub = da.sel(time=slice(start, end))
    annual_totals = sub.resample(time="YS").sum(min_count=1, skipna=True)
    clim = annual_totals.mean(dim="time", skipna=True)
    return clim  # dims: lat, lon


# =============================================================================
# 4. ANOMALÍAS
# =============================================================================

def daily_anomaly_map(da, target_date, baseline_start, baseline_end, window_days=7):
    """
    Anomalía diaria: valor observado en 'target_date' menos el promedio
    climatológico de ese día del año (+/- 'window_days' de ventana) sobre
    el periodo base [baseline_start, baseline_end].
    """
    target_date = pd.Timestamp(target_date)
    doy = target_date.dayofyear

    baseline = da.sel(time=slice(baseline_start, baseline_end))
    doy_all = baseline["time"].dt.dayofyear

    # Ventana circular alrededor del día juliano (maneja el cruce de año)
    diff = (doy_all - doy + 366) % 366
    window_mask = (diff <= window_days) | (diff >= 366 - window_days)

    climatologia = baseline.where(window_mask, drop=True).mean(dim="time", skipna=True)

    valor_obs = da.sel(time=target_date, method="nearest")
    anomalia = valor_obs - climatologia
    return anomalia, valor_obs, climatologia


def monthly_anomaly_map(da, year, month, baseline_start, baseline_end):
    """
    Anomalía mensual: total mensual observado (year-month) menos la
    climatología mensual de ese mes calendario en el periodo base.
    """
    target_start = pd.Timestamp(year=year, month=month, day=1)
    target_end = target_start + pd.offsets.MonthEnd(1)
    total_mes = da.sel(time=slice(target_start, target_end)).sum(dim="time", skipna=True)

    clim = monthly_climatology_maps(da, baseline_start, baseline_end)
    clim_mes = clim.sel(month=month)

    anomalia = total_mes - clim_mes
    return anomalia, total_mes, clim_mes


def annual_anomaly_map(da, year, baseline_start, baseline_end):
    """
    Anomalía anual: total anual observado (year) menos la climatología
    anual del periodo base.
    """
    target_start = pd.Timestamp(year=year, month=1, day=1)
    target_end = pd.Timestamp(year=year, month=12, day=31)
    total_anio = da.sel(time=slice(target_start, target_end)).sum(dim="time", skipna=True)

    clim = annual_climatology_map(da, baseline_start, baseline_end)

    anomalia = total_anio - clim
    return anomalia, total_anio, clim


# =============================================================================
# 5. PRECIPITACIÓN MÁXIMA DIARIA POR PERIODO
# =============================================================================

def max_daily_precip_map(da, start, end):
    """
    Precipitación máxima diaria registrada dentro del periodo [start, end].
    Útil para un mes específico (start=end del mes) o un año completo.
    """
    sub = da.sel(time=slice(start, end))
    max_map = sub.max(dim="time", skipna=True)
    # Fecha en que ocurrió el máximo, por celda (opcional, informativo)
    argmax_idx = sub.fillna(-9999).argmax(dim="time")
    fecha_max = sub["time"].isel(time=argmax_idx)
    return max_map, fecha_max


# =============================================================================
# 6. ÍNDICE DE PRECIPITACIÓN ANTECEDENTE (API)
# =============================================================================

def compute_api(df_daily, k=0.85, col="precip_mm", api_0=0.0):
    """
    Calcula el API recursivo sobre una serie diaria (punto o cuenca):
        API_t = k * API_(t-1) + P_t

    Retorna el mismo DataFrame con una columna adicional 'API'.
    """
    df = df_daily.copy().sort_index()
    api_vals = np.empty(len(df))
    api_prev = api_0
    precip_vals = df[col].fillna(0).values

    for i, p_t in enumerate(precip_vals):
        api_t = k * api_prev + p_t
        api_vals[i] = api_t
        api_prev = api_t

    df["API"] = api_vals
    df.attrs["k"] = k
    return df
