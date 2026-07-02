# -*- coding: utf-8 -*-
"""
utils_plot.py
==============
Funciones de graficado para mapas (precipitación, climatología, anomalías,
máximos) y series temporales (diarias/mensuales, API), recortadas al
dominio de Perú.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAS_CARTOPY = True
except ImportError:
    HAS_CARTOPY = False

PERU_BBOX = {"lon_min": -81.5, "lon_max": -68.0, "lat_min": -18.5, "lat_max": 0.5}


def plot_map(data_array, title, cmap="YlGnBu", vmin=0, vmax=None,
             units="mm", diverging=False, bbox=None):
    """
    Grafica un DataArray 2D (lat, lon) como mapa. Si 'diverging' es True,
    usa una paleta centrada en cero (para anomalías).
    Retorna la figura de matplotlib (para exportar o mostrar en Streamlit).
    """
    bbox = bbox or PERU_BBOX
    lon = data_array.lon.values
    lat = data_array.lat.values
    values = np.asarray(data_array.values)

    finite = values[np.isfinite(values)]
    if diverging:
        lim = np.nanpercentile(np.abs(finite), 98) if finite.size else 10
        vmin, vmax = -lim, lim
        cmap = cmap if cmap != "YlGnBu" else "RdBu"
        norm = mcolors.TwoSlopeNorm(vmin=vmin, vcenter=0, vmax=vmax)
    else:
        if vmax is None:
            vmax = np.nanpercentile(finite, 98) if finite.size else 10
            vmax = max(vmax, 1)
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

    if HAS_CARTOPY:
        fig = plt.figure(figsize=(6.5, 7.5))
        ax = plt.axes(projection=ccrs.PlateCarree())
        ax.set_extent([bbox["lon_min"], bbox["lon_max"], bbox["lat_min"], bbox["lat_max"]],
                       crs=ccrs.PlateCarree())
        mesh = ax.pcolormesh(lon, lat, values, cmap=cmap, norm=norm,
                              transform=ccrs.PlateCarree(), shading="auto")
        ax.add_feature(cfeature.BORDERS, linewidth=0.8)
        ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
        gl = ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.5)
        gl.top_labels = False
        gl.right_labels = False
        cbar = fig.colorbar(mesh, ax=ax, orientation="vertical", shrink=0.75, pad=0.05)
        cbar.set_label(units)
    else:
        fig, ax = plt.subplots(figsize=(6.5, 7.5))
        mesh = ax.pcolormesh(lon, lat, values, cmap=cmap, norm=norm, shading="auto")
        ax.set_xlabel("Longitud")
        ax.set_ylabel("Latitud")
        fig.colorbar(mesh, ax=ax, label=units)

    ax.set_title(title, fontsize=11, fontweight="bold")
    plt.tight_layout()
    return fig


def plot_timeseries(df, ycol, title, kind="line", ylabel="mm"):
    """Grafica una serie temporal (línea para diario/API, barras para mensual)."""
    fig, ax = plt.subplots(figsize=(9, 4))
    if kind == "bar":
        ax.bar(df.index, df[ycol], width=20, color="tab:blue")
    else:
        ax.plot(df.index, df[ycol], color="tab:blue", linewidth=1)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    return fig
