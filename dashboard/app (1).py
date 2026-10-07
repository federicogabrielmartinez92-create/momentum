"""
Dashboard de las estrategias con CEDEARs: Cartera de calidad y Momentum residual.
Se publica en Streamlit Community Cloud (privado: solo entran los mails invitados).

  * Cartera de calidad: la cartera que guarda el mail mensual (cartera_calidad.json) valuada con precios del día,
    la última revisión y el ranking (panel_calidad.json) y la historia del backtest 2011-2026 (historial_calidad.json).
  * Momentum residual: se recalcula en vivo con el mismo código del mail (momentum.py), incluyendo su backtest desde 2011.
"""
import json
import os
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

st.set_page_config(page_title="Estrategias CEDEAR", page_icon="📈", layout="wide")

# Configuración del momentum (los mismos valores que las variables de GitHub), en los "Secrets" de Streamlit.
for clave, defecto in (("MOMENTUM_INICIO", "2026-10-01"), ("MOMENTUM_CAPITAL", "10000"), ("MOMENTUM_EXCLUIR", "")):
    try:
        valor = st.secrets.get(clave, defecto)
    except Exception:           # noqa: BLE001
        valor = defecto
    os.environ.setdefault(clave, str(valor))

import calidad as C      # noqa: E402
import momentum as M     # noqa: E402
try:
    import screener as SCR   # noqa: E402  (copia del screener.py del otro repositorio, solo para leer las señales)
except ImportError:
    SCR = None

# Fecha de arranque de la cartera real del momentum: se lee de la configuración, NUNCA de M.INICIO, porque
# datos_momentum cambia M.INICIO un momento para calcular el backtest (si otra visita leía justo en ese momento,
# tomaba 2011 como inicio y mostraba el backtest como si fuera la cartera real).
INICIO_MOM_REAL = os.environ.get("MOMENTUM_INICIO") or "2026-10-01"
INICIO_BACKTEST_MOM = "2011-01-03"
AZUL, GRIS, NARANJA = "#2a78d6", "#8a8a8a", "#eb6834"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; max-width: 1400px;}
  div[data-testid="stMetricValue"] {font-size: 1.55rem;}
  .aviso {padding: .65rem 1rem; border-radius: .5rem; margin: .25rem 0 .8rem 0; font-size: .95rem;}
  .aviso-azul {background: rgba(42,120,214,.10); border-left: 4px solid #2a78d6;}
  .aviso-naranja {background: rgba(235,104,52,.10); border-left: 4px solid #eb6834;}
  .aviso-rojo {background: rgba(227,73,72,.10); border-left: 4px solid #e34948;}
  .aviso-verde {background: rgba(27,175,122,.10); border-left: 4px solid #1baf7a;}
  .aviso-violeta {background: rgba(142,91,214,.10); border-left: 4px solid #8e5bd6;}
  div[data-testid="stMetric"] {background: rgba(42,120,214,.06); border: 1px solid rgba(128,128,128,.18);
      border-left: 4px solid #2a78d6; border-radius: .6rem; padding: .55rem .85rem;}
  .leyenda {font-size: .85rem; margin: -.2rem 0 .6rem 0; line-height: 2;}
  .chip {display: inline-block; padding: .05rem .55rem; border-radius: 1rem; margin-right: .35rem; font-weight: 600; font-size: .85rem;}
</style>
""", unsafe_allow_html=True)

# ============================================================================ colores
VERDE, ROJO, AMARILLO, VIOLETA, CELESTE = "#1baf7a", "#e34948", "#d69a00", "#8e5bd6", "#2a78d6"
_FONDO = {"verde": (VERDE, "27,175,122"), "rojo": (ROJO, "227,73,72"), "naranja": (NARANJA, "235,104,52"),
          "amarillo": (AMARILLO, "214,154,0"), "azul": (CELESTE, "42,120,214"), "violeta": (VIOLETA, "142,91,214"),
          "gris": (GRIS, "138,138,138")}


def css_color(nombre):
    """Estilo de celda: fondo suave y letra del color."""
    if nombre not in _FONDO:
        return ""
    txt, rgb = _FONDO[nombre]
    return f"background-color: rgba({rgb},.16); color: {txt}; font-weight: 600"


def chip(texto, nombre):
    txt, rgb = _FONDO[nombre]
    return f"<span class='chip' style='background: rgba({rgb},.16); color: {txt}'>{texto}</span>"


# Tipo de movimiento: (prefijo, ícono, color). Se busca por prefijo, en este orden.
ORDENES = [("ROTAR", "🔄", "violeta"), ("VENDER", "🔴", "rojo"), ("COMPRAR", "🟢", "verde"), ("RECORTAR", "✂️", "naranja"),
           ("SUMAR", "➕", "azul"), ("REFORZAR", "➕", "azul")]


def _orden(v):
    for pre, ico, col in ORDENES:
        if str(v).startswith(pre):
            return ico, col
    return "", ""


def leyenda_ordenes(tipos=None):
    usados = [(p, i, c) for p, i, c in ORDENES if p != "REFORZAR" and (tipos is None or any(str(t).startswith(p) for t in tipos))]
    st.markdown("<div class='leyenda'>" + "".join(chip(f"{i} {p.capitalize()}", c) for p, i, c in usados) + "</div>",
                unsafe_allow_html=True)


def por_prefijo(mapa):
    """mapa: {prefijo del texto: color}. Devuelve la función de estilo para una columna de texto."""
    def f(v):
        s = str(v).lower()
        for pre, col in mapa.items():
            if s.startswith(pre):
                return css_color(col)
        return ""
    return f


def color_signo(v):
    try:
        v = float(str(v).replace("%", "").replace(",", ".").replace("+", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return ""
    if np.isnan(v) or abs(v) < 0.05:
        return ""
    return f"color: {VERDE if v > 0 else ROJO}; font-weight: 600"


def _fmt_num(f):
    def g(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return ""
        return (f % v).replace(".", ",")
    return g


def _fmt_fecha_corta(v):
    return "" if v is None or pd.isna(v) else pd.Timestamp(v).strftime("%d/%m/%Y")


TESIS_COLOR = por_prefijo({"✓": "verde", "⚠": "amarillo", "✗": "rojo", "sin datos": "gris"})
SI_NO_COLOR = por_prefijo({"✓": "verde", "✗": "rojo"})
ORIGEN_COLOR = por_prefijo({"sistema real": "violeta", "backtest": "gris"})
SITUACION_CALIDAD = por_prefijo({"en cartera": "azul", "comprable": "verde", "tendencia": "rojo", "precio": "naranja", "fuera": "gris"})
SITUACION_MOM = por_prefijo({"en cartera": "azul", "fuera": "gris"})


def tabla(df, fmt=None, signo=(), estilos=None, fechas=(), orden=None, config=None, height=None):
    """Tabla con colores.
    fmt: {columna: '%+.1f%%'} · signo: columnas en verde (positivo) o rojo (negativo) · estilos: {columna: función valor -> css}
    fechas: columnas de fecha (dd/mm/aaaa) · orden: columna con el tipo de movimiento (ícono y color) · config: column_config."""
    df = df.reset_index(drop=True).copy()
    fm = {c: (f if callable(f) else _fmt_num(f)) for c, f in (fmt or {}).items() if c in df}
    for c in list(fm):
        if df[c].isna().any():          # columna con huecos: se pasa a texto ya formateado
            f = fm.pop(c)
            df[c] = [f(v) if pd.notna(v) else "" for v in df[c]]
    for c in fechas:
        if c in df:
            fm[c] = _fmt_fecha_corta
    if orden and orden in df:
        fm[orden] = lambda v: f"{_orden(v)[0]} {v}".strip()
    sty = df.style.format(fm, na_rep="")
    cols = [c for c in signo if c in df]
    if cols:
        sty = sty.map(color_signo, subset=cols)
    for c, f in (estilos or {}).items():
        if c in df:
            sty = sty.map(f, subset=[c])
    if orden and orden in df:
        sty = sty.map(lambda v: css_color(_orden(v)[1]), subset=[orden])
    kw = {"height": height} if height else {}
    config = dict(config or {})
    if orden and orden in df and orden not in config:
        config[orden] = st.column_config.Column(width="medium")
    st.dataframe(sty, hide_index=True, width="stretch", column_config=config, **kw)


# ============================================================================ utilidades
def fmt_fecha(d):
    d = pd.Timestamp(d)
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def usd(v):
    return "—" if v is None or pd.isna(v) else "USD " + f"{v:,.0f}".replace(",", ".")


def pct(v, dec=1, signo=True):
    if v is None or pd.isna(v):
        return "—"
    return (f"{v:+.{dec}f}%" if signo else f"{v:.{dec}f}%").replace(".", ",")


def txt_pct(serie, dec=0):
    """Columna de % como texto (vacío si no hay dato), para no mostrar 'None'."""
    return [pct(v, dec) if v is not None and pd.notna(v) else "" for v in pd.to_numeric(serie, errors="coerce")]


def delta_pts(a, b):
    """Diferencia en puntos contra el S&P, o nada si todavía es cero."""
    if a is None or b is None or pd.isna(a) or pd.isna(b) or abs(a - b) < 0.05:
        return None
    return f"{pct(a - b)} vs S&P".replace("%", " pts")


def delta_usd(g):
    if g is None or pd.isna(g) or abs(g) < 0.5:
        return None
    return ("USD +" if g > 0 else "USD -") + f"{abs(g):,.0f}".replace(",", ".")


def aviso(texto, tipo="azul"):
    st.markdown(f"<div class='aviso aviso-{tipo}'>{texto}</div>", unsafe_allow_html=True)


def habil(d):
    return d.weekday() < 5


def proxima_revision_calidad(hoy, ultima_oficial):
    for k in range(0, 3):
        y, m = (hoy.year + (hoy.month - 1 + k) // 12, (hoy.month - 1 + k) % 12 + 1)
        d = date(y, m, C.DIA_REVISION)
        while not habil(d):
            d += timedelta(days=1)
        hecha = ultima_oficial and ultima_oficial[:7] == d.isoformat()[:7]
        if d >= hoy and not hecha:
            return d
    return None


def proxima_operacion_momentum(hoy):
    for k in range(0, 2):
        y, m = (hoy.year + (hoy.month - 1 + k) // 12, (hoy.month - 1 + k) % 12 + 1)
        d = date(y, m, 1)
        while not habil(d):
            d += timedelta(days=1)
        if d >= hoy:
            return d
    return None


def stats_serie(s):
    s = s.dropna()
    if len(s) < 20:
        return {}
    anios = (s.index[-1] - s.index[0]).days / 365.25
    r = s.pct_change().dropna()
    per_anio = 252 if len(s) / max(anios, 0.1) > 100 else 12
    return {"anual": ((s.iloc[-1] / s.iloc[0]) ** (1 / anios) - 1) * 100, "caida": (s / s.cummax() - 1).min() * 100,
            "vol": r.std() * np.sqrt(per_anio) * 100, "total": (s.iloc[-1] / s.iloc[0] - 1) * 100}


def anual_desde(series):
    """series: dict nombre -> Serie de valores. Devuelve DataFrame año x nombre en %."""
    df = pd.DataFrame(series)
    ye = df.resample("YE").last()
    ye = pd.concat([df.iloc[[0]], ye])
    out = (ye.pct_change().iloc[1:] * 100)
    out.index = out.index.year
    out.index.name = "Año"
    return out[~out.index.duplicated(keep="last")]


# ============================================================================ gráficos
def grafico_evolucion(df, colores, log=False, marca=None, alto=320):
    """df: índice fecha, columnas = series (máx. 3). marca: (fecha, texto) para una línea vertical."""
    d = df.copy()
    d.index.name = "Fecha"
    d = d.reset_index().melt("Fecha", var_name="Serie", value_name="Valor").dropna()
    esc = alt.Scale(domain=list(colores), range=list(colores.values()))
    base = alt.Chart(d).encode(x=alt.X("Fecha:T", title=None, axis=alt.Axis(format="%Y" if log else "%b %Y", grid=False)))
    y = alt.Y("Valor:Q", title=None, scale=alt.Scale(type="log" if log else "linear", zero=False),
              axis=alt.Axis(format="~s", gridOpacity=0.25))
    lineas = base.mark_line(strokeWidth=2).encode(y=y, color=alt.Color("Serie:N", scale=esc, legend=alt.Legend(orient="top", title=None)))
    cerca = alt.selection_point(nearest=True, on="pointerover", fields=["Fecha"], empty=False)
    puntos = base.mark_point(size=55, filled=True).encode(
        y=y, color=alt.Color("Serie:N", scale=esc, legend=None), opacity=alt.condition(cerca, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("Fecha:T", format="%d/%m/%Y"), "Serie:N", alt.Tooltip("Valor:Q", format=",.0f", title="USD")]).add_params(cerca)
    regla = base.mark_rule(color="#999").encode(opacity=alt.condition(cerca, alt.value(0.5), alt.value(0))).transform_filter(cerca)
    capas = lineas + puntos + regla
    if marca:
        m = pd.DataFrame({"Fecha": [pd.Timestamp(marca[0])], "txt": [marca[1]]})
        capas += alt.Chart(m).mark_rule(strokeDash=[3, 3], color="#777").encode(x="Fecha:T", tooltip=["txt:N"])
    st.altair_chart(capas.properties(height=alto), width="stretch")


def grafico_anual(an, colores):
    """an: DataFrame año x serie (%)."""
    d = an.copy()
    d.index.name = "Año"
    d = d.reset_index().melt("Año", var_name="Serie", value_name="Rend").dropna()
    d["Año"] = d["Año"].astype(str)
    esc = alt.Scale(domain=list(colores), range=list(colores.values()))
    ch = alt.Chart(d).mark_bar(cornerRadiusEnd=3, size=9).encode(
        x=alt.X("Año:N", title=None, axis=alt.Axis(labelAngle=0)), xOffset="Serie:N",
        y=alt.Y("Rend:Q", title="% en el año", axis=alt.Axis(gridOpacity=0.25)),
        color=alt.Color("Serie:N", scale=esc, legend=alt.Legend(orient="top", title=None)),
        tooltip=["Año:N", "Serie:N", alt.Tooltip("Rend:Q", format="+.1f", title="%")])
    cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#999").encode(y="y:Q")
    st.altair_chart((ch + cero).properties(height=280), width="stretch")


PALETA_SECTORES = ["#2a78d6", "#1baf7a", "#eb6834", "#8e5bd6", "#d69a00", "#e34948", "#17a2b8", "#c2569c", "#6b8e23", "#8c6d4f"]


def grafico_pesos(pesos, objetivo, tope, etiqueta_tope, sector_fn=None):
    d = pesos.sort_values(ascending=False).reset_index()
    d.columns = ["Acción", "Peso"]
    d["Sector"] = [("Liquidez" if str(t).startswith("SPY") else sector_fn(t)) if sector_fn else "" for t in d["Acción"]]
    sectores = [s for s in dict.fromkeys(d["Sector"]) if s != "Liquidez"]
    dom = sectores + (["Liquidez"] if "Liquidez" in set(d["Sector"]) else [])
    rng = [PALETA_SECTORES[i % len(PALETA_SECTORES)] for i in range(len(sectores))] + (["#b8b8b8"] if "Liquidez" in dom else [])
    color = (alt.Color("Sector:N", scale=alt.Scale(domain=dom, range=rng), legend=alt.Legend(orient="top", title=None))
             if sector_fn else alt.value(AZUL))
    barras = alt.Chart(d).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=26).encode(
        x=alt.X("Acción:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Peso:Q", title="% de la cartera", scale=alt.Scale(domain=[0, max(tope + 3, float(d["Peso"].max()) + 3)]),
                axis=alt.Axis(gridOpacity=0.25)),
        color=color,
        tooltip=["Acción:N", "Sector:N", alt.Tooltip("Peso:Q", format=".1f", title="% de la cartera")])
    reglas = alt.Chart(pd.DataFrame({"y": [objetivo, tope], "Línea": [f"objetivo {objetivo:.0f}%", etiqueta_tope]})).mark_rule(
        strokeDash=[4, 4], color="#777").encode(y="y:Q", tooltip=["Línea:N"])
    st.altair_chart((barras + reglas).properties(height=250), width="stretch")
    st.caption(f"Cada color es un sector. Líneas punteadas: objetivo {objetivo:.0f}% por posición y {etiqueta_tope} (si lo supera, se recorta).")


# ============================================================================ tablas comunes
def tabla_anual(an, nombre_cartera):
    t = an.copy()
    t["Diferencia"] = t[nombre_cartera] - t["S&P 500"]
    t["¿Gana al S&P?"] = np.where(t["Diferencia"] > 0, "✓ sí", "✗ no")
    t.index.name = "Año"
    t = t.reset_index()
    nums = [k for k in t.columns if k not in ("Año", "¿Gana al S&P?")]
    tabla(t, fmt={"Año": "%d", **{k: "%+.1f%%" for k in nums}}, signo=nums, estilos={"¿Gana al S&P?": SI_NO_COLOR},
          height=36 * (len(t) + 1) + 3)
    gana = (t["Diferencia"] > 0).sum()
    st.caption(f"Le ganó al S&P en {gana} de {len(t)} años. Verde = ganancia o mejor que el S&P · rojo = pérdida o peor que el S&P.")


def historial_con_filtros(df, clave, nombre_fn):
    """df con columnas Fecha, Orden, Acción, Peso (0-1), Resultado (0-1), Motivo, Origen."""
    if not len(df):
        st.info("Todavía no hay operaciones.")
        return
    df = df.copy()
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1.4])
    anios = sorted(int(a) for a in df["Fecha"].dt.year.unique())
    rango = c1.select_slider("Años", options=anios, value=(anios[0], anios[-1]), key=f"{clave}_anios") if len(anios) > 1 else (anios[0], anios[0])
    tipos = c2.multiselect("Tipo de movimiento", sorted(df["Orden"].unique()), key=f"{clave}_tipos", placeholder="Todos")
    acciones = c3.multiselect("Acción", sorted(df["Acción"].unique()), key=f"{clave}_acc", placeholder="Todas")
    origenes = sorted(df["Origen"].unique())
    origen = c4.selectbox("Origen", ["Todos"] + origenes, key=f"{clave}_origen") if len(origenes) > 1 else "Todos"
    f = df[(df["Fecha"].dt.year >= rango[0]) & (df["Fecha"].dt.year <= rango[1])]
    if tipos:
        f = f[f["Orden"].isin(tipos)]
    if acciones:
        f = f[f["Acción"].isin(acciones)]
    if origen != "Todos":
        f = f[f["Origen"] == origen]
    f = f.sort_values("Fecha", ascending=False).copy()
    f.insert(3, "Empresa", [nombre_fn(t) for t in f["Acción"]])
    f["Peso"] = pd.to_numeric(f["Peso"], errors="coerce") * 100
    f["Resultado"] = pd.to_numeric(f["Resultado"], errors="coerce") * 100
    cuenta = f["Orden"].map(lambda v: next((p for p, _, _ in ORDENES if str(v).startswith(p)), str(v))).value_counts()
    st.markdown(f"<div class='leyenda'><b>{len(f)} movimientos:</b> " + "".join(
        chip(f"{_orden(p)[0]} {p.capitalize()} {n}", _orden(p)[1] or "gris") for p, n in cuenta.items()) + "</div>",
        unsafe_allow_html=True)
    tabla(f[["Fecha", "Origen", "Orden", "Acción", "Empresa", "Peso", "Resultado", "Motivo"]],
          fmt={"Peso": "%.1f%%", "Resultado": "%+.0f%%"}, signo=["Resultado"], fechas=["Fecha"], orden="Orden",
          estilos={"Origen": ORIGEN_COLOR}, height=min(36 * (len(f) + 1) + 3, 560), config={
              "Peso": st.column_config.Column("% de la cartera"),
              "Resultado": st.column_config.Column("Resultado", help="Solo en ventas: ganancia o pérdida de la posición"),
              "Motivo": st.column_config.Column(width="large")})


def ventas_con_stats(v, nombre_fn, nota_motivo=None):
    """v: Acción, Compra, Venta, Resultado (0-1), Motivo, [Origen]."""
    if not len(v):
        st.info("Todavía no hubo ventas.")
        return
    v = v.copy()
    v["Compra"], v["Venta"] = pd.to_datetime(v["Compra"]), pd.to_datetime(v["Venta"])
    v["Años"] = (v["Venta"] - v["Compra"]).dt.days / 365.25
    v["Resultado"] = pd.to_numeric(v["Resultado"], errors="coerce") * 100
    gan, per = (v["Resultado"] > 0).sum(), (v["Resultado"] <= 0).sum()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Ventas", len(v))
    c2.metric("Con ganancia", pct(gan / len(v) * 100, 0, False), delta=f"{per} de {len(v)} con pérdida", delta_color="off")
    c3.metric("Resultado promedio", pct(v["Resultado"].mean(), 0), delta=pct(v["Resultado"].median(), 0) + " la del medio")
    c4.metric("Mejor", v.loc[v["Resultado"].idxmax(), "Acción"], delta=pct(v["Resultado"].max(), 0))
    c5.metric("Peor", v.loc[v["Resultado"].idxmin(), "Acción"], delta=pct(v["Resultado"].min(), 0))
    v.insert(1, "Empresa", [nombre_fn(t) for t in v["Acción"]])
    v = v.sort_values("Venta", ascending=False)
    v["¿Ganó?"] = np.where(v["Resultado"] > 0, "✓ ganó", "✗ perdió")
    cols = ["Acción", "Empresa", "Compra", "Venta", "Años", "Resultado", "¿Ganó?", "Motivo"] + (["Origen"] if "Origen" in v else [])
    tabla(v[cols], fmt={"Años": "%.1f", "Resultado": "%+.0f%%"}, signo=["Resultado"], fechas=["Compra", "Venta"],
          estilos={"¿Ganó?": SI_NO_COLOR, "Origen": ORIGEN_COLOR}, height=min(36 * (len(v) + 1) + 3, 520),
          config={"Motivo": st.column_config.Column(nota_motivo or "Motivo", width="large")})


# ============================================================================ datos
def ultimo_cierre():
    """Fecha del último cierre de Nueva York que ya debería estar publicado (16:45 hora de NY en adelante, días
    hábiles). Se usa como parte de la memoria de los datos: cuando hay un cierre nuevo, se vuelven a calcular solos."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ahora = datetime.now(ZoneInfo("America/New_York"))
    d = ahora.date()
    if ahora.weekday() >= 5 or (ahora.hour, ahora.minute) < (16, 45):
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


@st.cache_data(ttl=3600, show_spinner=False)
def precios_ajustados(tickers, desde, cierre=None):
    datos = yf.download(list(tickers) + ["SPY"], start=desde, auto_adjust=True, group_by="ticker", progress=False, threads=True)
    out = {}
    for t in list(tickers) + ["SPY"]:
        try:
            s = datos[t]["Close"].dropna()
            if s.index.tz is not None:
                s.index = s.index.tz_localize(None)
            out[t] = s
        except (KeyError, TypeError):
            pass
    px = pd.DataFrame(out)
    return px.reindex(px["SPY"].dropna().index).ffill()


def leer_json(nombre):
    p = RAIZ / nombre
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


_CANDADO_MOM = threading.Lock()      # momentum.py usa una variable global para la fecha de inicio: un cálculo por vez


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def datos_momentum(inicio_real, cierre=None):
    with _CANDADO_MOM:
        try:
            M.INICIO = INICIO_BACKTEST_MOM
            px, vo = M.descargar()
            motor = M.Motor(px, vo)
            bt = M.simular(motor)
            M.INICIO = inicio_real
            real = M.simular(motor)
        finally:
            M.INICIO = inicio_real
    k = len(motor.idx) - 1
    rk = motor.ranking(k)
    precios = px.iloc[k]

    def paquete(res):
        hold, caja, serie, spy, historial, cerradas, _ = res
        valor = caja + sum(h["cant"] * precios[t] for t, h in hold.items())
        cart = pd.DataFrame([{"Acción": t, "Empresa": M.nombre(t), "CEDEAR": M.cedear(t), "Sector": M.SECTOR.get(t, "Otros"),
                              "Desde": pd.Timestamp(h["compra"]).date(), "Peso %": h["cant"] * precios[t] / valor * 100,
                              "Resultado %": (h["cant"] * precios[t] / h["costo"] - 1) * 100, "Puesto": rk["Puesto"].get(t, np.nan)}
                             for t, h in hold.items()], columns=["Acción", "Empresa", "CEDEAR", "Sector", "Desde", "Peso %", "Resultado %", "Puesto"])
        h = historial.copy()
        if len(h):
            base = serie.shift(1).bfill()
            h["Fecha"] = pd.to_datetime(h["Mail"])
            h["Peso"] = [m / base.asof(f) if pd.notna(base.asof(f)) else np.nan for m, f in zip(h["Monto"], h["Fecha"])]
            h["Resultado"] = h["Resultado %"] / 100
        cer = cerradas.copy()
        if len(cer):
            cer["Resultado"] = cer["Resultado %"] / 100
        return dict(hold=hold, caja=caja, serie=serie, spy=spy, historial=h, cerradas=cer, cart=cart, valor=valor)
    B, R = paquete(bt), paquete(real)
    hold2, caja2, ords, _ = M.aplicar_reglas(R["hold"], R["caja"], rk, precios, pd.Timestamp(date.today()))
    return dict(cierre=motor.idx[-1], rk=rk, ords=ords, hold2=hold2, bt=B, real=R)



# ============================================================================ mezcla con el S&P
def mezclar(c, s_, w):
    """Cartera con w en calidad y (1 - w) en el S&P, rebalanceada una vez por año (al empezar cada año)."""
    rc, rs = c.pct_change().fillna(0), s_.pct_change().fillna(0)
    vc, vs = 10000 * w, 10000 * (1 - w)
    anio, out = c.index[0].year, []
    for d, a, b in zip(c.index, rc, rs):
        if d.year != anio:
            t = vc + vs
            vc, vs, anio = t * w, t * (1 - w), d.year
        vc *= 1 + a
        vs *= 1 + b
        out.append(vc + vs)
    return pd.Series(out, index=c.index)


def resumen_serie(v, spy):
    st_ = stats_serie(v)
    an = anual_desde({"x": v, "s": spy})
    return {"anual": st_.get("anual"), "final": v.iloc[-1], "caida": st_.get("caida"), "peor_anio": an["x"].min(),
            "gana": int((an["x"] > an["s"]).sum()), "anios": len(an)}


def tab_mezcla(comb, pesos_vivos, caja_pct):
    st.markdown("La cartera de calidad son 10 acciones. Tener además una **base fija en el S&P 500** (el CEDEAR de SPY) no evita "
                "las caídas del mercado, pero **amortigua los años en que la selección sale mal**. Acá se ve cómo habría andado cada "
                "mezcla, rebalanceando una vez por año, y cuánto poner en cada papel para un cliente.")
    try:
        defecto = int(float(st.secrets.get("MEZCLA_CALIDAD", 70)))
    except Exception:           # noqa: BLE001
        defecto = 70
    opciones = [50, 60, 70, 80, 90, 100]
    defecto = defecto if defecto in opciones else 70
    w = st.select_slider("Parte en las 10 acciones de calidad", options=opciones, value=defecto, key="mezcla_w",
                         format_func=lambda v: f"{v}% calidad · {100 - v}% S&P")
    d = comb[["Cartera de calidad", "S&P 500"]].dropna()
    c, spy = d["Cartera de calidad"], d["S&P 500"]
    nom = f"Mezcla {w}/{100 - w}"
    mz = mezclar(c, spy, w / 100)
    R, Rc, Rs = resumen_serie(mz, spy), resumen_serie(c, spy), resumen_serie(spy, spy)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"{nom}: rendimiento anual", pct(R["anual"], 1, False), delta=delta_pts(R["anual"], Rs["anual"]),
              help="Abajo: cuántos puntos por año le gana al S&P")
    k2.metric("USD 10.000 →", usd(R["final"]), delta=f"x{R['final'] / 10000:.1f} el capital".replace(".", ","))
    k3.metric("Peor caída", pct(R["caida"], 1), delta=f"{pct(Rc['caida'], 1)} solo calidad", delta_color="off",
              help="Medida con datos de fin de mes")
    k4.metric("Peor año", pct(R["peor_anio"], 1), delta=f"{pct(Rc['peor_anio'], 1)} solo calidad", delta_color="off")
    grafico_evolucion(pd.DataFrame({nom: mz, "Cartera de calidad": c, "S&P 500": spy}),
                      {nom: VERDE, "Cartera de calidad": AZUL, "S&P 500": GRIS})
    st.caption("USD 10.000 desde enero de 2011: backtest y, después, el sistema real con las mismas reglas. La mezcla se rebalancea "
               "al empezar cada año para volver a los porcentajes elegidos.")

    st.subheader("Todas las mezclas", divider="green")
    filas = []
    for wi in opciones + [0]:
        v = mezclar(c, spy, wi / 100) if wi else spy
        r = resumen_serie(v, spy)
        filas.append({"Mezcla": "100% S&P" if wi == 0 else f"{wi}% calidad · {100 - wi}% S&P", "Anual %": r["anual"],
                      "USD 10.000 →": r["final"], "Peor caída %": r["caida"], "Peor año %": r["peor_anio"],
                      "Diferencia vs S&P (pts por año)": None if wi == 0 else r["anual"] - Rs["anual"],
                      "": "◀ elegida" if wi == w else ""})
    tabla(pd.DataFrame(filas), fmt={"Anual %": "%.1f%%", "USD 10.000 →": lambda v: usd(v), "Peor caída %": "%+.1f%%",
                                    "Peor año %": "%+.1f%%", "Diferencia vs S&P (pts por año)": "%+.1f"},
          signo=["Peor caída %", "Peor año %", "Diferencia vs S&P (pts por año)"],
          estilos={"": lambda v: css_color("verde") if v else ""}, height=36 * 8 + 3)
    st.caption("Más S&P = menos rendimiento en el backtest, pero caídas algo menores y menos dependencia de que la selección acierte. "
               "El rendimiento del backtest seguramente está inflado (lista de hoy, CEDEARs que no existían), así que el costo real de "
               "tener S&P es probablemente menor que el que muestra la tabla.")

    st.subheader(f"Año por año: {nom}", divider="gray")
    an = anual_desde({nom: mz, "S&P 500": spy})
    grafico_anual(an, {nom: VERDE, "S&P 500": GRIS})
    tabla_anual(an, nom)

    st.subheader("Calculadora para un cliente", divider="blue")
    monto = st.number_input("Monto total del cliente (USD)", min_value=0.0, value=10000.0, step=1000.0, format="%.0f", key="mz_monto")
    filas = [{"Papel": "SPY", "Empresa": "S&P 500 (base fija)" + (" + liquidez del sistema" if caja_pct > 0.05 else ""),
              "% del total": (100 - w) + w * caja_pct / 100, "USD": monto * ((100 - w) + w * caja_pct / 100) / 100}]
    for t, pw in sorted(pesos_vivos.items(), key=lambda x: -x[1]):
        filas.append({"Papel": t, "Empresa": C.nombre(t), "% del total": w * pw / 100, "USD": monto * w * pw / 10000})
    tabla(pd.DataFrame(filas), fmt={"% del total": "%.1f%%", "USD": lambda v: usd(v)},
          estilos={"Papel": lambda v: css_color("gris") if v == "SPY" else css_color("azul")}, height=36 * (len(filas) + 1) + 3)
    st.caption(f"Las 10 acciones van con los mismos pesos que la cartera del sistema, escalados al {w}%. Para un cliente nuevo, entrar "
               "en 3 tramos (un tercio por mes).")

    st.markdown("**Rebalanceo anual (en enero):** cargá cuánto tiene hoy el cliente en cada parte.")
    r1, r2 = st.columns(2)
    v_acc = r1.number_input("Valor de las 10 acciones (USD)", min_value=0.0, value=float(round(monto * w / 100)), step=500.0,
                            format="%.0f", key="mz_acc")
    v_spy = r2.number_input("Valor en SPY (USD)", min_value=0.0, value=float(round(monto * (100 - w) / 100)), step=500.0,
                            format="%.0f", key="mz_spy")
    tot = v_acc + v_spy
    if tot > 0:
        actual = v_acc / tot * 100
        mover = v_acc - tot * w / 100
        if abs(actual - w) < 3:
            aviso(f"✓ Está en {pct(actual, 0, False)} acciones / {pct(100 - actual, 0, False)} S&amp;P: cerca del objetivo "
                  f"({w}/{100 - w}). <b>No hace falta rebalancear</b> (se hace si se desvía 3 puntos o más).", "verde")
        elif mover > 0:
            aviso(f"Está en {pct(actual, 0, False)} acciones. Para volver a {w}/{100 - w}: <b>vender {usd(mover)} de las acciones "
                  "y comprar SPY</b>, en proporción a lo que pesa cada una (o sacarlo de las que más crecieron).", "naranja")
        else:
            aviso(f"Está en {pct(actual, 0, False)} acciones. Para volver a {w}/{100 - w}: <b>vender {usd(-mover)} de SPY y "
                  "comprar acciones</b>, empezando por las que están más lejos de su peso.", "azul")
        st.caption("Si el cliente aporta plata, conviene ponerla primero en la parte que quedó por debajo del objetivo: así se "
                   "rebalancea sin vender.")

# ============================================================================ página: calidad
REGLAS_CALIDAD = """
**La idea:** tener siempre 10 empresas de calidad (muy rentables, que crecen, con poca deuda y que generan caja), comprarlas a un
precio razonable, dejar correr a las ganadoras y vender solo cuando el negocio se deteriora. Datos: balances anuales de los últimos
5 años de la SEC de EE.UU., los mismos que usó el backtest.

1. **Filtros mínimos:** ROIC promedio ≥ 12% (bancos: ROE), deuda ≤ 3 veces el EBITDA, que genere caja, ventas creciendo ≥ 5% anual,
   dilución ≤ 3% anual y más de USD 20 M operados por día.
2. **Puntaje de calidad (0-100):** rentabilidad 25%, crecimiento de ventas 15%, crecimiento de caja por acción 15%, margen bruto 10%,
   conversión en caja 10%, poca deuda 10%, poca dilución 5% y precio 10%.
3. **Precio:** rendimiento esperado a 10 años (caja sobre valor de mercado, crecimiento que se va frenando, venta final a 25 veces).
   Menos de 5% anual = precio extremo.
4. **Tendencia:** momentum residual, en percentil de 0 a 100.
5. **Qué se compra:** entre las 20 mejores en calidad, ranking combinado de 50% calidad, 25% precio y 25% tendencia. Máximo 3 por sector.

| Movimiento | Cuándo | Qué hace |
|---|---|---|
| **Comprar** | Hay un lugar libre | Entra la mejor del ranking combinado con 10% |
| **Vender** | Se rompe la tesis | ROIC debajo de 10%, ventas creciendo menos de 3% u otro filtro mínimo: se vende entera |
| **Rotar** | Feb, may, ago y nov | Si cayó del puesto 20 o está en la zona de tolerancia, se cambia por la mejor del ranking (máx. 2). La que entra recibe como mucho 10% |
| **Recortar** | Creció demasiado o está carísima | Más de 25% baja a 20%; precio extremo y más de 12,5% baja a 10% |
| **Sumar** | Sobra plata | Completa hacia el 10% las posiciones por debajo de 8,5% |
| **Nunca** | Por una caída de precio | Si cae más de 25% contra el S&P, lo revisa el equipo |

**Zona de tolerancia:** para comprar se pide ROIC de 12% y ventas creciendo 5%; para seguir en cartera alcanza con 10% y 3%. Entre medio
no se vende ni se suma. Las extranjeras con normas internacionales (TSMC, ASML, SAP y otras) se valúan en dólares.
Quedan afuera seis empresas con datos poco confiables (Ford, GM, JD,
Alibaba, Baidu y NIO). Costos: 0,5% por operación. Análisis cuantitativo con fines educativos; no es una recomendación de inversión.
"""


def pagina_calidad():
    st.title("Cartera de calidad")
    st.caption("10 empresas de calidad para el largo plazo · revisión mensual el primer día hábil desde el 15 · mismo programa y datos "
               "que el backtest 2011-2026")
    E_arch = leer_json("cartera_calidad.json")
    if not E_arch:
        st.error("No encuentro cartera_calidad.json en el repositorio.")
        return
    panel, H = leer_json("panel_calidad.json"), leer_json("historial_calidad.json")
    # Dos carteras: la REAL (arranca de cero en la primera revisión desde INICIO_REAL_CAL) y la que viene del BACKTEST
    # desde 2011 y sigue con las mismas reglas. Antes del arranque, cartera_calidad.json todavía es la del backtest.
    INICIO_REAL_CAL = getattr(C, "INICIO_REAL", "2026-10-15")
    antes_real = str(E_arch.get("origen") or "").startswith("backtest")
    Eb0 = E_arch if antes_real else leer_json("cartera_calidad_backtest.json")
    Er0 = None if antes_real else E_arch
    E0 = Er0 if Er0 is not None else C.estado_nuevo()
    todas = set(E0["posiciones"]) | set((Eb0 or {}).get("posiciones", {}))
    entradas = [p["fecha_entrada"] for p in E0["posiciones"].values()] + [x for x in (E0.get("ultima_fecha"), (Eb0 or {}).get("ultima_fecha")) if x]
    entradas += [p["fecha_entrada"] for p in (Eb0 or {}).get("posiciones", {}).values()]
    desde = (min([pd.Timestamp(d) for d in entradas] or [pd.Timestamp(date.today()) - pd.Timedelta(days=400)])
             - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    with st.spinner("Actualizando precios..."):
        px = precios_ajustados(tuple(sorted(todas)), desde, ultimo_cierre())
    E = C.actualizar_valores(E0, px) if E0["ultima_fecha"] else E0
    Eb = C.actualizar_valores(Eb0, px) if Eb0 else None
    valor = E["caja"] + sum(p["valor"] for p in E["posiciones"].values())
    valor_b = Eb["caja"] + sum(p["valor"] for p in Eb["posiciones"].values()) if Eb else None
    cap = E.get("capital", 10000)
    ult = pd.Timestamp(px.index[-1])
    hoy = date.today()
    prox = proxima_revision_calidad(hoy, E0.get("ultima_oficial"))
    tesis = (panel or {}).get("tesis", {}) if not antes_real else {}
    rank = pd.DataFrame((panel or {}).get("ranking", []))
    castigadas = set(rank.loc[rank["castigada"], "Acción"]) if len(rank) else set()
    arranco = bool(E["posiciones"])
    pesos_vivos = {t: p["valor"] / valor * 100 for t, p in E["posiciones"].items()} if arranco else {}
    pesos_bt = {t: p["valor"] / valor_b * 100 for t, p in Eb["posiciones"].items()} if Eb else {}

    def evo_de(Ex, v_hoy):
        ev = pd.DataFrame(Ex.get("evolucion", []), columns=["fecha", "cartera", "spy"])
        ev = pd.concat([ev, pd.DataFrame([{"fecha": ult.strftime("%Y-%m-%d"), "cartera": v_hoy, "spy": Ex["spy_ref"]}])])
        ev = ev.drop_duplicates("fecha", keep="last")
        ev.index = pd.to_datetime(ev.pop("fecha"))
        return ev.sort_index()

    evo_real = evo_de(E, valor) if arranco else pd.DataFrame(columns=["cartera", "spy"])
    evo_bt = evo_de(Eb, valor_b) if Eb else None
    # serie del backtest desde 2011 + su continuación con las mismas reglas (escalada para que sea continua)
    comb = None
    if H:
        hb = pd.DataFrame(H["evolucion"])
        hb.index = pd.to_datetime(hb.pop("fecha"))
        f_c, f_s = hb["cartera"].iloc[-1] / cap, hb["spy"].iloc[-1] / cap
        cont = evo_bt[evo_bt.index > hb.index[-1]] if evo_bt is not None else evo_real[evo_real.index > hb.index[-1]]
        comb = pd.DataFrame({"Cartera de calidad": pd.concat([hb["cartera"], cont["cartera"] * f_c]),
                             "S&P 500": pd.concat([hb["spy"], cont["spy"] * f_s]), "Promedio de la lista": hb["lista"]})

    c1, c2, c3, c4, c5 = st.columns(5)
    if arranco:
        r_real, r_spy = (valor / cap - 1) * 100, (E["spy_ref"] / cap - 1) * 100
        c1.metric("Cartera real", usd(valor), delta=delta_usd(valor - cap),
                  help=f"Cartera de referencia que arrancó de cero con {usd(cap)} el {fmt_fecha(E['inicio'])}")
        c2.metric("Desde el inicio real", pct(r_real), delta=delta_pts(r_real, r_spy),
                  help=f"Desde el {fmt_fecha(E['inicio'])}. Abajo: diferencia contra el S&P (verde = le gana)")
        c3.metric("S&P 500 mismo período", pct(r_spy))
    else:
        c1.metric("Cartera real", usd(cap), help="Arranca de cero en la próxima revisión, con la compra inicial")
        c2.metric("Desde el inicio real", "—")
        c3.metric("S&P 500 mismo período", "—")
    if comb is not None:
        a_c, a_s = stats_serie(comb["Cartera de calidad"]).get("anual"), stats_serie(comb["S&P 500"]).get("anual")
        c4.metric("Anual desde 2011 (backtest)", pct(a_c, 1, False), delta=delta_pts(a_c, a_s),
                  help="Cartera que arrancó en el backtest de 2011 y sigue con las mismas reglas. Abajo: puntos por año contra el S&P")
    c5.metric("Próxima revisión", prox.strftime("%d/%m/%Y") if prox else "—", help="Primer día hábil desde el 15, a la noche")
    st.caption(f"Precios al cierre del {ult.strftime('%d/%m/%Y')}. "
               + (f"La cartera real arrancó de cero el {fmt_fecha(E['inicio'])}; la del backtest de 2011 sigue aparte con las mismas reglas."
                  if arranco else f"La cartera real arranca de cero el {fmt_fecha(prox) if prox else fmt_fecha(INICIO_REAL_CAL)} con la "
                  "compra inicial (10 empresas, 10% cada una). Mientras tanto se muestra la del backtest."))
    if not arranco:
        aviso(f"<b>La cartera real arranca de cero el {fmt_fecha(prox) if prox else fmt_fecha(INICIO_REAL_CAL)}</b>: ese día el mail manda la "
              "compra inicial. Hasta entonces, las pestañas muestran la cartera que viene del backtest.", "azul")
        E, valor, pesos_vivos = (Eb, valor_b, pesos_bt) if Eb else (E, valor, pesos_vivos)

    tabs = st.tabs(["Resumen", "Cartera", "Evolución", "Con S&P 500", "Operaciones", "Ranking", "Cómo funciona"])
    with tabs[0]:
        corr = (panel or {}).get("correccion")
        if corr is not None and corr <= -0.10:
            aviso(f"<b>Mercado en corrección:</b> el S&amp;P está {pct(-corr * 100, 0, False)} debajo de su máximo del último año. "
                  "Momento de comprar, no de vender: los aportes van a las posiciones por debajo del 10%.", "rojo")
        st.subheader("1. Qué hacer", divider="blue")
        if panel:
            oficial = panel["modo"] == "OFICIAL"
            st.markdown(f"Última revisión: **{fmt_fecha(panel['fecha'])}** · " + (":green-badge[oficial]" if oficial else
                        ":orange-badge[consulta (no registrada)]") + (" · :violet-badge[revisión trimestral]" if panel.get("revision_trimestral") else ""))
            if not oficial:
                aviso("Fue una <b>consulta</b>: muestra qué haría el sistema, pero no quedó registrada.", "naranja")
            if panel["ordenes"]:
                o = pd.DataFrame(panel["ordenes"])
                o.insert(2, "Empresa", [C.nombre(t) for t in o["Acción"]])
                o.insert(3, "CEDEAR", [C.cedear(t) for t in o["Acción"]])
                o["Peso"] = pd.to_numeric(o["Peso"], errors="coerce") * 100
                o["Resultado"] = pd.to_numeric(o["Resultado"], errors="coerce") * 100
                leyenda_ordenes(o["Orden"])
                tabla(o, fmt={"Peso": "%.1f%%", "Resultado": "%+.0f%%"}, signo=["Resultado"], orden="Orden", config={
                    "Peso": st.column_config.Column("% de la cartera"), "Motivo": st.column_config.Column(width="large")})
                st.caption("Primero las ventas, después las compras. Para cada cliente, usar el % de la cartera.")
            else:
                aviso("<b>Ese mes no hubo que hacer nada.</b> En una cartera de largo plazo, es lo normal.", "verde")
        else:
            aviso(f"La primera revisión del sistema real es el <b>{fmt_fecha(prox) if prox else '15 de octubre'}</b> a la noche. "
                  "Hasta entonces, la cartera es la que dejó el backtest.")
        st.subheader("2. Para revisar a mano", divider="orange")
        rev = [(t, x) for t, x in tesis.items() if x["estado"] in ("REVISAR", "SIN DATOS")]
        if rev:
            for t, x in rev:
                aviso(f"⚠ <b>{t}</b> ({C.nombre(t)}): {'; '.join(x['motivos'])}. El sistema no vende por esto: lo decide el equipo.",
                      "naranja")
        else:
            aviso("✓ <b>Nada para revisar:</b> ninguna tesis en duda y ninguna posición cae más de 25% contra el S&amp;P.", "verde")
        st.subheader("3. Si entra plata (aportes o clientes nuevos)", divider="green")
        faltan = sorted([(w, t) for t, w in pesos_vivos.items() if w < 9.7 and tesis.get(t, {}).get("estado", "INTACTA") == "INTACTA"
                         and t not in castigadas])
        if faltan:
            st.markdown("**Aportes**, en este orden hasta que se termine: " + " · ".join(
                f":green-badge[➕ {t}] hasta {pct(10 - w, 1, False)} de la cartera" for w, t in faltan) + ". Si todas llegan al 10%, "
                "repartir el resto en partes iguales.")
        else:
            st.markdown("**Aportes:** todas están cerca del 10%: repartir en partes iguales.")
        st.markdown("**Clientes nuevos:** entrar en 3 tramos (un tercio ahora, otro en un mes y el último al mes siguiente, o antes si el "
                    "mercado cae 10%), comprando la cartera en los pesos de la pestaña Cartera.")
        st.subheader("4. Alertas", divider="red")
        alertas = []
        for t, w in pesos_vivos.items():
            if w > 20:
                alertas.append((f"⚖️ <b>{t}</b> pesa {pct(w, 1, False)}: si pasa del 25% se recorta a 20%.", "naranja"))
        sect = pd.Series([C.grupo(t) for t in E["posiciones"]]).value_counts()
        for s_, n_ in sect[sect >= 3].items():
            alertas.append((f"🧩 Hay {n_} empresas de <b>{s_.lower()}</b>: es el máximo por sector.", "azul"))
        if E["caja"] / valor > 0.03:
            alertas.append((f"💵 Hay {pct(E['caja'] / valor * 100, 1, False)} de liquidez estacionada en SPY esperando la próxima compra.",
                            "azul"))
        for texto, tipo in alertas:
            aviso(texto, tipo)
        if not alertas:
            aviso("✓ <b>Sin alertas.</b>", "verde")

    with tabs[1]:
        filas = []
        for t, p in E["posiciones"].items():
            rend, rel = C.rel_vs_spy(px, t, p["fecha_entrada"])
            filas.append({"Acción": t, "Empresa": C.nombre(t), "CEDEAR": C.cedear(t), "Sector": C.sector(t), "Peso %": pesos_vivos[t],
                          "Suba desde la compra %": rend * 100 if pd.notna(rend) else np.nan,
                          "vs S&P desde la compra %": rel * 100 if pd.notna(rel) else np.nan,
                          "En cartera desde": pd.Timestamp(p["fecha_entrada"]).date(),
                          "Tesis": {"INTACTA": "✓ intacta", "REVISAR": "⚠ revisar", "ROTA": "✗ rota", "SIN DATOS": "sin datos"}.get(
                              tesis.get(t, {}).get("estado"), "—")})
        cart = pd.DataFrame(filas).sort_values("Peso %", ascending=False)
        n_gana = int((cart["vs S&P desde la compra %"] > 0).sum())
        st.markdown(f"<div class='leyenda'>{chip(f'▲ {n_gana} le ganan al S&P desde que entraron', 'verde')}"
                    f"{chip(f'▼ {len(cart) - n_gana} van peor que el S&P', 'rojo') if len(cart) - n_gana else ''}</div>",
                    unsafe_allow_html=True)
        tabla(cart, fmt={"Suba desde la compra %": "%+.0f%%", "vs S&P desde la compra %": "%+.0f%%"},
              signo=["Suba desde la compra %", "vs S&P desde la compra %"], fechas=["En cartera desde"], estilos={"Tesis": TESIS_COLOR},
              config={"Peso %": st.column_config.ProgressColumn("Peso", format="%.1f%%", min_value=0, max_value=25),
                      "Suba desde la compra %": st.column_config.Column(help="Suba de la acción (con dividendos) desde que entró"),
                      "vs S&P desde la compra %": st.column_config.Column(help="Cuánto más (o menos) que el S&P en el mismo período")})
        pesos = cart.set_index("Acción")["Peso %"]
        if E["caja"] / valor > 0.005:
            pesos["SPY*"] = E["caja"] / valor * 100
        grafico_pesos(pesos, 10, 25, "tope 25%", sector_fn=C.sector)
        st.caption("SPY\\* = liquidez estacionada hasta la próxima compra.")
        if arranco and Eb:
            st.subheader("La cartera que viene del backtest (desde 2011)", divider="gray")
            fb = [{"Acción": t, "Empresa": C.nombre(t), "Sector": C.sector(t), "Peso %": pesos_bt[t],
                   "Resultado %": (p["valor"] / p["costo"] - 1) * 100 if p.get("costo") else np.nan,
                   "En cartera desde": pd.Timestamp(p["fecha_entrada"]).date(), "También en la real": "Sí" if t in E["posiciones"] else ""}
                  for t, p in Eb["posiciones"].items()]
            cb = pd.DataFrame(fb).sort_values("Peso %", ascending=False)
            tabla(cb, fmt={"Resultado %": "%+.0f%%"}, signo=["Resultado %"], fechas=["En cartera desde"],
                  config={"Peso %": st.column_config.ProgressColumn("Peso", format="%.1f%%", min_value=0, max_value=25)})
            st.caption(f"Sigue las mismas reglas y el mismo ranking que la real; solo es para comparar. "
                       f"{int((cb['También en la real'] == 'Sí').sum())} de {len(cb)} empresas coinciden con la cartera real.")
        st.subheader("La tesis de cada posición", divider="violet")
        tt = []
        pos_hoy = rank.set_index("Acción")["Puesto"] if len(rank) else pd.Series(dtype=float)
        for t, p in E["posiciones"].items():
            s_ = p.get("tesis") or {}
            num = lambda k: (s_.get(k) if s_.get(k) is not None else np.nan)
            tt.append({"Acción": t, "Empresa": C.nombre(t), "Rentabilidad %": num("rent_prom") * 100, "Ventas crec. %": num("ventas_cagr") * 100,
                       "Rend. esperado %": num("rend_esperado") * 100, "Puesto al comprar": s_.get("Puesto"),
                       "Puesto hoy": str(int(pos_hoy.get(t))) if pd.notna(pos_hoy.get(t)) else "fuera del top 30" if len(rank) else "",
                       "Motivos para revisar": "; ".join(tesis.get(t, {}).get("motivos", []))})
        def color_puesto_hoy(v):
            if v in ("", None):
                return ""
            if not str(v).isdigit():
                return css_color("rojo")
            return css_color("verde" if int(v) <= 10 else "amarillo" if int(v) <= 20 else "rojo")
        tabla(pd.DataFrame(tt), fmt={"Rentabilidad %": "%.0f%%", "Ventas crec. %": "%.0f%%", "Rend. esperado %": "%.1f%%",
                                     "Puesto al comprar": "%d"},
              estilos={"Puesto hoy": color_puesto_hoy, "Motivos para revisar": lambda v: css_color("naranja") if v else ""},
              config={"Rentabilidad %": st.column_config.Column("ROIC/ROE al comprar"),
                      "Ventas crec. %": st.column_config.Column("Ventas/año al comprar"),
                      "Rend. esperado %": st.column_config.Column("Rend. 10 años al comprar")})
        st.caption("Se vende si la tesis se rompe (ROIC debajo de 10%, ventas debajo de 3% u otro filtro mínimo). Se revisa a mano si el ROIC baja 2 años seguidos, si el margen bruto cae "
                   "más de 3 puntos desde la compra o si la acción cae más de 25% contra el S&P. Puesto hoy: solo figura si está en el top 30 "
                   "(verde = top 10 · amarillo = 11 a 20 · rojo = pasó del 20, en riesgo de rotación en la próxima revisión trimestral).")

    with tabs[2]:
        if comb is not None:
            grafico_evolucion(comb, {"Cartera de calidad": AZUL, "S&P 500": GRIS, "Promedio de la lista": NARANJA},
                              marca=(H["fin"], "Fin del backtest"))
            st.caption("USD 10.000 invertidos en enero de 2011. Hasta la línea punteada es el backtest; después, esa misma cartera sigue con las "
                       "mismas reglas y datos del mail. El promedio de la lista compra todas las acciones en partes iguales.")
            res_bt = {r["Cartera"]: r for r in H.get("resumen", []) if r.get("Período") == "Todo"}
            nombres_bt = {"Cartera de calidad": "Cartera de calidad", "S&P 500": "S&P 500 (SPY)", "Promedio de la lista": "Promedio de la lista (igual peso)"}
            cols = st.columns(4)
            for col, nom in zip(cols[:3], ["Cartera de calidad", "S&P 500", "Promedio de la lista"]):
                s_ = stats_serie(comb[nom])
                caida = res_bt.get(nombres_bt[nom], {}).get("Peor caída %", s_.get("caida"))
                col.metric(nom, pct(s_.get("anual"), 1, False) + " anual", delta=f"{pct(caida, 1)} peor caída")
            fin = comb["Cartera de calidad"].dropna().iloc[-1]
            cols[3].metric("USD 10.000 →", usd(fin), delta=f"x{fin / 10000:.1f} el capital".replace(".", ","))
            an = anual_desde({"Cartera de calidad": comb["Cartera de calidad"], "S&P 500": comb["S&P 500"]})
            an["Promedio de la lista"] = pd.Series({a["Año"]: a["Lista"] for a in H["anual"]})
            st.subheader("Año por año", divider="gray")
            grafico_anual(an[["Cartera de calidad", "S&P 500"]], {"Cartera de calidad": AZUL, "S&P 500": GRIS})
            tabla_anual(an, "Cartera de calidad")
        else:
            st.info("Falta historial_calidad.json en el repositorio (lo genera el backtest).")
        if len(evo_real) >= 2:
            st.subheader(f"La cartera real (desde el {fmt_fecha(E0['inicio'])})", divider="violet")
            grafico_evolucion(evo_real.rename(columns={"cartera": "Cartera de calidad", "spy": "S&P 500"})[["Cartera de calidad", "S&P 500"]],
                              {"Cartera de calidad": AZUL, "S&P 500": GRIS})

    with tabs[3]:
        if comb is not None:
            tab_mezcla(comb, pesos_vivos, E["caja"] / valor * 100)
        else:
            st.info("Falta historial_calidad.json en el repositorio (lo genera el backtest).")

    with tabs[4]:
        ops_bt = pd.DataFrame(H["operaciones"]) if H else pd.DataFrame()
        ops_real = pd.DataFrame(E0.get("operaciones", []))
        ops_bt2 = pd.DataFrame((Eb0 or {}).get("operaciones", []))
        for x, origen in ((ops_real, "Cartera real"), (ops_bt2, "Backtest (sigue)")):
            if len(x):
                x["Origen"] = origen
                for k in ("Peso", "Resultado"):
                    if k not in x:
                        x[k] = np.nan
        partes = [x for x in (ops_bt, ops_bt2, ops_real) if len(x)]
        st.subheader("Historial de movimientos", divider="blue")
        historial_con_filtros(pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(), "cal", C.nombre)
        st.subheader("Resultado de cada posición vendida", divider="green")
        v_bt = pd.DataFrame(H["ventas"]) if H else pd.DataFrame()
        v_real = pd.DataFrame(E0.get("cerradas", []))
        v_bt2 = pd.DataFrame((Eb0 or {}).get("cerradas", []))
        for x, origen in ((v_real, "Cartera real"), (v_bt2, "Backtest (sigue)")):
            if len(x):
                x["Origen"] = origen
        partes = [x[["Acción", "Compra", "Venta", "Resultado", "Motivo", "Origen"]] for x in (v_bt, v_bt2, v_real) if len(x)]
        ventas_con_stats(pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(), C.nombre)

    with tabs[5]:
        if not len(rank):
            st.info("El ranking aparece después de la primera revisión del sistema real.")
        else:
            st.markdown(f"De {panel['total']} empresas, **{panel['pasan']}** pasan los filtros mínimos y **{panel['comprables']}** de las 20 "
                        f"mejores son comprables (sin precio extremo ni tendencia en el 10% más bajo). Revisión del {fmt_fecha(panel['fecha'])}.")
            en_cart = set(E["posiciones"])

            def situacion(x):
                if x["Acción"] in en_cart:
                    return "en cartera"
                if x["comprable"]:
                    return f"comprable (orden {int(x['Orden'])})"
                if x["castigada"]:
                    return "tendencia muy débil"
                if x["precio_extremo"]:
                    return "precio extremo"
                return "fuera del top 20" if x["Puesto"] > 20 else "—"
            r = rank.copy()
            r["Situación"] = r.apply(situacion, axis=1)
            r.insert(1, "Empresa", [C.nombre(t) for t in r["Acción"]])
            for k in ("Rentabilidad", "Ventas", "Rend10", "Tendencia"):
                r[k] = pd.to_numeric(r[k], errors="coerce") * 100
            cuenta = r["Situación"].str.split(" ").str[0].value_counts()
            st.markdown("<div class='leyenda'>" + "".join(chip(f"{txt} {cuenta.get(clave, 0)}", col) for clave, txt, col in (
                ("en", "🏛️ En cartera", "azul"), ("comprable", "🟢 Comprables", "verde"), ("precio", "💲 Precio extremo", "naranja"),
                ("tendencia", "📉 Tendencia muy débil", "rojo")) if cuenta.get(clave, 0)) + "</div>", unsafe_allow_html=True)

            def color_rend(v):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    return ""
                return "" if np.isnan(v) else f"color: {ROJO if v < 5 else VERDE if v >= 10 else AMARILLO}; font-weight: 600"
            tabla(r[["Puesto", "Acción", "Empresa", "Situación", "Sector", "Puntaje", "Rentabilidad", "Ventas", "Deuda", "Rend10", "Tendencia"]],
                  fmt={"Puesto": "%d", "Puntaje": "%.0f", "Rentabilidad": "%.0f%%", "Ventas": "%.0f%%", "Deuda": "%.1fx", "Rend10": "%.1f%%"},
                  estilos={"Rend10": color_rend, "Situación": SITUACION_CALIDAD}, height=560, config={
                      "Rentabilidad": st.column_config.Column("ROIC/ROE"), "Ventas": st.column_config.Column("Ventas/año"),
                      "Deuda": st.column_config.Column("Deuda/EBITDA"),
                      "Rend10": st.column_config.Column("Rend. 10 años", help="Verde: 10% o más · amarillo: 5 a 10% · rojo: menos de 5% (precio extremo)"),
                      "Tendencia": st.column_config.ProgressColumn("Tendencia", format="%.0f", min_value=0, max_value=100)})
            esp = r[(r["Puesto"] <= 20) & (~r["comprable"]) & (~r["Acción"].isin(en_cart))].copy()
            if len(esp):
                st.subheader("Lista de espera", divider="orange")
                st.caption("Entre las 20 mejores en calidad, pero hoy no se pueden comprar. Precio de compra = precio al que rendiría 10% anual.")
                esp["Tiene que bajar %"] = (1 - esp["PrecioCompra"] / esp["Precio"]) * 100
                tabla(esp[["Puesto", "Acción", "Empresa", "Precio", "PrecioCompra", "Tiene que bajar %", "Situación"]],
                      fmt={"Puesto": "%d", "Precio": "%.2f", "PrecioCompra": "%.2f", "Tiene que bajar %": "%.0f%%"},
                      estilos={"Situación": SITUACION_CALIDAD, "Tiene que bajar %": lambda v: f"color: {NARANJA}; font-weight: 600"},
                      config={"Precio": st.column_config.Column("Precio hoy (USD)"),
                              "PrecioCompra": st.column_config.Column("Precio de compra (USD)")})

    with tabs[6]:
        st.markdown(REGLAS_CALIDAD)


# ============================================================================ página: momentum
REGLAS_MOMENTUM = """
**La idea:** comprar las 10 acciones que más subieron "por mérito propio" en el último año (descontando lo que explica el S&P) y
mantenerlas mientras sigan entre las 30 mejores.

- **Ranking** el último día hábil de cada mes: para cada acción se estima con 36 meses cuánto de su movimiento explica el S&P; el
  puntaje es la suba propia de los últimos 12 meses (sin el último) dividida por su variabilidad.
- Solo acciones con más de USD 20 millones operados por día.
- **10 acciones.** Se vende una acción solo cuando sale del top 30.
- Cada compra nueva recibe el 10% de la cartera; el sobrante completa las más chicas.
- Si una acción pasa del 20% de la cartera, se recorta a 12,5%.
- Se opera una vez por mes, el primer día hábil, al cierre. Costos estimados: 0,5% por operación.

Análisis cuantitativo con fines educativos; no es una recomendación de inversión.
"""


def color_puesto_mom(v):
    """Puesto en el ranking de momentum: verde top 10, amarillo 25-30 (cerca de salir), rojo fuera del top 30."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return css_color("rojo")
    if np.isnan(v) or v > 30:
        return css_color("rojo")
    return css_color("verde") if v <= 10 else css_color("amarillo") if v >= 25 else ""


def tabla_cartera_mom(cart):
    c = cart.sort_values("Peso %", ascending=False)
    n_gan = int((c["Resultado %"] > 0).sum())
    st.markdown(f"<div class='leyenda'>{chip(f'▲ {n_gan} ganando', 'verde')}"
                f"{chip(f'▼ {len(c) - n_gan} perdiendo', 'rojo') if len(c) - n_gan else ''}</div>", unsafe_allow_html=True)
    tabla(c, fmt={"Resultado %": "%+.1f%%", "Puesto": "%d"}, signo=["Resultado %"], fechas=["Desde"],
          estilos={"Puesto": color_puesto_mom}, config={
              "Peso %": st.column_config.ProgressColumn("Peso", format="%.1f%%", min_value=0, max_value=20),
              "Puesto": st.column_config.Column(help="Puesto en el ranking de hoy. Verde: top 10 · amarillo: 25 a 30, cerca de salir · "
                                                     "rojo: fuera del top 30, se vende")})


def pagina_momentum():
    st.title("Momentum residual")
    st.caption("10 acciones con la mejor suba propia de los últimos 12 meses · se opera el primer día hábil de cada mes · se vende solo "
               "si sale del top 30")
    with st.spinner("Calculando con los precios de hoy (la primera vez tarda hasta un minuto)..."):
        d = datos_momentum(INICIO_MOM_REAL, ultimo_cierre())
    R, B = d["real"], d["bt"]
    inicio = pd.Timestamp(INICIO_MOM_REAL)
    arranco = len(R["cart"]) > 0
    hoy = date.today()
    prox = proxima_operacion_momentum(hoy)
    c1, c2, c3, c4, c5 = st.columns(5)
    r_m = (R["serie"].iloc[-1] / R["serie"].iloc[0] - 1) * 100 if arranco else None
    r_s = (R["spy"].iloc[-1] / R["spy"].iloc[0] - 1) * 100 if arranco else None
    gan = R["valor"] - M.CAPITAL_REF if arranco else None
    c1.metric("Cartera del sistema", usd(R["valor"]), delta=delta_usd(gan),
              help=f"Cartera de referencia de {usd(M.CAPITAL_REF)} desde el {fmt_fecha(inicio)}")
    c2.metric("Desde el inicio real", pct(r_m) if arranco else "—",
              delta=delta_pts(r_m, r_s))
    c3.metric("S&P 500 mismo período", pct(r_s) if arranco else "—")
    a_m, a_s = stats_serie(B["serie"]).get("anual"), stats_serie(B["spy"]).get("anual")
    c4.metric("Anual desde 2011 (backtest)", pct(a_m, 1, False), delta=delta_pts(a_m, a_s),
              help="Abajo: cuántos puntos por año le gana al S&P")
    c5.metric("Próxima operación", prox.strftime("%d/%m/%Y") if prox else "—", help="Primer día hábil del mes, al cierre")
    st.caption(f"Precios al cierre del {pd.Timestamp(d['cierre']).strftime('%d/%m/%Y')}.")
    if not arranco:
        aviso(f"El sistema real arranca el <b>{fmt_fecha(inicio)}</b>. Mientras tanto se muestra la compra inicial que haría hoy y la "
              "historia del backtest desde 2011 con las mismas reglas.")

    tabs = st.tabs(["Resumen", "Cartera", "Evolución", "Operaciones", "Ranking", "Cómo funciona"])
    with tabs[0]:
        st.subheader("1. Qué hacer", divider="blue")
        st.markdown((":green-badge[Hoy es día de operar] "  if prox == hoy else f"Próxima operación: **{fmt_fecha(prox)}**. ")
                    + "Estas son las órdenes que saldrían con el ranking de hoy (el mail del día confirma las definitivas):")
        if d["ords"]:
            orden = {"VENDER": 0, "RECORTAR": 1, "COMPRAR": 2, "SUMAR": 3}
            o = pd.DataFrame(sorted(d["ords"], key=lambda x: orden[x["Orden"]]))
            o.insert(2, "Empresa", [M.nombre(t) for t in o["Acción"]])
            o.insert(3, "CEDEAR", [M.cedear(t) for t in o["Acción"]])
            o["% de la cartera"] = o["Monto"] / (R["valor"] or M.CAPITAL_REF) * 100
            o["Resultado %"] = pd.to_numeric(o["Resultado %"], errors="coerce")
            leyenda_ordenes(o["Orden"])
            tabla(o[["Orden", "Acción", "Empresa", "CEDEAR", "Puesto", "% de la cartera", "Resultado %", "Motivo"]],
                  fmt={"Puesto": "%d", "% de la cartera": "%.1f%%", "Resultado %": "%+.1f%%"}, signo=["Resultado %"], orden="Orden",
                  config={"Motivo": st.column_config.Column(width="large")})
            st.caption("Primero las ventas, después las compras.")
        else:
            aviso("✓ <b>No habría que hacer nada:</b> las 10 siguen dentro del top 30 y ninguna pasa del 20%.", "verde")
        st.subheader("2. Si aportás plata", divider="green")
        if arranco:
            faltan = R["cart"][R["cart"]["Peso %"] < 9.7].sort_values("Peso %")
            st.markdown(("En este orden hasta que se termine: " + " · ".join(
                f":green-badge[➕ {r['Acción']}] hasta {pct(10 - r['Peso %'], 1, False)} de la cartera" for _, r in faltan.iterrows()) + ".")
                if len(faltan) else "Todas están cerca del 10%: repartilo en partes iguales entre las 10.")
        else:
            st.markdown("Cuando arranque el sistema, acá aparece dónde poner los aportes.")
        st.subheader("3. Alertas", divider="red")
        alertas = []
        if arranco:
            for _, r in R["cart"].iterrows():
                if r["Peso %"] > 20:
                    alertas.append((f"⚖️ <b>{r['Acción']}</b> pesa {pct(r['Peso %'], 1, False)}: se recorta a 12,5%.", "naranja"))
                if pd.isna(r["Puesto"]) or r["Puesto"] > 30:
                    alertas.append((f"🔴 <b>{r['Acción']}</b> salió del top 30: se vende en la próxima operación.", "rojo"))
                elif r["Puesto"] >= 25:
                    alertas.append((f"⚠ <b>{r['Acción']}</b> está en el puesto {int(r['Puesto'])}: se vende si pasa del 30.", "naranja"))
            sect = R["cart"]["Sector"].value_counts()
            for s_, n_ in sect[sect >= 3].items():
                alertas.append((f"🧩 Hay {n_} acciones de <b>{s_.lower()}</b> (solo informativo).", "azul"))
        for texto, tipo in alertas:
            aviso(texto, tipo)
        if not alertas:
            aviso("✓ <b>Sin alertas.</b>", "verde")

    with tabs[1]:
        if arranco:
            tabla_cartera_mom(R["cart"])
            grafico_pesos(R["cart"].set_index("Acción")["Peso %"], 10, 20, "tope 20%", sector_fn=lambda t: M.SECTOR.get(t, "Otros"))
        else:
            st.markdown("**Compra inicial si la cartera arrancara hoy** (10% en cada una):")
            ini = pd.DataFrame([{"Acción": t, "Empresa": M.nombre(t), "CEDEAR": M.cedear(t), "Sector": M.SECTOR.get(t, "Otros"),
                                 "Puesto": d["rk"]["Puesto"].get(t), "Suba 12 meses %": d["rk"]["Suba 12-1 %"].get(t)}
                                for t in d["hold2"]]).sort_values("Puesto")
            tabla(ini, fmt={"Puesto": "%d", "Suba 12 meses %": "%+.0f%%"}, signo=["Suba 12 meses %"])
            st.caption("Es una referencia: la compra real sale en el mail del primer día hábil desde la fecha de inicio.")
        with st.expander("Cartera que tendría hoy el backtest (si se hubiera seguido desde 2011)"):
            tabla_cartera_mom(B["cart"])

    with tabs[2]:
        grafico_evolucion(pd.DataFrame({"Momentum": B["serie"], "S&P 500": B["spy"]}), {"Momentum": AZUL, "S&P 500": GRIS})
        st.caption(f"Backtest: USD 10.000 desde el {fmt_fecha(B['serie'].index[0])} con las mismas reglas y el mismo código del mail. "
                   "La lista de acciones es la de hoy (sesgo de supervivencia).")
        s_m, s_s = stats_serie(B["serie"]), stats_serie(B["spy"])
        cols = st.columns(4)
        cols[0].metric("Momentum", pct(s_m.get("anual"), 1, False) + " anual", delta=f"{pct(s_m.get('caida'), 1)} peor caída")
        cols[1].metric("S&P 500", pct(s_s.get("anual"), 1, False) + " anual", delta=f"{pct(s_s.get('caida'), 1)} peor caída")
        cols[2].metric("Volatilidad anual", pct(s_m.get("vol"), 1, False), delta=f"S&P 500: {pct(s_s.get('vol'), 1, False)}",
                       delta_color="off")
        cols[3].metric("USD 10.000 →", usd(B["serie"].iloc[-1]), delta=f"x{B['serie'].iloc[-1] / B['serie'].iloc[0]:.1f} el capital".replace(".", ","))
        an = anual_desde({"Momentum": B["serie"], "S&P 500": B["spy"]})
        st.subheader("Año por año", divider="gray")
        grafico_anual(an, {"Momentum": AZUL, "S&P 500": GRIS})
        tabla_anual(an, "Momentum")
        if arranco and len(R["serie"]) >= 5:
            st.subheader("Solo el sistema real", divider="violet")
            grafico_evolucion(pd.DataFrame({"Momentum": R["serie"], "S&P 500": R["spy"]}), {"Momentum": AZUL, "S&P 500": GRIS})

    with tabs[3]:
        opciones = ["Backtest desde 2011"] + (["Sistema real"] if arranco else [])
        cual = st.radio("Ver", opciones, horizontal=True, key="mom_ver", index=len(opciones) - 1)
        X = R if cual == "Sistema real" else B
        st.subheader("Historial de órdenes", divider="blue")
        h = X["historial"]
        if len(h):
            hh = h[["Fecha", "Orden", "Acción", "Peso", "Resultado", "Motivo"]].copy()
            hh["Origen"] = cual
            historial_con_filtros(hh, "mom_r" if cual == "Sistema real" else "mom_b", M.nombre)
        else:
            st.info("Todavía no hay órdenes.")
        st.subheader("Operaciones cerradas", divider="green")
        cer = X["cerradas"]
        if len(cer):
            v = cer[["Acción", "Compra", "Venta", "Resultado", "Sector"]].rename(columns={"Sector": "Motivo"})
            ventas_con_stats(v, M.nombre, nota_motivo="Sector")
            st.caption("En momentum, el motivo de venta es siempre el mismo: salir del top 30.")
        else:
            st.info("Todavía no hubo ventas.")

    with tabs[4]:
        rk = d["rk"].head(30).reset_index().rename(columns={"index": "Acción"})
        rk.insert(1, "Empresa", [M.nombre(t) for t in rk["Acción"]])
        rk.insert(2, "CEDEAR", [M.cedear(t) for t in rk["Acción"]])
        en = set(R["cart"]["Acción"]) if arranco else set(d["hold2"])
        rk["Situación"] = ["en cartera" if t in en else ("fuera (cartera llena)" if p <= 10 else "") for t, p in zip(rk["Acción"], rk["Puesto"])]
        st.markdown("**Ranking de hoy (top 30).** Las que están en cartera no se cambian por otras mejor rankeadas: solo se venden si salen "
                    "del top 30.")
        st.markdown("<div class='leyenda'>" + chip("🏛️ En cartera", "azul") + chip("Top 10 que no entra (cartera llena)", "gris")
                    + chip("25 a 30: zona de salida", "amarillo") + "</div>", unsafe_allow_html=True)
        tabla(rk[["Puesto", "Acción", "Empresa", "Situación", "CEDEAR", "Sector", "Suba 12-1 %", "Volatilidad %", "Puntaje"]],
              fmt={"Puesto": "%d", "Suba 12-1 %": "%+.0f%%", "Volatilidad %": "%.0f%%", "Puntaje": "%.2f"}, signo=["Suba 12-1 %"],
              estilos={"Situación": SITUACION_MOM, "Puesto": lambda v: css_color("amarillo") if v >= 25 else ""}, height=560, config={
                  "Suba 12-1 %": st.column_config.Column("Suba 12 meses"), "Volatilidad %": st.column_config.Column("Volatilidad")})

    with tabs[5]:
        st.markdown(REGLAS_MOMENTUM)



# ============================================================================ página: reversión (screener)
INICIO_REV = "2010-01-01"
TP_REV, MAX_TP_REV, LUGARES_REV = 0.20, 252, 10
REGLAS_REV = {"6m": "Vender a los 6 meses", "tp": "Vender al +20% (o a los 12 meses)"}
FILTROS_TXT = {"volumen": "volumen", "emas": "medias semanales", "correccion": "caída 25-60%", "consolidacion": "consolidación",
               "valuacion": "P/E", "mercado": "S&P sobre su media", "beta": "beta ≥ 1,3"}


def evaluar_rev(ind, cfg):
    """Los mismos filtros de screener.evaluar, calculados para todas las ruedas juntas."""
    r = pd.DataFrame(index=ind.index)
    r["volumen"] = ind["Volumen prom. USD (M)"] * 1e6 >= cfg["volumen_min_usd"]
    precio_ok = ind["Precio vs EMA200 %"] >= -cfg["precio_cerca_ema200"] * 100
    pegadas = ind["EMA20 vs EMA200 %"].abs() <= cfg["ema20_pegada_ema200"] * 100
    r["emas"] = (ind["Semanas de historia"] >= cfg["ema_larga"]) & precio_ok & (pegadas | (ind["Precio"] > ind["EMA20 sem."]))
    alto = ind["Beta alto"] == "Sí"
    lo = np.where(alto, cfg["correccion_beta_alto"][0], cfg["correccion_beta_bajo"][0]) * 100
    hi = np.where(alto, cfg["correccion_beta_alto"][1], cfg["correccion_beta_bajo"][1]) * 100
    r["correccion"] = (ind["Caída desde máx. %"] >= lo) & (ind["Caída desde máx. %"] <= hi)
    lo2, hi2 = cfg["dias_desde_max_si_alcista"]
    r["consolidacion"] = np.where(ind["Tendencia previa"] == "Bajista", ind["Días en rango"] >= cfg["rango_min_dias_si_bajista"],
                                  (ind["Días desde últ. máx."] >= lo2) & (ind["Días desde últ. máx."] <= hi2))
    r["valuacion"] = False
    bmin = cfg.get("beta_min")
    b = pd.to_numeric(ind["Beta"], errors="coerce")
    r["beta"] = True if not bmin else (b >= bmin).fillna(False)
    r["mercado"] = ind["S&P sobre media 200"].astype(bool)
    return r.astype(bool)


def _salidas(cv, cb, i0):
    """Resultado de una señal con las dos reglas. Devuelve dict regla -> datos (abierta si todavía no se cumplió)."""
    n, c0 = len(cv), cv[i0]
    out = {}
    k = SCR.CONFIG["mantener_ruedas"]
    if i0 + k <= n - 1:
        out["6m"] = dict(fin=i0 + k, abierta=False, motivo="6 meses")
    else:
        out["6m"] = dict(fin=n - 1, abierta=True, motivo="", faltan=k - (n - 1 - i0))
    seg = cv[i0 + 1:i0 + MAX_TP_REV + 1] / c0 - 1
    toca = np.where(seg >= TP_REV)[0]
    if len(toca):
        out["tp"] = dict(fin=i0 + 1 + int(toca[0]), abierta=False, motivo="Llegó a +20%")
    elif i0 + MAX_TP_REV <= n - 1:
        out["tp"] = dict(fin=i0 + MAX_TP_REV, abierta=False, motivo="12 meses sin llegar a +20%")
    else:
        out["tp"] = dict(fin=n - 1, abierta=True, motivo="", faltan=MAX_TP_REV - (n - 1 - i0))
    for d in out.values():
        d["ret"] = cv[d["fin"]] / c0 - 1
        d["ret_spy"] = cb[d["fin"]] / cb[i0] - 1 if cb[i0] > 0 else np.nan
        d["ruedas"] = d["fin"] - i0
    return out


def simular_cartera_rev(ops, reg, px, spy, liquidez_spy):
    """Cartera de 10 lugares: cada señal entra con 1/10 del valor total si hay lugar libre; sale según la regla."""
    if not len(ops):
        return pd.Series(dtype=float)
    idx = spy.index[spy.index >= ops["Entrada"].min()]
    cols = {t: j for j, t in enumerate(px.columns)}
    P = px.reindex(idx).ffill().values
    S = spy.reindex(idx).ffill().values
    pos_d = {d: i for i, d in enumerate(idx)}
    entradas, salidas = {}, {}
    for oid, o in ops.iterrows():
        i = pos_d.get(o["Entrada"])
        if i is None:
            continue
        entradas.setdefault(i, []).append(oid)
        if not o[f"abierta_{reg}"]:
            j = pos_d.get(o[f"salida_{reg}"])
            if j is not None:
                salidas.setdefault(j, []).append(oid)
    caja, pos, vals = 10000.0, {}, []
    for i in range(len(idx)):
        if liquidez_spy and i > 0:
            caja *= S[i] / S[i - 1]
        for oid in salidas.get(i, []):
            if oid in pos:
                j, cant = pos.pop(oid)
                caja += cant * P[i, j] * (1 - C.COSTO)
        abiertas_v = sum(cant * P[i, j] for j, cant in pos.values())
        for oid in sorted(entradas.get(i, []), key=lambda o: ops.loc[o, "Ticker"]):
            if len(pos) >= LUGARES_REV:
                break
            j = cols[ops.loc[oid, "Ticker"]]
            monto = min((caja + abiertas_v) / LUGARES_REV, caja)
            if monto > 1 and P[i, j] > 0:
                pos[oid] = (j, monto * (1 - C.COSTO) / P[i, j])
                caja -= monto
        vals.append(caja + sum(cant * P[i, j] for j, cant in pos.values()))
    return pd.Series(vals, index=idx)


VERSION_REV = "4"     # subir este número cuando cambie el cálculo, para que no se use la memoria vieja


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def datos_reversion(version, reglas, cierre=None):
    cfg, act = SCR.CONFIG, SCR.FILTROS_ACTIVOS
    tick = list(SCR.LISTA_TICKERS)
    datos = yf.download(tick + ["SPY"], period="max", interval="1d", auto_adjust=True, group_by="ticker", threads=True, progress=False)
    precios = {}
    for t in tick + ["SPY"]:
        try:
            df = datos[t][["Close", "Volume"]].dropna(subset=["Close"])
        except (KeyError, TypeError):
            continue
        if len(df):
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            precios[t] = df
    spy = precios.pop("SPY")["Close"]
    SCR.SPY_SERIE = spy
    media = spy.rolling(cfg["mercado_media_dias"]).mean()
    spy_ok = spy > media
    activos = [f for f in act if act[f]]
    filas_ops, hoy = [], []
    for t, df in precios.items():
        try:
            ind = SCR._serie_dias(df, {}, cfg, INICIO_REV)
        except Exception:       # noqa: BLE001
            continue
        if ind.empty:
            continue
        ind["S&P sobre media 200"] = spy_ok.reindex(ind["Fecha"]).ffill().fillna(False).values
        ev = evaluar_rev(ind, cfg)
        ok = ev[activos].all(axis=1)
        u, e = ind.iloc[-1], ev.iloc[-1]
        falla = [FILTROS_TXT[f] for f in activos if not e[f]]
        hoy.append({"Acción": t, "Precio": u["Precio"], "Caída desde máx. %": u["Caída desde máx. %"], "Beta": u["Beta"],
                    "Tendencia previa": u["Tendencia previa"], "Días desde últ. máx.": u["Días desde últ. máx."],
                    "Días en rango": u["Días en rango"], "Fallan": len(falla), "Falta": ", ".join(falla)})
        cv = df["Close"].values.astype(float)
        cb = spy.reindex(df.index).ffill().values.astype(float)
        ultimo = -10 ** 9
        for i0, fecha in ind.loc[ok, ["i", "Fecha"]].itertuples(index=False):
            if i0 - ultimo < cfg["mantener_ruedas"]:     # no se repite mientras la anterior sigue en cartera
                continue
            ultimo = i0
            sal = _salidas(cv, cb, int(i0))
            f = {"Ticker": t, "Entrada": pd.Timestamp(fecha), "Precio entrada": cv[i0]}
            for reg, d in sal.items():
                f.update({f"salida_{reg}": df.index[d["fin"]], f"precio_{reg}": cv[d["fin"]], f"ret_{reg}": d["ret"] * 100,
                          f"spy_{reg}": d["ret_spy"] * 100, f"ruedas_{reg}": d["ruedas"], f"abierta_{reg}": d["abierta"],
                          f"motivo_{reg}": d["motivo"], f"faltan_{reg}": d.get("faltan")})
            filas_ops.append(f)
    ops = pd.DataFrame(filas_ops).sort_values("Entrada").reset_index(drop=True) if filas_ops else pd.DataFrame()
    px = pd.DataFrame({t: df["Close"] for t, df in precios.items()})
    carteras = {reg: simular_cartera_rev(ops, reg, px, spy, True) for reg in REGLAS_REV}
    spy_c = spy[spy.index >= (ops["Entrada"].min() if len(ops) else spy.index[0])]
    return dict(ops=ops, hoy=pd.DataFrame(hoy), carteras=carteras, spy=spy_c, cierre=spy.index[-1],
                mercado=(bool(spy_ok.iloc[-1]), float(spy.iloc[-1]), float(media.iloc[-1])))


def stats_reglas(ops):
    filas = []
    for reg, nom in REGLAS_REV.items():
        o = ops[~ops[f"abierta_{reg}"]] if len(ops) else ops
        if not len(o):
            continue
        meses = o[f"ruedas_{reg}"].sum() / 21
        filas.append({"Regla de salida": nom, "Operaciones cerradas": len(o), "% con ganancia": (o[f"ret_{reg}"] > 0).mean() * 100,
                      "Resultado promedio %": o[f"ret_{reg}"].mean(), "Meses promedio": o[f"ruedas_{reg}"].mean() / 21,
                      "Ganancia por mes invertido %": o[f"ret_{reg}"].sum() / meses,
                      "S&P por mes %": o[f"spy_{reg}"].sum() / meses,
                      "% le ganan al S&P": ((o[f"ret_{reg}"] - o[f"spy_{reg}"]) > 0).mean() * 100,
                      "Peor %": o[f"ret_{reg}"].min(), "Mejor %": o[f"ret_{reg}"].max()})
    return pd.DataFrame(filas)


REGLAS_REVERSION = """
**La idea:** comprar acciones con CEDEAR que vienen de una corrección fuerte pero siguen en tendencia de largo plazo, cuando la
caída ya se frenó, y venderlas en el rebote. Es el mismo programa del mail diario del screener.

**Cuándo da señal de compra** (tienen que cumplirse todas):
- **Volumen:** más de USD 20 millones operados por día.
- **Medias semanales:** el precio arriba (o hasta 10% abajo) de la media de 200 semanas, y la media de 20 semanas pegada a la de 200 o el precio arriba de la de 20.
- **Corrección:** cae entre 25% y 60% desde el máximo de los últimos 2 años.
- **Consolidación:** si venía subiendo, entre 30 y 120 días desde el último máximo; si venía bajando, más de 100 días lateralizando.
- **Beta ≥ 1,3:** se mueve más que el mercado (2 años de datos semanales).
- **Mercado:** el S&P 500 está arriba de su media de 200 días.
- No se vuelve a comprar la misma acción mientras la anterior sigue en cartera.

**Dos formas de salir** (se pueden comparar con el selector de arriba):
- **A los 6 meses** (126 ruedas): la regla del mail. Deja correr las subas grandes.
- **Al +20%:** se vende apenas el cierre supera +20% desde la compra; si en 12 meses no llega, se vende igual. Más operaciones
  terminan con ganancia, pero se cortan las subas grandes.

**Cartera de 10 lugares:** cada señal entra con el 10% del valor de la cartera si hay lugar libre. La plata que no está en
ninguna operación queda invertida en el S&P 500 (SPY) hasta la próxima compra, así la comparación con el índice es pareja.
Costos: 0,5% por operación. Entrada y salida al cierre del día de la señal.

Análisis cuantitativo con fines educativos; no es una recomendación de inversión.
"""


def pagina_reversion():
    st.title("Reversión (screener)")
    if SCR is None:
        aviso("Falta <b>screener.py</b> en este repositorio. Copialo desde el repositorio del screener a la carpeta principal de "
              "este (al lado de calidad.py) y la página se arma sola. Acá solo se usa para calcular las señales: no manda mails.", "naranja")
        return
    st.caption("Empresas con CEDEAR que corrigieron 25-60%, con beta alto, consolidando y con el mercado a favor · mismo código que el "
               "mail diario del screener · dos reglas de salida para comparar")
    with st.spinner("Calculando señales desde 2010 con los precios de hoy (la primera vez tarda hasta un par de minutos)..."):
        d = datos_reversion(VERSION_REV, tuple(REGLAS_REV), ultimo_cierre())
        if len(d["ops"]) and any(f"abierta_{r}" not in d["ops"] for r in REGLAS_REV):   # memoria de una versión anterior
            datos_reversion.clear()
            d = datos_reversion(VERSION_REV, tuple(REGLAS_REV), ultimo_cierre())
    ops, hoy = d["ops"], d["hoy"]
    reg = st.radio("Regla de salida", list(REGLAS_REV), format_func=REGLAS_REV.get, horizontal=True, key="rev_regla")
    nom = REGLAS_REV[reg]
    ok_m, px_s, media_s = d["mercado"]
    senales = hoy[hoy["Fallan"] == 0] if len(hoy) else hoy
    ab = ops[ops[f"abierta_{reg}"]].copy() if len(ops) else ops
    cer = ops[~ops[f"abierta_{reg}"]].copy() if len(ops) else ops
    cart = d["carteras"][reg]
    spy = d["spy"]
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Señales de hoy", len(senales))
    k2.metric("Operaciones abiertas", len(ab), delta=(pct(ab[f"ret_{reg}"].mean(), 1) + " promedio") if len(ab) else None)
    k3.metric("Mercado", "A favor" if ok_m else "En contra", delta=f"{pct((px_s / media_s - 1) * 100, 1)} S&P vs su media",
              delta_color="normal", help="Solo se compra si el S&P 500 está arriba de su media de 200 días")
    if len(cart):
        a_c, a_s = stats_serie(cart).get("anual"), stats_serie(spy.loc[cart.index[0]:]).get("anual")
        k4.metric("Cartera de 10 lugares", pct(a_c, 1, False) + " anual", delta=delta_pts(a_c, a_s),
                  help=f"Desde {cart.index[0].year}, con la regla elegida. Abajo: diferencia contra el S&P")
    so = stats_reglas(ops)
    fila = so[so["Regla de salida"] == nom] if len(so) else so
    if len(fila):
        k5.metric("Operaciones con ganancia", pct(float(fila["% con ganancia"].iloc[0]), 0, False),
                  delta=f"{int(fila['Operaciones cerradas'].iloc[0])} cerradas", delta_color="off")
    st.caption(f"Precios al cierre del {pd.Timestamp(d['cierre']).strftime('%d/%m/%Y')}.")

    tabs = st.tabs(["Hoy", "Operaciones abiertas", "Historial", "Resultados", "Cómo funciona"])
    with tabs[0]:
        if ok_m:
            aviso(f"✓ <b>Mercado a favor:</b> el S&amp;P ({px_s:,.0f}) está arriba de su media de 200 días ({media_s:,.0f}). "
                  "Se pueden tomar las señales.".replace(",", "."), "verde")
        else:
            aviso(f"<b>Mercado en contra:</b> el S&amp;P ({px_s:,.0f}) está debajo de su media de 200 días ({media_s:,.0f}). "
                  "No se compra hasta que vuelva a estar arriba.".replace(",", "."), "rojo")
        st.subheader("1. Comprar", divider="green")
        if len(senales):
            t_ = senales.copy()
            t_.insert(1, "Empresa", [C.nombre(x) for x in t_["Acción"]])
            t_.insert(2, "CEDEAR", [C.cedear(x) for x in t_["Acción"]])
            en_cartera = set(ab["Ticker"]) if len(ab) else set()
            t_["Situación"] = ["ya en cartera: no repetir" if x in en_cartera else "🟢 comprar" for x in t_["Acción"]]
            tabla(t_[["Acción", "Empresa", "CEDEAR", "Precio", "Caída desde máx. %", "Beta", "Tendencia previa", "Situación"]],
                  fmt={"Precio": "%.2f", "Caída desde máx. %": "%.1f%%", "Beta": "%.2f"},
                  estilos={"Situación": por_prefijo({"🟢": "verde", "ya": "gris"})})
            st.caption("Cada compra, 10% de la cartera destinada a esta estrategia. Si tiene balance en los próximos días, el mail avisa.")
        else:
            aviso("Hoy no hay señales de compra.", "azul")
        st.subheader("2. Vender", divider="red")
        if len(ab):
            if reg == "6m":
                vend = ab[ab["faltan_6m"] <= 0]
                prox = ab[(ab["faltan_6m"] > 0) & (ab["faltan_6m"] <= 5)]
                for _, r in vend.iterrows():
                    aviso(f"🔴 <b>{r['Ticker']}</b> ({C.nombre(r['Ticker'])}): cumplió 6 meses, <b>vender hoy</b> "
                          f"(resultado {pct(r['ret_6m'], 1)}).", "rojo")
                for _, r in prox.iterrows():
                    aviso(f"⏳ <b>{r['Ticker']}</b>: se vende en {int(r['faltan_6m'])} ruedas (resultado hoy {pct(r['ret_6m'], 1)}).", "naranja")
                if not len(vend) and not len(prox):
                    aviso("✓ Ninguna operación cumple 6 meses esta semana.", "verde")
            else:
                fmt_u = lambda v: f"USD {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                cerca = ab[ab[f"ret_{reg}"] >= 15]
                for _, r in cerca.iterrows():
                    aviso(f"🎯 <b>{r['Ticker']}</b> está en {pct(r[f'ret_{reg}'], 1)}: se vende si cierra arriba de "
                          f"{fmt_u(r['Precio entrada'] * (1 + TP_REV))}.", "naranja")
                vence = ab[ab[f"faltan_{reg}"] <= 5]
                for _, r in vence.iterrows():
                    aviso(f"⏳ <b>{r['Ticker']}</b>: en {int(max(r[f'faltan_{reg}'], 0))} ruedas cumple 12 meses; se vende igual.", "rojo")
                if not len(cerca) and not len(vence):
                    aviso("✓ Ninguna operación está cerca del objetivo ni de cumplir 12 meses.", "verde")
            st.caption("Las ventas de ayer ya figuran en el Historial.")
        else:
            aviso("No hay operaciones abiertas.", "azul")
        st.subheader("3. Cerca de dar señal", divider="gray")
        casi = hoy[hoy["Fallan"] == 1].copy() if len(hoy) else hoy
        if len(casi):
            casi.insert(1, "Empresa", [C.nombre(x) for x in casi["Acción"]])
            tabla(casi[["Acción", "Empresa", "Precio", "Caída desde máx. %", "Beta", "Falta"]].sort_values("Caída desde máx. %", ascending=False),
                  fmt={"Precio": "%.2f", "Caída desde máx. %": "%.1f%%", "Beta": "%.2f"},
                  estilos={"Falta": lambda v: css_color("amarillo")})
            st.caption("Cumplen todo menos un filtro. No se compran todavía: es para tenerlas en el radar.")
        else:
            st.markdown("Ninguna está a un solo filtro de dar señal.")

    with tabs[1]:
        if not len(ab):
            st.info("No hay operaciones abiertas con esta regla.")
        else:
            t_ = ab.copy()
            t_.insert(1, "Empresa", [C.nombre(x) for x in t_["Ticker"]])
            t_["Precio actual"] = t_[f"precio_{reg}"]
            t_["Resultado %"] = t_[f"ret_{reg}"]
            t_["vs S&P %"] = t_[f"ret_{reg}"] - t_[f"spy_{reg}"]
            if reg == "6m":
                t_["Vender el"] = [(e + pd.offsets.BDay(SCR.CONFIG["mantener_ruedas"])) for e in t_["Entrada"]]
                t_["Ruedas restantes"] = t_["faltan_6m"]
                cols = ["Ticker", "Empresa", "Entrada", "Precio entrada", "Precio actual", "Resultado %", "vs S&P %", "Vender el", "Ruedas restantes"]
                fechas = ["Entrada", "Vender el"]
            else:
                t_["Vende en (USD)"] = t_["Precio entrada"] * (1 + TP_REV)
                t_["Le falta subir %"] = (t_["Vende en (USD)"] / t_["Precio actual"] - 1) * 100
                t_["Límite 12 meses"] = [(e + pd.offsets.BDay(MAX_TP_REV)) for e in t_["Entrada"]]
                cols = ["Ticker", "Empresa", "Entrada", "Precio entrada", "Precio actual", "Resultado %", "vs S&P %", "Vende en (USD)",
                        "Le falta subir %"]
                cols += ["Límite 12 meses"]
                fechas = ["Entrada", "Límite 12 meses"]
            n_g = int((t_["Resultado %"] > 0).sum())
            st.markdown(f"<div class='leyenda'>{chip(f'▲ {n_g} ganando', 'verde')}"
                        f"{chip(f'▼ {len(t_) - n_g} perdiendo', 'rojo') if len(t_) - n_g else ''}"
                        f"{chip('Resultado promedio ' + pct(t_['Resultado %'].mean(), 1), 'azul')}</div>", unsafe_allow_html=True)
            tabla(t_[cols].sort_values("Entrada"), fmt={"Precio entrada": "%.2f", "Precio actual": "%.2f", "Resultado %": "%+.1f%%",
                                                         "vs S&P %": "%+.1f%%", "Vende en (USD)": "%.2f", "Le falta subir %": "%.1f%%",
                                                         "Ruedas restantes": "%d"},
                  signo=["Resultado %", "vs S&P %"], fechas=fechas)
            st.caption("Son las operaciones que abrió el sistema (todas las señales). Si en tu cartera real compraste otras o en otras "
                       "fechas, los resultados cambian.")

    with tabs[2]:
        if not len(cer):
            st.info("Todavía no hay operaciones cerradas.")
        else:
            v = pd.DataFrame({"Acción": cer["Ticker"], "Compra": cer["Entrada"], "Venta": cer[f"salida_{reg}"],
                              "Resultado": cer[f"ret_{reg}"] / 100, "Motivo": cer[f"motivo_{reg}"]})
            ventas_con_stats(v, C.nombre, nota_motivo="Por qué se vendió")
            st.caption(f"Todas las señales desde {INICIO_REV[:4]} con la regla «{nom}». El motivo muestra si llegó a +20% o se vendió por plazo.")

    with tabs[3]:
        st.subheader("Las dos reglas, operación por operación", divider="blue")
        if len(so):
            so2 = so.copy()
            so2[""] = ["◀ elegida" if x == nom else "" for x in so2["Regla de salida"]]
            tabla(so2, fmt={"Operaciones cerradas": "%d", "% con ganancia": "%.0f%%", "Resultado promedio %": "%+.1f%%",
                            "Meses promedio": "%.1f", "Ganancia por mes invertido %": "%+.2f%%", "S&P por mes %": "%+.2f%%",
                            "% le ganan al S&P": "%.0f%%", "Peor %": "%+.0f%%", "Mejor %": "%+.0f%%"},
                  signo=["Resultado promedio %", "Ganancia por mes invertido %", "Peor %", "Mejor %"],
                  estilos={"": lambda v: css_color("verde") if v else ""})
            st.caption("Ganancia por mes invertido = suma de resultados dividida por los meses que la plata estuvo adentro: permite comparar "
                       "reglas que mantienen la acción distinto tiempo. S&P por mes = lo mismo con el S&P en esos mismos períodos.")
        if len(ops):
            tp_ok = ops[(~ops["abierta_tp"]) & (ops["motivo_tp"] == "Llegó a +20%")]
            if len(tp_ok):
                m_ = tp_ok["ruedas_tp"] / 21
                aviso(f"🎯 Con la regla del +20%, <b>{len(tp_ok)}</b> operaciones llegaron al objetivo: la mitad en <b>"
                      f"{str(round(m_.median(), 1)).replace('.', ',')} meses</b> o menos, y {int((m_ <= 6).sum())} de {len(tp_ok)} dentro "
                      "de los primeros 6 meses.", "azul")
        st.subheader(f"Cartera de 10 lugares: {nom}", divider="green")
        cart = d["carteras"][reg]
        if len(cart):
            s_ = spy.loc[cart.index[0]:]
            s_ = s_ / s_.iloc[0] * 10000
            paleta = {"6m": VERDE, "tp": NARANJA}
            series = {REGLAS_REV[r]: d["carteras"][r] for r in REGLAS_REV}
            grafico_evolucion(pd.DataFrame({**series, "S&P 500": s_}),
                              {**{REGLAS_REV[r]: paleta[r] for r in REGLAS_REV}, "S&P 500": GRIS})
            cols_m = st.columns(len(REGLAS_REV) + 1)
            for col_m, r in zip(cols_m, REGLAS_REV):
                sr = stats_serie(d["carteras"][r])
                col_m.metric(REGLAS_REV[r] + (" ◀" if r == reg else ""), pct(sr.get("anual"), 1, False) + " anual",
                             delta=f"{pct(sr.get('caida'), 1)} peor caída")
            ss = stats_serie(s_)
            cols_m[-1].metric("S&P 500", pct(ss.get("anual"), 1, False) + " anual", delta=f"{pct(ss.get('caida'), 1)} peor caída")
            st.caption(f"Con la regla elegida, USD 10.000 se convirtieron en {usd(cart.iloc[-1])}.")
            st.caption("Cada señal entra con el 10% de la cartera si hay lugar; con 10 operaciones abiertas, las señales nuevas se "
                       "saltean. La plata que no está en ninguna operación queda en el S&P 500 (SPY) hasta la próxima compra. "
                       "Costos de 0,5% por operación. La lista de acciones es la de hoy (sesgo de supervivencia).")
            st.subheader("Año por año", divider="gray")
            an = anual_desde({nom: cart, "S&P 500": s_})
            grafico_anual(an, {nom: VERDE, "S&P 500": GRIS})
            tabla_anual(an, nom)

    with tabs[4]:
        st.markdown(REGLAS_REVERSION)

pg = st.navigation([st.Page(pagina_calidad, title="Cartera de calidad", icon="🏛️", default=True),
                    st.Page(pagina_reversion, title="Reversión (screener)", icon="🔄", url_path="reversion"),
                    st.Page(pagina_momentum, title="Momentum residual", icon="🚀", url_path="momentum")])
st.sidebar.caption("Estrategias con CEDEARs · datos con fines educativos, no es recomendación de inversión.")
pg.run()
