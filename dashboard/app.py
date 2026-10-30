"""
Dashboard de las estrategias con CEDEARs: Cartera de calidad y Momentum residual.
Se publica en Streamlit Community Cloud (privado: solo entran los mails invitados).

  * Cartera de calidad: la cartera que guarda el mail mensual (cartera_calidad.json) valuada con precios del día,
    la última revisión y el ranking (panel_calidad.json) y la historia del backtest 2011-2026 (historial_calidad.json).
  * Momentum residual: se recalcula en vivo con el mismo código del mail (momentum.py), incluyendo su backtest desde 2011.
"""
import html
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

st.set_page_config(page_title="Streamlimits", page_icon="📈", layout="wide")

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

# Streamlit deja los programas cargados en memoria entre visitas: si GitHub actualizó universo.csv, se vuelven a cargar
# para que las tres estrategias y el explorador usen la lista nueva sin tener que reiniciar la app.
_ARCH_UNIVERSO = RAIZ / "universo.csv"
MARCA_UNIVERSO = _ARCH_UNIVERSO.stat().st_mtime if _ARCH_UNIVERSO.exists() else 0.0
if getattr(C, "_marca_universo", None) != MARCA_UNIVERSO:
    import importlib
    import universo as _U
    importlib.reload(_U)
    C, M = importlib.reload(C), importlib.reload(M)
    if SCR is not None:
        SCR = importlib.reload(SCR)
    import calculos as _CALC
    importlib.reload(_CALC)
    C._marca_universo = MARCA_UNIVERSO
import calculos as CALC      # noqa: E402  (cálculos pesados; se guardan hechos de madrugada en precalculo/)
from calculos import (INICIO_REV, TP_REV, MAX_TP_REV, LUGARES_REV, REGLAS_REV, FILTROS_TXT, VERSION_REV,  # noqa: E402,F401
                      evaluar_rev, simular_cartera_rev)

# Fecha de arranque de la cartera real del momentum: se lee de la configuración, NUNCA de M.INICIO, porque
# datos_momentum cambia M.INICIO un momento para calcular el backtest (si otra visita leía justo en ese momento,
# tomaba 2011 como inicio y mostraba el backtest como si fuera la cartera real).
INICIO_MOM_REAL = os.environ.get("MOMENTUM_INICIO") or "2026-10-01"
INICIO_BACKTEST_MOM = "2011-01-03"
AZUL, GRIS, NARANJA = "#2459D6", "#98A2B3", "#E07A1F"       # estilo claro: azul, gris, naranja
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  :root {--acento: #2459D6; --acento-suave: #EEF2FF; --fondo: #F6F7F9; --panel: #FFFFFF; --borde: #E4E7EC; --linea: #F0F2F5;
         --texto: #101828; --texto2: #5B6474; --texto3: #344054; --cabecera: #FAFBFC; --pista: #EEF0F3; --suave: #F2F4F7;
         --verde: #067647; --verde-f: #ECFDF3; --verde-b: #ABEFC6; --rojo: #B42318; --rojo-f: #FEF3F2; --rojo-b: #FECDCA;
         --naranja: #B93815; --naranja-f: #FFF4ED; --amarillo: #B54708; --amarillo-f: #FFFAEB; --amarillo-b: #FEDF89;
         --azul: #2459D6; --azul-f: #EEF2FF; --azul-b: #C7D7FE; --violeta: #6941C6; --violeta-f: #F4F3FF; --violeta-b: #D9D6FE;
         --gris: #475467; --gris-f: #F2F4F7;}
  /* modo oscuro: lo activa la app cuando el tema de Streamlit es oscuro (menú ⋮ → Settings) */
  body.tema-oscuro {--acento: #6E9BFF; --acento-suave: rgba(110,155,255,.14); --fondo: #0B1220; --panel: #111A2E; --borde: #23304A;
         --linea: #1B263C; --texto: #E6EAF2; --texto2: #98A2B3; --texto3: #C5CCD8; --cabecera: #0F1729; --pista: #23304A; --suave: #1B263C;
         --verde: #47CD89; --verde-f: rgba(18,183,106,.16); --verde-b: rgba(71,205,137,.35); --rojo: #F97066; --rojo-f: rgba(240,68,56,.16);
         --rojo-b: rgba(249,112,102,.35); --naranja: #FD853A; --naranja-f: rgba(253,133,58,.15); --amarillo: #FDB022; --amarillo-f: rgba(253,176,34,.14);
         --amarillo-b: rgba(253,176,34,.35); --azul: #84ADFF; --azul-f: rgba(110,155,255,.16); --azul-b: rgba(110,155,255,.35);
         --violeta: #BDB4FE; --violeta-f: rgba(155,138,251,.16); --violeta-b: rgba(155,138,251,.35); --gris: #C5CCD8; --gris-f: #1B263C;}
  .stApp {background-color: var(--fondo);}
  html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp button, .stApp input, .stApp textarea,
  [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"] {font-family: 'Inter', system-ui, sans-serif;}
  .stApp h1, .stApp h2, .stApp h3 {font-family: 'Inter', system-ui, sans-serif; letter-spacing: -.02em; color: var(--texto);}
  .stApp h1 {font-weight: 700; font-size: 2rem;}
  .stApp h3 {font-size: 1.1rem; font-weight: 700;}
  .block-container {padding-top: 2.6rem; max-width: 1280px;}
  header[data-testid="stHeader"] {background: transparent;}
  [data-testid="stCaptionContainer"] {color: var(--texto2);}
  .kicker {font-size: .75rem; font-weight: 600; letter-spacing: .08em; color: var(--acento); margin: 0 0 -.4rem 0; text-transform: uppercase;}
  .num, .tbl td.n {font-variant-numeric: tabular-nums;}

  /* tarjetas de números */
  div[data-testid="stMetric"] {background: var(--panel); border: 1px solid var(--borde); border-radius: 14px; padding: .9rem 1rem .8rem 1rem;
      min-height: 8.4rem; box-sizing: border-box;}
  div[data-testid="stMetricLabel"] p {color: var(--texto2) !important; font-size: .82rem; font-weight: 500;}
  div[data-testid="stMetricValue"] {font-size: 1.45rem; font-weight: 700; color: var(--texto); letter-spacing: -.02em; font-variant-numeric: tabular-nums;}
  div[data-testid="stMetricLabel"] p, div[data-testid="stMetricLabel"] div, div[data-testid="stMetricDelta"] div {white-space: normal !important; overflow: visible !important; text-overflow: clip !important;}

  /* avisos */
  .aviso {padding: .75rem 1rem; border-radius: 12px; margin: .25rem 0 .8rem 0; font-size: .95rem; color: var(--texto3);
      background: var(--panel); border: 1px solid var(--borde);}
  .aviso-azul {background: var(--azul-f); border-color: var(--azul-b);}
  .aviso-naranja {background: var(--amarillo-f); border-color: var(--amarillo-b);}
  .aviso-rojo {background: var(--rojo-f); border-color: var(--rojo-b);}
  .aviso-verde {background: var(--verde-f); border-color: var(--verde-b);}
  .aviso-violeta {background: var(--violeta-f); border-color: var(--violeta-b);}

  /* chips */
  .leyenda {font-size: .85rem; margin: -.2rem 0 .6rem 0; line-height: 2.2;}
  .chip {display: inline-block; padding: .12rem .65rem; border-radius: 999px; margin-right: .35rem; font-weight: 600; font-size: .76rem;
      line-height: 1.5; white-space: nowrap;}

  /* pestañas */
  .stTabs [data-baseweb="tab-list"] {gap: .2rem; border-bottom: 1px solid var(--borde);}
  .stTabs [data-baseweb="tab"] {font-size: .92rem; font-weight: 500; color: var(--texto2); padding: .5rem .8rem;}
  .stTabs [aria-selected="true"] {color: var(--texto) !important;}
  .stTabs [data-baseweb="tab-highlight"] {background-color: var(--acento) !important;}

  /* tablas propias (sin cuadrícula de planilla) */
  .tbl-wrap {background: var(--panel); border: 1px solid var(--borde); border-radius: 14px; overflow: auto; margin: .2rem 0 .9rem 0;}
  table.tbl {width: 100%; border-collapse: separate; border-spacing: 0; font-size: .86rem; color: var(--texto); border: 0 !important; margin: 0 !important;}
  table.tbl th, table.tbl td {border-left: 0 !important; border-right: 0 !important; border-top: 0 !important;}
  table.tbl th {position: sticky; top: 0; z-index: 1; background: var(--cabecera); text-align: left; font-size: .7rem; font-weight: 600;
      color: var(--texto2); text-transform: uppercase; letter-spacing: .04em; padding: .6rem .6rem; border-bottom: 1px solid var(--borde);}
  table.tbl td {padding: .55rem .6rem; border-bottom: 1px solid var(--linea) !important; vertical-align: middle;}
  table.tbl tr:last-child td {border-bottom: 0;}
  table.tbl tr:hover td {background: var(--cabecera);}
  table.tbl th.n, table.tbl td.n {text-align: right; white-space: nowrap;}
  table.tbl td.largo {min-width: 170px; color: var(--texto3); font-size: .84rem;}
  .tk {display: inline-flex; align-items: center; gap: .55rem; font-weight: 600; white-space: nowrap;}
  .nomtk {display: flex; flex-direction: column; line-height: 1.25; white-space: normal; min-width: 120px;}
  .nomtk small {font-weight: 500; color: var(--texto2); font-size: .74rem;}
  .logo {display: inline-flex; align-items: center; justify-content: center; flex: none; border-radius: 8px; overflow: hidden;
      background: #FFFFFF; border: 1px solid var(--borde); color: #FFFFFF; font-weight: 700;}
  .logo {position: relative;}
  .logo img {position: absolute; inset: 0; margin: auto; width: 78%; height: 78%; object-fit: contain; background: #FFFFFF;}
  .logo.con-img {color: transparent;}
  .barra {display: flex; align-items: center; gap: .5rem; min-width: 90px;}
  table.exp a.emp {display: flex; align-items: center; gap: .65rem; color: var(--texto); text-decoration: none;}
  table.exp a.emp:hover b {color: var(--acento); text-decoration: underline;}
  table.exp a.emp span {display: flex; flex-direction: column; line-height: 1.25;}
  table.exp a.emp small {color: var(--texto2); font-size: .74rem;}
  table.exp td.sec {color: var(--texto3); font-size: .84rem;}
  table.exp td .chip {margin: .1rem .25rem .1rem 0;}
  .barra > span:first-child {flex: 1; height: 6px; background: var(--pista); border-radius: 99px; overflow: hidden; display: block;}
  .barra i {display: block; height: 100%; background: var(--acento); border-radius: 99px;}

  /* movimientos como tarjetas */
  .dia {display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; margin: 1.1rem 0 .6rem 0;}
  .dia .punto {width: 10px; height: 10px; border-radius: 99px; background: var(--acento);}
  .dia b {font-size: .98rem; color: var(--texto);}
  .dia .cuenta {margin-left: auto; font-size: .82rem; color: var(--texto2);}
  .grilla {display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: .75rem; padding-left: 1.1rem;
      border-left: 2px solid var(--borde); margin-left: 4px;}
  .tarjeta {background: var(--panel); border: 1px solid var(--borde); border-radius: 14px; padding: .9rem 1rem; display: flex;
      flex-direction: column; gap: .65rem;}
  .tarjeta .cab {display: flex; align-items: center; gap: .7rem;}
  .tarjeta .cab .nom {flex: 1; min-width: 0; display: flex; flex-direction: column;}
  .tarjeta .cab .nom b {color: var(--texto); font-size: .95rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
  .tarjeta .cab .nom span {font-size: .76rem; color: var(--texto2);}
  .tarjeta .datos {display: flex; flex-wrap: wrap; gap: 1.2rem;}
  .tarjeta .datos div {display: flex; flex-direction: column;}
  .tarjeta .datos span {font-size: .72rem; color: var(--texto2);}
  .tarjeta .datos b {font-size: .92rem; font-variant-numeric: tabular-nums;}
  .tarjeta p {margin: 0; font-size: .84rem; color: var(--texto3); line-height: 1.45;}

  /* ficha de empresa */
  .ficha-cab {background: var(--panel); border: 1px solid var(--borde); border-radius: 16px; padding: 1.2rem 1.3rem; display: flex;
      flex-wrap: wrap; align-items: center; gap: 1.1rem; margin-bottom: .8rem;}
  .ficha-cab h2 {margin: 0 !important; padding: 0 !important; font-size: 1.7rem !important;}
  .etiquetas {display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .35rem;}
  .etiquetas span {padding: .15rem .65rem; border-radius: 999px; background: var(--suave); color: var(--texto3); font-size: .78rem;}
  .caja {background: var(--panel); border: 1px solid var(--borde); border-radius: 14px; padding: 1rem 1.1rem; height: 100%;}
  .caja .tit {margin: 0 0 .5rem 0; font-size: .95rem; font-weight: 700; color: var(--texto);}
  .filtro {display: flex; align-items: center; gap: .6rem; padding: .45rem 0; border-bottom: 1px solid var(--linea); font-size: .88rem;}
  .filtro:last-child {border-bottom: 0;}
  .filtro .v {margin-left: auto; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap;}
  .ok, .no {width: 20px; height: 20px; border-radius: 99px; display: inline-flex; align-items: center; justify-content: center;
      font-size: .72rem; font-weight: 700; flex: none;}
  .ok {background: var(--verde-f); color: var(--verde);}
  .no {background: var(--rojo-f); color: var(--rojo);}
  .metricas {display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: .9rem;}
  .metricas span {display: block; font-size: .74rem; color: var(--texto2);}
  .metricas b {font-size: 1.1rem; font-variant-numeric: tabular-nums;}

  /* gráficos */
  div[data-testid="stVegaLiteChart"] {background: var(--panel); border: 1px solid var(--borde); border-radius: 14px; padding: .7rem .9rem;}
  div[data-testid="stDataFrame"] {border: 1px solid var(--borde); border-radius: 12px; overflow: hidden;}
  [class*="st-key-caja"] {background: var(--panel); border-radius: 14px !important; border-color: var(--borde) !important;}
  [class*="st-key-caja"] div[data-testid="stVegaLiteChart"] {border: 0; padding: 0;}

  /* menú lateral */
  section[data-testid="stSidebar"] {border-right: 1px solid var(--borde);}
  [data-testid="stSidebarNav"] a {border-radius: 10px; min-height: 44px;}
  [data-testid="stSidebarNav"] a[aria-current="page"] {background: var(--acento-suave);}
  .marca {display: flex; align-items: center; gap: .6rem; font-weight: 700; font-size: 1.1rem; letter-spacing: -.01em; color: var(--texto);}
  .pesos {display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: .75rem; margin: .5rem 0 .8rem 0;}
  .pesos div {background: var(--panel); border: 1px solid var(--borde); border-radius: 12px; padding: .8rem .9rem; display: flex; flex-direction: column; gap: .15rem;}
  .pesos span {font-size: .75rem; color: var(--texto2);}
  .pesos b {font-size: 1.15rem;}
  .pesos small {font-size: .74rem; color: var(--texto2);}
  /* inicio */
  .carteras {display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; margin: .4rem 0 1rem 0;}
  a.cartera {background: var(--panel); border: 1px solid var(--borde); border-radius: 16px; padding: 1.1rem; display: flex;
      flex-direction: column; gap: .8rem; color: var(--texto) !important; text-decoration: none !important;}
  a.cartera:hover {border-color: var(--azul-b); box-shadow: 0 1px 8px rgba(16,24,40,.06);}
  a.cartera .cab {display: flex; justify-content: space-between; align-items: center; font-size: .78rem; font-weight: 600;
      color: var(--texto2); text-transform: uppercase; letter-spacing: .04em;}
  a.cartera .cab .chip {text-transform: none; letter-spacing: 0;}
  a.cartera .valor {font-size: 1.75rem; font-weight: 700; letter-spacing: -.02em;}
  a.cartera .valor small {font-size: .8rem; font-weight: 500; color: var(--texto2); margin-left: .4rem;}
  a.cartera .datos {display: flex; flex-wrap: wrap; gap: 1.1rem;}
  a.cartera .datos div {display: flex; flex-direction: column;}
  a.cartera .datos span {font-size: .74rem; color: var(--texto2);}
  a.cartera .datos b {font-size: .9rem; font-variant-numeric: tabular-nums;}
  a.cartera .logos {display: flex; flex-wrap: wrap; gap: .35rem; min-height: 28px;}
  a.cartera .pie {border-top: 1px solid var(--linea); padding-top: .7rem; font-size: .84rem; color: var(--texto3); margin-top: auto;}
  .caja-inicio {background: var(--panel); border: 1px solid var(--borde); border-radius: 16px; padding: 1rem 1.2rem; margin-bottom: 1rem;}
  .caja-inicio .tit {font-size: 1.05rem; font-weight: 700; margin-bottom: .4rem;}
  .caja-inicio p {margin: .6rem 0 0 0; font-size: .78rem; color: var(--texto2);}
  .tarea {display: flex; align-items: flex-start; gap: .9rem; padding: .75rem 0; border-top: 1px solid var(--linea);}
  .tarea > div {flex: 1; display: flex; flex-direction: column; gap: .15rem;}
  .tarea b {font-size: .92rem;}
  .tarea > div span {font-size: .85rem; color: var(--texto3); line-height: 1.5;}
  .tarea .fecha {min-width: 62px; text-align: center; padding: .35rem .5rem; border-radius: 10px; font-size: .82rem; font-weight: 700;
      background: var(--suave); color: var(--texto3); font-variant-numeric: tabular-nums;}
  .tarea .fecha.urgente {background: var(--amarillo-f); color: var(--amarillo);}
  .fila-d {display: flex; justify-content: space-between; align-items: center; gap: .6rem; padding: .6rem 0; border-top: 1px solid var(--linea); font-size: .9rem;}
  .fila-d:first-child {border-top: 0;}
  .tit-sec {font-size: 1.02rem; font-weight: 700; margin: .4rem 0 .5rem 0;}
  iframe {border: 0;}
</style>
""", unsafe_allow_html=True)


def encabezado(kicker, titulo):
    """Título de página con una línea chica en cian arriba (estilo del dashboard)."""
    st.markdown(f"<div class='kicker'>{kicker}</div>", unsafe_allow_html=True)
    st.title(titulo)


# ============================================================================ colores
# Colores para fondo claro (verde y rojo también difieren en luminosidad, no solo en tono)
VERDE = "#12B76A"           # para gráficos (se lee en modo claro y oscuro)
# para texto y etiquetas: variables CSS que cambian con el modo claro u oscuro
T_VERDE, T_ROJO, T_AMARILLO, T_NARANJA = "var(--verde)", "var(--rojo)", "var(--amarillo)", "var(--naranja)"
ROJO, AMARILLO, VIOLETA, CELESTE = T_ROJO, T_AMARILLO, "var(--violeta)", "var(--azul)"
_FONDO = {"verde": (T_VERDE, "var(--verde-f)"), "rojo": (T_ROJO, "var(--rojo-f)"), "naranja": (T_NARANJA, "var(--naranja-f)"),
          "amarillo": (T_AMARILLO, "var(--amarillo-f)"), "azul": (CELESTE, "var(--azul-f)"), "violeta": (VIOLETA, "var(--violeta-f)"),
          "gris": ("var(--gris)", "var(--gris-f)")}


def css_color(nombre):
    """Estilo de celda: fondo suave y letra del color."""
    if nombre not in _FONDO:
        return ""
    txt, fondo = _FONDO[nombre]
    return f"background-color: {fondo}; color: {txt}; font-weight: 600"


def chip(texto, nombre):
    txt, fondo = _FONDO.get(nombre, _FONDO["gris"])
    return f"<span class='chip' style='background: {fondo}; color: {txt}'>{texto}</span>"


# Tipo de movimiento: (prefijo, ícono, color). Se busca por prefijo, en este orden.
ORDENES = [("ROTAR", "", "violeta"), ("VENDER", "", "rojo"), ("COMPRAR", "", "verde"), ("RECORTAR", "", "naranja"),
           ("SUMAR", "", "azul"), ("REFORZAR", "", "azul")]


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
    return f"color: {T_VERDE if v > 0 else T_ROJO}; font-weight: 600"


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


# ============================================================================ logos
try:
    import universo as U          # noqa: E402
    DOMINIOS = U.dominios()
    # webs cuyo ícono no es el logo conocido de la marca
    DOMINIOS.update({"GOOGL": "google.com", "GOOG": "google.com"})
except Exception:                 # noqa: BLE001
    U, DOMINIOS = None, {}
try:
    LOGO_TOKEN = st.secrets.get("LOGO_DEV_TOKEN", "")
except Exception:                 # noqa: BLE001
    LOGO_TOKEN = ""
TONOS = ["#1D4ED8", "#047857", "#B45309", "#7C3AED", "#BE123C", "#0E7490", "#4D7C0F", "#9D174D"]


def logo_url(t):
    """Logo de la empresa: logo.dev si hay clave (LOGO_DEV_TOKEN en los Secrets), si no el ícono de su web."""
    t = str(t)
    if LOGO_TOKEN:
        return f"https://img.logo.dev/ticker/{t.split('-')[0]}?token={LOGO_TOKEN}&size=80&format=png&retina=true"
    d = DOMINIOS.get(t)
    return f"https://www.google.com/s2/favicons?domain={d}&sz=128" if d else None


def logo_html(t, tam=26):
    """Logo de la empresa; si no hay o no carga, un cuadrado de color con las iniciales."""
    t = str(t)
    url = logo_url(t)
    tono = TONOS[sum(map(ord, t)) % len(TONOS)]
    base = (f"width:{tam}px;height:{tam}px;font-size:{max(9, int(tam * .38))}px;")
    if url:
        return (f"<span class='logo' style='{base}'><img src='{html.escape(url)}' alt='' loading='lazy' "
                f"onerror=\"this.parentNode.style.background='{tono}';this.parentNode.style.borderColor='{tono}';this.remove()\">"
                f"{html.escape(t[:2])}</span>")
    return f"<span class='logo' style='{base}background:{tono};border-color:{tono}'>{html.escape(t[:2])}</span>"


def ticker_html(t, tam=24):
    return f"<span class='tk'>{logo_html(t, tam)}{html.escape(str(t))}</span>"


def _css_a_chip(css, texto):
    """Estilo de celda (fondo + color) -> etiqueta redondeada; solo color -> texto coloreado."""
    if not css:
        return texto, ""
    if "background-color" in css:
        partes = {a.strip(): b for a, b in (x.split(":", 1) for x in css.split(";") if ":" in x)}
        fondo, color = partes.get("background-color", "").strip(), partes.get("color", "").strip()
        return f"<span class='chip' style='background:{fondo};color:{color}'>{texto}</span>", ""
    return texto, css


def tabla(df, fmt=None, signo=(), estilos=None, fechas=(), orden=None, config=None, height=None):
    """Tabla limpia en HTML (sin cuadrícula de planilla).
    fmt: {columna: '%+.1f%%'} · signo: columnas en verde (positivo) o rojo (negativo) · estilos: {columna: función valor -> css}
    fechas: columnas de fecha (dd/mm/aaaa) · orden: columna con el tipo de movimiento · config: column_config (título, ayuda,
    barra de progreso)."""
    df = df.reset_index(drop=True).copy()
    config = dict(config or {})
    unir = "Acción" in df and "Empresa" in df       # una sola columna: logo, nombre y ticker (menos ancho)
    sectores = {}
    if unir:
        nombres = dict(zip(df["Acción"], df["Empresa"]))
        df = df.drop(columns=["Empresa"])
        if "Sector" in df:            # el sector va en la línea chica debajo del nombre
            sectores = dict(zip(df["Acción"], df["Sector"]))
            df = df.drop(columns=["Sector"])
        config.setdefault("Acción", {"label": "Empresa"})
    fm = {c: (f if callable(f) else _fmt_num(f)) for c, f in (fmt or {}).items() if c in df}
    for c in fechas:
        if c in df:
            fm[c] = _fmt_fecha_corta
    cab, cuerpo = [], []
    tipos = {}
    for c in df.columns:
        cfg = config.get(c) or {}
        cfg = cfg if isinstance(cfg, dict) else {}
        tc = cfg.get("type_config") or {}
        barra = tc if tc.get("type") == "progress" else None
        num = (c in fm and c not in fechas and not callable((fmt or {}).get(c))) or c in signo or barra or (
            pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c]))
        largo = cfg.get("width") == "large" or c in ("Motivo", "Motivos para revisar", "Falla en")
        tipos[c] = (barra, num, largo)
        etiqueta = cfg.get("label") or c
        ayuda = cfg.get("help")
        cab.append(f"<th class='{'n' if num and not barra else ''}'" + (f" title='{html.escape(ayuda)}'" if ayuda else "")
                   + f">{html.escape(str(etiqueta))}</th>")
    for _, fila in df.iterrows():
        celdas = []
        for c in df.columns:
            v = fila[c]
            barra, num, largo = tipos[c]
            vacio = v is None or (not isinstance(v, (list, dict, str)) and pd.isna(v))
            if barra and not vacio:
                lo, hi = barra.get("min_value") or 0, barra.get("max_value") or 100
                ancho = max(0, min(100, (float(v) - lo) / (hi - lo) * 100)) if hi > lo else 0
                f_ = barra.get("format") or "%.0f"
                txt = (f_ % float(v)).replace(".", ",") if "%" in f_ else str(v)
                celdas.append(f"<td><span class='barra'><span><i style='width:{ancho:.1f}%'></i></span><b class='num'>{txt}</b></span></td>")
                continue
            if vacio:
                txt = ""
            elif c in fm:
                txt = html.escape(str(fm[c](v)))
            elif isinstance(v, float):
                txt = (f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}").replace(",", "X").replace(".", ",").replace("X", ".")
            elif isinstance(v, (pd.Timestamp, date)):
                txt = _fmt_fecha_corta(v)
            else:
                txt = html.escape(str(v))
            estilo = ""
            if c in signo and not vacio:
                estilo = color_signo(v)
            if estilos and c in estilos and not vacio:
                txt, estilo2 = _css_a_chip(estilos[c](v), txt)
                estilo = estilo2 or estilo
            if orden and c == orden and not vacio:
                txt = chip(html.escape(str(v).capitalize()), _orden(v)[1] or "gris")
            if c == "Acción" and not vacio and not str(v).startswith("SPY"):
                if unir and isinstance(nombres.get(v), str) and nombres.get(v):
                    sec = sectores.get(v)
                    txt = (f"<span class='tk'>{logo_html(v, 28)}<span class='nomtk'><b>{html.escape(nombres[v])}</b>"
                           f"<small>{html.escape(str(v))}{' · ' + html.escape(str(sec)) if isinstance(sec, str) and sec else ''}</small></span></span>")
                else:
                    txt = ticker_html(v)
            clase = "n" if num else ("largo" if largo else "")
            celdas.append(f"<td class='{clase}'" + (f" style='{estilo}'" if estilo else "") + f">{txt}</td>")
        cuerpo.append("<tr>" + "".join(celdas) + "</tr>")
    alto = f"max-height:{int(height)}px;" if height else ("max-height:620px;" if len(df) > 16 else "")
    st.markdown(f"<div class='tbl-wrap' style='{alto}'><table class='tbl'><thead><tr>{''.join(cab)}</tr></thead>"
                f"<tbody>{''.join(cuerpo)}</tbody></table></div>".replace("$", "&#36;"), unsafe_allow_html=True)


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
    return ("+USD " if g > 0 else "-USD ") + f"{abs(g):,.0f}".replace(",", ".")


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
    lineas = base.mark_line(strokeWidth=2.4).encode(y=y, color=alt.Color("Serie:N", scale=esc, legend=alt.Legend(orient="top", title=None)))
    cerca = alt.selection_point(nearest=True, on="pointerover", fields=["Fecha"], empty=False)
    puntos = base.mark_point(size=55, filled=True).encode(
        y=y, color=alt.Color("Serie:N", scale=esc, legend=None), opacity=alt.condition(cerca, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("Fecha:T", format="%d/%m/%Y"), "Serie:N", alt.Tooltip("Valor:Q", format=",.0f", title="USD")]).add_params(cerca)
    regla = base.mark_rule(color="#98A2B3").encode(opacity=alt.condition(cerca, alt.value(0.5), alt.value(0))).transform_filter(cerca)
    capas = lineas + puntos + regla
    if marca:
        m = pd.DataFrame({"Fecha": [pd.Timestamp(marca[0])], "txt": [marca[1]]})
        capas += alt.Chart(m).mark_rule(strokeDash=[3, 3], color="#98A2B3").encode(x="Fecha:T", tooltip=["txt:N"])
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
    cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#98A2B3").encode(y="y:Q")
    st.altair_chart((ch + cero).properties(height=280), width="stretch")


PALETA_SECTORES = ["#2459D6", "#0E9384", "#DC6803", "#7A5AF8", "#E04F16", "#D92D20", "#155EEF", "#C11574", "#4CA30D", "#667085"]


def grafico_pesos(pesos, objetivo, tope, etiqueta_tope, sector_fn=None):
    d = pesos.sort_values(ascending=False).reset_index()
    d.columns = ["Acción", "Peso"]
    d["Sector"] = [("Liquidez" if str(t).startswith("SPY") else sector_fn(t)) if sector_fn else "" for t in d["Acción"]]
    sectores = [s for s in dict.fromkeys(d["Sector"]) if s != "Liquidez"]
    dom = sectores + (["Liquidez"] if "Liquidez" in set(d["Sector"]) else [])
    rng = [PALETA_SECTORES[i % len(PALETA_SECTORES)] for i in range(len(sectores))] + (["#98A2B3"] if "Liquidez" in dom else [])
    color = (alt.Color("Sector:N", scale=alt.Scale(domain=dom, range=rng), legend=alt.Legend(orient="top", title=None))
             if sector_fn else alt.value(AZUL))
    barras = alt.Chart(d).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=26).encode(
        x=alt.X("Acción:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Peso:Q", title="% de la cartera", scale=alt.Scale(domain=[0, max(tope + 3, float(d["Peso"].max()) + 3)]),
                axis=alt.Axis(gridOpacity=0.25)),
        color=color,
        tooltip=["Acción:N", "Sector:N", alt.Tooltip("Peso:Q", format=".1f", title="% de la cartera")])
    reglas = alt.Chart(pd.DataFrame({"y": [objetivo, tope], "Línea": [f"objetivo {objetivo:.0f}%", etiqueta_tope]})).mark_rule(
        strokeDash=[4, 4], color="#98A2B3").encode(y="y:Q", tooltip=["Línea:N"])
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
    vista = st.segmented_control("Vista", ["Tarjetas", "Tabla"], default="Tarjetas", key=f"{clave}_vista",
                                 label_visibility="collapsed")
    if vista != "Tabla":
        movimientos_tarjetas(f, clave)
        return
    tabla(f[["Fecha", "Origen", "Orden", "Acción", "Empresa", "Peso", "Resultado", "Motivo"]],
          fmt={"Peso": "%.1f%%", "Resultado": "%+.0f%%"}, signo=["Resultado"], fechas=["Fecha"], orden="Orden",
          estilos={"Origen": ORIGEN_COLOR}, height=min(36 * (len(f) + 1) + 3, 560), config={
              "Peso": st.column_config.Column("% de la cartera"),
              "Resultado": st.column_config.Column("Resultado", help="Solo en ventas: ganancia o pérdida de la posición"),
              "Motivo": st.column_config.Column(width="large")})


def movimientos_tarjetas(f, clave, por_pagina=8):
    """Movimientos agrupados por fecha, una tarjeta por orden (los más recientes primero)."""
    cedear_fn = C.cedear
    fechas = list(dict.fromkeys(f["Fecha"].dt.normalize()))
    k_mas = f"{clave}_mostrar"
    n = st.session_state.get(k_mas, por_pagina)
    partes = []
    for d in fechas[:n]:
        g = f[f["Fecha"].dt.normalize() == d]
        origenes = " · ".join(dict.fromkeys(str(o) for o in g["Origen"] if pd.notna(o)))
        dia = f"{['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'][d.weekday()]} {fmt_fecha(d)}"
        partes.append(f"<div class='dia'><span class='punto'></span><b>{dia}</b>{chip(html.escape(origenes), 'gris') if origenes else ''}"
                      f"<span class='cuenta'>{len(g)} {'orden' if len(g) == 1 else 'órdenes'}</span></div><div class='grilla'>")
        for _, o in g.iterrows():
            t = str(o["Acción"])
            ced = cedear_fn(t)
            datos = []
            if pd.notna(o.get("Peso")):
                datos.append(("% de la cartera", pct(o["Peso"], 1, False)))
            if pd.notna(o.get("Resultado")):
                col = T_VERDE if o["Resultado"] > 0 else T_ROJO
                datos.append(("Resultado", f"<span style='color:{col}'>{pct(o['Resultado'], 0)}</span>"))
            partes.append(
                "<div class='tarjeta'><div class='cab'>" + logo_html(t, 38) +
                f"<div class='nom'><b>{html.escape(str(o.get('Empresa') or t))}</b><span>{html.escape(t)}"
                + (f" · CEDEAR {html.escape(ced)}" if ced else "") + "</span></div>"
                + chip(html.escape(str(o["Orden"]).upper()), _orden(o["Orden"])[1] or "gris") + "</div>"
                + ("<div class='datos'>" + "".join(f"<div><span>{a}</span><b>{b}</b></div>" for a, b in datos) + "</div>" if datos else "")
                + (f"<p>{html.escape(str(o['Motivo']))}</p>" if isinstance(o.get("Motivo"), str) and o["Motivo"] else "")
                + "</div>")
        partes.append("</div>")
    st.markdown("".join(partes).replace("$", "&#36;"), unsafe_allow_html=True)
    if len(fechas) > n:
        if st.button(f"Mostrar más ({len(fechas) - n} fechas más)", key=f"{clave}_mas_btn"):
            st.session_state[k_mas] = n + por_pagina
            st.rerun()


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


def _cierre_anterior(cierre):
    """Día hábil anterior a 'cierre' (lo precalculado de anoche sigue sirviendo hasta que GitHub corra de nuevo)."""
    d = pd.Timestamp(cierre) - pd.offsets.BDay(1)
    return d.strftime("%Y-%m-%d")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def datos_momentum(inicio_real, cierre=None, universo=None):
    d = CALC.cargar("momentum", _cierre_anterior(cierre) if cierre else None, inicio=inicio_real)
    return d if d is not None else CALC.datos_momentum(inicio_real)


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def niveles_calidad(semana, universo=None):
    d = CALC.cargar("niveles")
    return d if d is not None else CALC.niveles_calidad()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def datos_reversion(version, reglas, cierre=None, universo=None, niveles=None):
    d = CALC.cargar("reversion", _cierre_anterior(cierre) if cierre else None)
    return d if d is not None else CALC.datos_reversion(dict(niveles or {}))



def leer_json(nombre):
    p = RAIZ / nombre
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None







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


def ranking_vigente(panel):
    """Ranking de calidad para mostrar: el del explorador (se recalcula todos los domingos con el universo ampliado) si es
    más nuevo que la última revisión; si no, el de la revisión. Solo cambia lo que se ve: las órdenes salen de la revisión."""
    panel = panel or {}
    ex = leer_json("explorador_calidad.json") or {}
    if ex.get("empresas") and ex.get("fecha", "") > panel.get("fecha", ""):
        filas = []
        for t, e in ex["empresas"].items():
            if not e.get("pasa") or e.get("puesto") is None:
                continue
            filas.append({"Acción": t, "Puesto": int(e["puesto"]), "Puntaje": e.get("puntaje"), "Orden": e.get("orden"),
                          "Sector": C.sector(t), "tipo": e.get("tipo"), "Rentabilidad": e.get("rent_prom"),
                          "Ventas": e.get("ventas_cagr"), "Deuda": e.get("deuda_ebitda") if e.get("tipo") != "financiera" else None,
                          "Rend10": e.get("rend_esperado"), "Tendencia": e.get("mom_pct"), "comprable": bool(e.get("comprable")),
                          "castigada": bool(e.get("castigada")), "precio_extremo": bool(e.get("precio_extremo")),
                          "Precio": e.get("precio"), "PrecioCompra": e.get("precio_compra")})
        rk = pd.DataFrame(filas)
        if len(rk):
            rk = rk.sort_values("Puesto").head(30).reset_index(drop=True)
            info = {"fecha": ex["fecha"], "total": len(ex["empresas"]), "pasan": len(filas),
                    "comprables": sum(1 for f in filas if f["comprable"]), "fuente": "semanal"}
            return rk, info
    rk = pd.DataFrame(panel.get("ranking", []))
    info = {"fecha": panel.get("fecha"), "total": panel.get("total"), "pasan": panel.get("pasan"),
            "comprables": panel.get("comprables"), "fuente": "revision"}
    return rk, info


def pagina_calidad():
    encabezado("ESTRATEGIA · LARGO PLAZO", "Cartera de calidad")
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
    rank, info_rk = ranking_vigente(panel)
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
        st.subheader("Tu cartera en pesos", divider="gray")
        tabla_cartera_pesos(list(cart["Acción"]))
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
              config={"Rentabilidad %": st.column_config.Column("ROIC", help="ROIC (ROE en bancos) al comprar"),
                      "Ventas crec. %": st.column_config.Column("Ventas", help="Crecimiento anual de las ventas al comprar"),
                      "Rend. esperado %": st.column_config.Column("Rend. 10a", help="Rendimiento esperado a 10 años al comprar"),
                      "Puesto al comprar": st.column_config.Column("Puesto inicial"),
                      "Motivos para revisar": st.column_config.Column("Para revisar", width="large")})
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
            cuando = (f"Actualizado el {fmt_fecha(info_rk['fecha'])} (se recalcula todos los domingos con los precios de ese día; "
                      f"las órdenes salen de la revisión mensual)." if info_rk["fuente"] == "semanal"
                      else f"Revisión del {fmt_fecha(info_rk['fecha'])}.")
            st.markdown(f"De {info_rk['total']} empresas, **{info_rk['pasan']}** pasan los filtros mínimos y **{info_rk['comprables']}** de las 20 "
                        f"mejores son comprables (sin precio extremo ni tendencia en el 10% más bajo). {cuando}")
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
                ("en", "En cartera", "azul"), ("comprable", "Comprables", "verde"), ("precio", "Precio extremo", "naranja"),
                ("tendencia", "Tendencia muy débil", "rojo")) if cuenta.get(clave, 0)) + "</div>", unsafe_allow_html=True)

            def color_rend(v):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    return ""
                return "" if np.isnan(v) else f"color: {T_ROJO if v < 5 else T_VERDE if v >= 10 else T_AMARILLO}; font-weight: 600"
            tabla(r[["Puesto", "Acción", "Empresa", "Situación", "Sector", "Puntaje", "Rentabilidad", "Ventas", "Deuda", "Rend10", "Tendencia"]],
                  fmt={"Puesto": "%d", "Puntaje": "%.0f", "Rentabilidad": "%.0f%%", "Ventas": "%.0f%%", "Deuda": "%.1fx", "Rend10": "%.1f%%"},
                  estilos={"Rend10": color_rend, "Situación": SITUACION_CALIDAD}, height=560, config={
                      "Rentabilidad": st.column_config.Column("ROIC", help="ROIC promedio de 5 años (ROE en bancos)"),
                      "Ventas": st.column_config.Column("Ventas", help="Crecimiento anual de las ventas, 5 años"),
                      "Deuda": st.column_config.Column("Deuda", help="Deuda neta / EBITDA"),
                      "Rend10": st.column_config.Column("Rend. 10a", help="Rendimiento anual esperado a 10 años. Verde: 10% o más · amarillo: 5 a 10% · rojo: menos de 5% (precio extremo)"),
                      "Puntaje": st.column_config.ProgressColumn("Puntaje", format="%.0f", min_value=0, max_value=100),
                      "Tendencia": st.column_config.ProgressColumn("Tendencia", format="%.0f", min_value=0, max_value=100)})
            esp = r[(r["Puesto"] <= 20) & (~r["comprable"]) & (~r["Acción"].isin(en_cart))].copy()
            if len(esp):
                st.subheader("Lista de espera", divider="orange")
                st.caption("Entre las 20 mejores en calidad, pero hoy no se pueden comprar. Precio de compra = precio al que rendiría 10% anual. "
                           + (f"Precios del {pd.Timestamp(info_rk['fecha']).strftime('%d/%m/%Y')}." if info_rk.get("fecha") else ""))
                esp["Tiene que bajar %"] = (1 - esp["PrecioCompra"] / esp["Precio"]) * 100
                tabla(esp[["Puesto", "Acción", "Empresa", "Precio", "PrecioCompra", "Tiene que bajar %", "Situación"]],
                      fmt={"Puesto": "%d", "Precio": "%.2f", "PrecioCompra": "%.2f", "Tiene que bajar %": "%.0f%%"},
                      estilos={"Situación": SITUACION_CALIDAD, "Tiene que bajar %": lambda v: f"color: {T_NARANJA}; font-weight: 600"},
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
    encabezado("ESTRATEGIA · MENSUAL", "Momentum residual")
    st.caption("10 acciones con la mejor suba propia de los últimos 12 meses · se opera el primer día hábil de cada mes · se vende solo "
               "si sale del top 30")
    with st.spinner("Calculando con los precios de hoy (la primera vez tarda hasta un minuto)..."):
        d = datos_momentum(INICIO_MOM_REAL, ultimo_cierre(), MARCA_UNIVERSO)
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
        st.markdown("<div class='leyenda'>" + chip("En cartera", "azul") + chip("Top 10 que no entra (cartera llena)", "gris")
                    + chip("25 a 30: zona de salida", "amarillo") + "</div>", unsafe_allow_html=True)
        tabla(rk[["Puesto", "Acción", "Empresa", "Situación", "CEDEAR", "Sector", "Suba 12-1 %", "Volatilidad %", "Puntaje"]],
              fmt={"Puesto": "%d", "Suba 12-1 %": "%+.0f%%", "Volatilidad %": "%.0f%%", "Puntaje": "%.2f"}, signo=["Suba 12-1 %"],
              estilos={"Situación": SITUACION_MOM, "Puesto": lambda v: css_color("amarillo") if v >= 25 else ""}, height=560, config={
                  "Suba 12-1 %": st.column_config.Column("Suba 12 meses"), "Volatilidad %": st.column_config.Column("Volatilidad")})

    with tabs[5]:
        st.markdown(REGLAS_MOMENTUM)



# ============================================================================ página: reversión (screener)









NIVEL_COLOR = {"Premium": "amarillo", "Sólida": "azul", "Especulativa": "gris"}
FILTROS_CORTO = {"volumen": "Vol.", "emas": "EMAs", "correccion": "Correc.", "consolidacion": "Consolid.",
                 "valuacion": "P/E", "mercado": "Merc.", "beta": "Beta"}




def niveles_seguro():
    """Igual que niveles_calidad, pero si Yahoo falla devuelve vacío (la página sigue funcionando sin el nivel)."""
    if st.session_state.get("_niveles_fallo"):
        return {"niveles": {}, "fund": {}}
    try:
        return niveles_calidad(pd.Timestamp.today().strftime("%G-%V"), MARCA_UNIVERSO)
    except Exception:           # noqa: BLE001
        st.session_state["_niveles_fallo"] = True
        return {"niveles": {}, "fund": {}}


def pe_ok(fu, cfg):
    """Filtro de P/E del screener (está apagado: solo se muestra, como en el mail)."""
    pe = fu.get("pe_forward") if cfg["pe_tipo"] == "forward" else fu.get("pe_trailing")
    if pe is None or pd.isna(pe):
        return None if not fu else False
    mcap = fu.get("market_cap")
    lo, hi = cfg["pe_large_cap"] if (mcap and mcap >= cfg["large_cap_desde_usd"]) else cfg["pe_small_mid_cap"]
    return bool(lo <= pe <= hi)     # subir este número cuando cambie el cálculo, para que no se use la memoria vieja




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

**Cartera de 10 lugares:** cada señal entra con el 10% del valor de la cartera si hay lugar libre. Si el mismo día hay más
señales que lugares, entran primero las Premium, después las Sólidas y al final las Especulativas. La plata que no está en
ninguna operación queda invertida en el S&P 500 (SPY) hasta la próxima compra, así la comparación con el índice es pareja.
Costos: 0,5% por operación. Entrada y salida al cierre del día de la señal.

Análisis cuantitativo con fines educativos; no es una recomendación de inversión.
"""


def pagina_reversion():
    encabezado("ESTRATEGIA · DIARIA", "Reversión (screener)")
    if SCR is None:
        aviso("Falta <b>screener.py</b> en este repositorio. Copialo desde el repositorio del screener a la carpeta principal de "
              "este (al lado de calidad.py) y la página se arma sola. Acá solo se usa para calcular las señales: no manda mails.", "naranja")
        return
    st.caption("Empresas con CEDEAR que corrigieron 25-60%, con beta alto, consolidando y con el mercado a favor · mismo código que el "
               "mail diario del screener · dos reglas de salida para comparar")
    with st.spinner("Buscando el nivel de calidad de cada acción (una vez por semana)..."):
        nv = niveles_seguro()
    with st.spinner("Calculando señales desde 2010 con los precios de hoy (la primera vez tarda hasta un par de minutos)..."):
        niv_t = tuple(sorted(nv["niveles"].items()))
        d = datos_reversion(VERSION_REV, tuple(REGLAS_REV), ultimo_cierre(), MARCA_UNIVERSO, niv_t)
        if len(d["ops"]) and any(f"abierta_{r}" not in d["ops"] for r in REGLAS_REV):   # memoria de una versión anterior
            datos_reversion.clear()
            d = datos_reversion(VERSION_REV, tuple(REGLAS_REV), ultimo_cierre(), MARCA_UNIVERSO, niv_t)
    ops, hoy = d["ops"], d["hoy"]
    nivel_de = lambda t: nv["niveles"].get(t, "")
    estilo_nivel = lambda v: css_color(NIVEL_COLOR.get(v, ""))
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
            t_.insert(1, "Nivel", [nivel_de(x) for x in t_["Acción"]])
            en_cartera = set(ab["Ticker"]) if len(ab) else set()
            t_["_p"] = [CALC.PRIORIDAD_NIVEL.get(n, 3) for n in t_["Nivel"]]
            t_ = t_.sort_values(["_p", "Acción"])
            t_["Situación"] = ["ya en cartera: no repetir" if x in en_cartera else "🟢 comprar" for x in t_["Acción"]]
            tabla(t_[["Acción", "Nivel", "Empresa", "CEDEAR", "Precio", "Caída desde máx. %", "Beta", "Tendencia previa", "Situación"]],
                  fmt={"Precio": "%.2f", "Caída desde máx. %": "%.1f%%", "Beta": "%.2f"},
                  estilos={"Situación": por_prefijo({"🟢": "verde", "ya": "gris"}), "Nivel": estilo_nivel})
            st.caption("Cada compra, 10% de la cartera destinada a esta estrategia. Si hay más señales que lugares libres, primero las "
                       "Premium, después las Sólidas y al final las Especulativas (en ese orden aparecen en la tabla).")
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
        st.subheader("3. Tablero: las 30 más cercanas a dar señal", divider="gray")
        if len(hoy):
            cfg_s, act_s = SCR.CONFIG, SCR.FILTROS_ACTIVOS
            tb = hoy.sort_values(["Fallan", "Acción"]).head(30).copy()
            out = pd.DataFrame({"Acción": tb["Acción"].values, "Nivel": [nivel_de(x) for x in tb["Acción"]],
                                "Empresa": [C.nombre(x) for x in tb["Acción"]]})
            for f, corto in FILTROS_CORTO.items():
                if f == "valuacion":
                    v = [pe_ok(nv["fund"].get(x, {}), cfg_s) for x in tb["Acción"]]
                else:
                    v = list(tb["ok_" + f]) if "ok_" + f in tb else [None] * len(tb)
                out[corto] = ["Sí" if x is True else "No" if x is False else "" for x in v]
            out["Caída %"] = tb["Caída desde máx. %"].values
            out["Fallas"] = ["PASA" if k == 0 else str(int(k)) for k in tb["Fallan"]]
            def sino(activo):
                if not activo:
                    return lambda v: "color: #6F819E"
                return lambda v: css_color("verde" if v == "Sí" else "rojo" if v == "No" else "")
            est = {corto: sino(act_s[f]) for f, corto in FILTROS_CORTO.items()}
            est["Nivel"] = estilo_nivel
            est["Fallas"] = lambda v: css_color("verde") if v == "PASA" else css_color("amarillo") if v == "1" else ""
            tabla(out, fmt={"Caída %": "%.0f%%"}, estilos=est, height=min(38 + 35 * len(out), 1100))
            notas = ["Ordenadas por cantidad de filtros que les faltan. Verde = cumple, rojo = no cumple.",
                     "El P/E está apagado en la estrategia: se muestra solo como dato (en gris)."]
            if nv["niveles"]:
                notas.append("Nivel de calidad (solo informativo): Premium = 20 mejores por tamaño, ROE y margen; "
                             "Sólida = siguientes 50; Especulativa = resto.")
            else:
                notas.append("Hoy Yahoo no devolvió los datos para el nivel de calidad; se vuelve a intentar en la próxima visita.")
            st.caption(" ".join(notas))
        else:
            st.markdown("Sin datos para armar el tablero.")

    with tabs[1]:
        if not len(ab):
            st.info("No hay operaciones abiertas con esta regla.")
        else:
            t_ = ab.copy()
            t_.insert(1, "Empresa", [C.nombre(x) for x in t_["Ticker"]])
            t_.insert(1, "Nivel", [nivel_de(x) for x in t_["Ticker"]])
            t_["Precio actual"] = t_[f"precio_{reg}"]
            t_["Resultado %"] = t_[f"ret_{reg}"]
            t_["vs S&P %"] = t_[f"ret_{reg}"] - t_[f"spy_{reg}"]
            if reg == "6m":
                t_["Vender el"] = [(e + pd.offsets.BDay(SCR.CONFIG["mantener_ruedas"])) for e in t_["Entrada"]]
                t_["Ruedas restantes"] = t_["faltan_6m"]
                cols = ["Ticker", "Nivel", "Empresa", "Entrada", "Precio entrada", "Precio actual", "Resultado %", "vs S&P %", "Vender el", "Ruedas restantes"]
                fechas = ["Entrada", "Vender el"]
            else:
                t_["Vende en (USD)"] = t_["Precio entrada"] * (1 + TP_REV)
                t_["Le falta subir %"] = (t_["Vende en (USD)"] / t_["Precio actual"] - 1) * 100
                t_["Límite 12 meses"] = [(e + pd.offsets.BDay(MAX_TP_REV)) for e in t_["Entrada"]]
                cols = ["Ticker", "Nivel", "Empresa", "Entrada", "Precio entrada", "Precio actual", "Resultado %", "vs S&P %", "Vende en (USD)",
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
                  signo=["Resultado %", "vs S&P %"], fechas=fechas, estilos={"Nivel": estilo_nivel})
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
            st.caption("Cada señal entra con el 10% de la cartera si hay lugar; si el mismo día hay más señales que lugares, primero "
                       "las Premium, después las Sólidas y al final las Especulativas; con 10 operaciones abiertas, las señales nuevas se "
                       "saltean. El nivel es el de hoy (en el pasado pudo ser otro). La plata que no está en ninguna operación queda en el S&P 500 (SPY) hasta la próxima compra. "
                       "Costos de 0,5% por operación. La lista de acciones es la de hoy (sesgo de supervivencia).")
            st.subheader("Año por año", divider="gray")
            an = anual_desde({nom: cart, "S&P 500": s_})
            grafico_anual(an, {nom: VERDE, "S&P 500": GRIS})
            tabla_anual(an, nom)

    with tabs[4]:
        st.markdown(REGLAS_REVERSION)

# ============================================================================ página: explorador de empresas
def _f(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


def _x100(v):
    v = _f(v)
    return None if v is None else v * 100


def _p(v, dec=1):
    v = _f(v)
    return "—" if v is None else (f"{v * 100:.{dec}f}%").replace(".", ",")


def _marca_archivos(*nombres):
    return tuple((RAIZ / n).stat().st_mtime if (RAIZ / n).exists() else 0 for n in nombres)


@st.cache_data(ttl=3600, show_spinner=False)
def datos_explorador(marca):
    """Une el universo, las métricas de calidad, el momentum, el screener y las carteras en una tabla por empresa."""
    uni = [r for r in (U.todas() if U else []) if r.get("incluida") == "1"]
    if not uni:          # todavía no se generó universo.csv: la lista fija de siempre
        uni = [{"ticker": t, "nombre": n, "cedear": c, "sector": C.sector(t), "formulario": "10-K"} for t, (n, c) in C.CEDEARS.items()]
    ex = (leer_json("explorador_calidad.json") or {})
    emp = ex.get("empresas", {})
    pm = leer_json("panel_momentum.json") or {}
    ps = leer_json("panel_screener.json") or {}
    cal = leer_json("cartera_calidad.json") or {}
    en_cal = set() if str(cal.get("origen") or "").startswith("backtest") else set(cal.get("posiciones", {}))
    en_mom = {x["Acción"] for x in pm.get("cartera", [])}
    puesto_mom = {x["Acción"]: x["Puesto"] for x in pm.get("ranking", [])}
    scr = ps.get("filas", {})
    filas = []
    for r in uni:
        t = r["ticker"]
        e = emp.get(t, {})
        sc = scr.get(t, {})
        estado = []
        if t in en_cal:
            estado.append("Cartera calidad")
        if t in en_mom:
            estado.append("Cartera momentum")
        if sc.get("pasa"):
            estado.append("Señal reversión")
        if not estado:
            estado.append("Comprable (calidad)" if e.get("comprable") else "Pasa filtros de calidad" if e.get("pasa") else "—")
        vol = _f(r.get("volumen_usd")) or _f(e.get("volumen_usd"))
        filas.append({
            "Logo": logo_url(t), "Ticker": t, "Empresa": C.nombre(t) if t in C.CEDEARS else r.get("nombre") or t,
            "CEDEAR": r.get("cedear") or t, "Sector": r.get("sector") or C.sector(t),
            "Calidad": _f(e.get("puntaje")), "Puesto calidad": _f(e.get("puesto")),
            "ROIC/ROE": _x100(e.get("rent_prom")),
            "Ventas/año": _x100(e.get("ventas_cagr")),
            "Deuda/EBITDA": _f(e.get("deuda_ebitda")) if e.get("tipo") != "financiera" else None,
            "Rend. 10 años": _x100(e.get("rend_esperado")),
            "Puesto momentum": _f(puesto_mom.get(t)),
            "Caída desde máx.": _f(sc.get("caida")),
            "Volumen (USD M)": vol / 1e6 if vol else None,
            "Estado": " · ".join(estado),
            "_pasa": bool(e.get("pasa")), "_en": bool({t} & (en_cal | en_mom)), "_scr": bool(sc.get("pasa"))})
    df = pd.DataFrame(filas)
    info = {"fecha_cal": ex.get("fecha"), "fecha_mom": pm.get("fecha"), "fecha_scr": ps.get("fecha"),
            "n_mom": len(pm.get("ranking", [])), "n_pasan": sum(1 for e in emp.values() if e.get("pasa"))}
    return df, info


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def precio_5_anios(t, cierre):
    desde = (pd.Timestamp(date.today()) - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    px = precios_ajustados((t,), desde, cierre)
    return px


def ejercicio_txt(v):
    """'2025-12' -> 'cerró en dic-2025' (el ejercicio anual más reciente que presentó)."""
    try:
        f = pd.Timestamp(str(v) + "-01")
    except (ValueError, TypeError):
        return "—"
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"cerró en {meses[f.month - 1]}-{f.year}"


def ficha_empresa(t):
    uni = {r["ticker"]: r for r in (U.todas() if U else [])}
    r = uni.get(t, {})
    ex = (leer_json("explorador_calidad.json") or {})
    e = ex.get("empresas", {}).get(t, {})
    pm = leer_json("panel_momentum.json") or {}
    ps = leer_json("panel_screener.json") or {}
    cal = leer_json("cartera_calidad.json") or {}
    pos_cal = {} if str(cal.get("origen") or "").startswith("backtest") else cal.get("posiciones", {})
    nombre = C.nombre(t) if t in C.CEDEARS else (r.get("nombre") or t)
    ced = r.get("cedear") or C.cedear(t)
    fin = e.get("tipo") == "financiera"
    etiquetas = [f"{t}" + (f" · {r['bolsa']}" if r.get("bolsa") else ""),
                 f"CEDEAR {ced}" + (f" · ratio {r['ratio_cedear']}" if r.get("ratio_cedear") else ""),
                 r.get("sector") or C.sector(t)]
    if r.get("pais"):
        etiquetas.append(r["pais"])
    if r.get("formulario"):
        etiquetas.append(f"balances {r['formulario']}")
    est = []
    if t in pos_cal:
        est.append(chip("En cartera de calidad", "azul"))
    if any(x["Acción"] == t for x in pm.get("cartera", [])):
        est.append(chip("En cartera de momentum", "violeta"))
    if ps.get("filas", {}).get(t, {}).get("pasa"):
        est.append(chip("Señal de reversión", "verde"))
    st.markdown(
        f"<div class='ficha-cab'>{logo_html(t, 64)}<div style='flex:1;min-width:240px'><h2>{html.escape(nombre)}</h2>"
        f"<div class='etiquetas'>{''.join(f'<span>{html.escape(str(x))}</span>' for x in etiquetas if x)}</div>"
        f"<div style='margin-top:.5rem'>{''.join(est)}</div></div></div>", unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Puntaje de calidad" + (f" · puesto {int(e['puesto'])}" if _f(e.get("puesto")) else ""),
              f"{e['puntaje']:.1f}".replace(".", ",") if _f(e.get("puntaje")) is not None else "—",
              help=None if _f(e.get("puesto")) else ("No pasa los filtros mínimos" if e else "Sin balances en la SEC"))
    c2.metric("Rend. esperado a 10 años", _p(e.get("rend_esperado")), help="Rendimiento anual estimado comprando hoy (precio)")
    c3.metric("Tendencia", f"{_f(e.get('mom_pct')) * 100:.0f}".replace(".", ",") if _f(e.get("mom_pct")) is not None else "—",
              help="Percentil de momentum residual entre las empresas de calidad (100 = mejor)")
    pm_rank = {x["Acción"]: x for x in pm.get("ranking", [])}
    c4.metric("Puesto en momentum" + (f" · de {len(pm_rank)}" if t in pm_rank else ""),
              str(pm_rank[t]["Puesto"]) if t in pm_rank else "—")

    izq, der = st.columns([2, 1])
    with izq, st.container(border=True, key="caja_metricas"):
        h = e.get("hist") or {}
        st.markdown("<div style='margin:0;font-size:.95rem;font-weight:700;color:var(--texto)'>Métricas de los últimos 5 ejercicios</div>",
                    unsafe_allow_html=True)
        if h.get("anios"):
            opciones = {("ROE" if fin else "ROIC"): ("rent", True), "Ventas": ("ventas", False)}
            if not fin:
                opciones.update({"Margen bruto": ("margen_bruto", True), "Caja libre por acción": ("caja_accion", False)})
            else:
                opciones["Ganancia por acción"] = ("ganancia_accion", False)
            elegida = st.segmented_control("Métrica", list(opciones), default=list(opciones)[0], key=f"met_{t}",
                                           label_visibility="collapsed") or list(opciones)[0]
            clave, es_pct = opciones[elegida]
            d = pd.DataFrame({"Año": [str(a) for a in h["anios"]], "Valor": h.get(clave) or [None] * len(h["anios"])}).dropna()
            if es_pct:
                d["Valor"] = d["Valor"] * 100
            if len(d):
                ch = alt.Chart(d).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=34, color=AZUL).encode(
                    x=alt.X("Año:N", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("Valor:Q", title="%" if es_pct else None, axis=alt.Axis(gridOpacity=0.25, format=".0f" if es_pct else "~s")),
                    tooltip=["Año:N", alt.Tooltip("Valor:Q", format=".1f" if es_pct else ",.2f")])
                st.altair_chart(ch.properties(height=230), width="stretch")
        else:
            st.caption("Sin balances anuales en la SEC para esta empresa: entra en momentum y en el screener, no en calidad.")
        met = [("ROE promedio" if fin else "ROIC promedio", _p(e.get("rent_prom"))),
               ("Último año", _p(e.get("rent_ult"))), ("Ventas (por año)", _p(e.get("ventas_cagr"))),
               ("Caja por acción (por año)" if not fin else "Ganancia por acción (por año)", _p(e.get("crec_accion")))]
        if not fin:
            de = _f(e.get("deuda_ebitda"))
            met += [("Margen bruto", _p(e.get("mb_ult"))), ("Conversión en caja", _p(e.get("conversion"), 0)),
                    ("Deuda neta / EBITDA", "—" if de is None else "caja neta" if de <= 0 else "EBITDA negativo" if de >= 99
                     else f"{de:.1f}x".replace(".", ","))]
        met += [("Acciones en circulación (por año)", _p(e.get("dilucion"))),
                ("Último ejercicio anual", ejercicio_txt(e.get("ultimo_balance")))]
        st.markdown("<div class='metricas'>" + "".join(f"<div><span>{a}</span><b>{b}</b></div>" for a, b in met) + "</div>",
                    unsafe_allow_html=True)
    with der:
        filtros = []
        if e:
            rp, vc, dl, de = _f(e.get("rent_prom")), _f(e.get("ventas_cagr")), _f(e.get("dilucion")), _f(e.get("deuda_ebitda"))
            vol = _f(e.get("volumen_usd")) or _f(r.get("volumen_usd"))
            filtros.append((f"{'ROE' if fin else 'ROIC'} promedio ≥ 12%", rp is not None and rp >= C.KO_ROIC, _p(rp)))
            if not fin:
                filtros.append(("Deuda neta ≤ 3x EBITDA", de is not None and de <= C.KO_DEUDA,
                                "caja neta" if de is not None and de <= 0 else ("—" if de is None else f"{de:.1f}x".replace(".", ","))))
                genera = not any(str(k).startswith("no genera caja") for k in e.get("ko", []))
                filtros.append(("Genera caja", genera, "sí" if genera else "no"))
            filtros.append(("Ventas ≥ 5% por año", vc is not None and vc >= C.KO_VENTAS, _p(vc)))
            filtros.append(("Dilución ≤ 3% por año", dl is None or dl <= C.KO_DILUCION, _p(dl)))
            filtros.append(("Volumen > USD 20 M por día", vol is not None and vol >= C.VOL_MIN_USD,
                            f"USD {vol / 1e6:,.0f} M".replace(",", ".") if vol else "—"))
        cuerpo = "".join(f"<div class='filtro'><span class='{'ok' if ok else 'no'}'>{'✓' if ok else '✗'}</span>"
                         f"<span>{html.escape(n)}</span><span class='v'>{html.escape(str(v))}</span></div>" for n, ok, v in filtros)
        pie = ""
        if filtros:
            n_ok = sum(1 for _, ok, _ in filtros if ok)
            pie = (f"<p style='margin:.6rem 0 0 0;font-size:.85rem;font-weight:600;color:{T_VERDE if n_ok == len(filtros) else T_ROJO}'>"
                   f"{'Pasa los ' + str(len(filtros)) + ' filtros' if n_ok == len(filtros) else 'No pasa ' + str(len(filtros) - n_ok) + ' de ' + str(len(filtros))}</p>")
        st.markdown(f"<div class='caja'><div class='tit'>Filtros mínimos de calidad</div>{cuerpo or '<p>Sin datos de calidad.</p>'}{pie}</div>",
                    unsafe_allow_html=True)

    st.subheader("Precio contra el S&P 500 (5 años)", divider="gray")
    try:
        px = precio_5_anios(t, ultimo_cierre())
        if t in px and px[t].notna().sum() > 20:
            p_ = px[[t, "SPY"]].dropna()
            p_ = p_ / p_.iloc[0] * 10000
            grafico_evolucion(p_.rename(columns={t: nombre, "SPY": "S&P 500"}), {nombre: AZUL, "S&P 500": GRIS}, alto=280)
            st.caption("USD 10.000 invertidos hace 5 años, con dividendos.")
        else:
            st.caption("Sin precios para mostrar.")
    except Exception:       # noqa: BLE001
        st.caption("No se pudieron bajar los precios en este momento.")

    seccion_trimestres(t, e)
    seccion_pesos(t, r.get("ratio_cedear"), ced)

    st.subheader("Qué dice cada estrategia", divider="gray")
    k1, k2, k3 = st.columns(3)
    if t in pos_cal:
        p_ = pos_cal[t]
        txt = f"<b>En cartera desde el {pd.Timestamp(p_['fecha_entrada']).strftime('%d/%m/%Y')}</b>"
    elif e.get("comprable"):
        txt = f"<b>Comprable</b> (orden {int(e['orden'])} del ranking combinado)"
    elif e.get("pasa"):
        motivo = "precio extremo" if e.get("precio_extremo") else "tendencia muy débil" if e.get("castigada") else "fuera de las 20 mejores"
        txt = f"<b>Pasa los filtros</b>, pero hoy no se compra: {motivo}"
    elif e:
        txt = "<b>No pasa los filtros</b>: " + html.escape("; ".join(e.get("ko", [])[:3]))
    else:
        txt = "<b>Fuera de la estrategia</b>: no presenta balances en la SEC"
    k1.markdown(f"<div class='caja'><div class='tit'>Calidad</div><p style='margin:0;font-size:.9rem'>{txt}</p></div>", unsafe_allow_html=True)
    if t in pm_rank:
        en = next((x for x in pm.get("cartera", []) if x["Acción"] == t), None)
        txt = (f"<b>En cartera</b> desde el {pd.Timestamp(en['Desde']).strftime('%d/%m/%Y')} · puesto {pm_rank[t]['Puesto']}" if en
               else f"Puesto <b>{pm_rank[t]['Puesto']}</b> de {len(pm_rank)}" + (" · entre las 10 mejores" if pm_rank[t]["Puesto"] <= 10 else ""))
    else:
        txt = "Sin puesto: poco volumen o menos de 2 años de historia"
    k2.markdown(f"<div class='caja'><div class='tit'>Momentum</div><p style='margin:0;font-size:.9rem'>{txt}</p></div>", unsafe_allow_html=True)
    sc = ps.get("filas", {}).get(t)
    if sc:
        caida = _f(sc.get("caida"))
        txt = ("<b>Señal de compra hoy</b>" if sc.get("pasa") else "Sin señal hoy" + (f": falla en {html.escape(sc['falla_en'].lower())}" if sc.get("falla_en") else ""))
        if caida is not None:
            txt += f"<br><span style='color:var(--texto2);font-size:.82rem'>Caída desde el máximo de 2 años: {caida:.0f}%".replace(".", ",") + "</span>"
    else:
        txt = "Sin datos del screener todavía"
    k3.markdown(f"<div class='caja'><div class='tit'>Reversión</div><p style='margin:0;font-size:.9rem'>{txt}</p></div>", unsafe_allow_html=True)


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def trimestres(t):
    """Últimos balances trimestrales de Yahoo (solo para mirar): ventas, resultado bruto, operativo y neto, caja libre."""
    tk = yf.Ticker(t)
    inc = tk.quarterly_income_stmt
    if inc is None or inc.empty:
        return None
    try:
        cf = tk.quarterly_cashflow
    except Exception:       # noqa: BLE001
        cf = None

    def fila(df, *nombres):
        if df is None or df.empty:
            return None
        for n in nombres:
            if n in df.index:
                return pd.to_numeric(df.loc[n], errors="coerce")
        return None
    out = pd.DataFrame({"Ventas": fila(inc, "Total Revenue", "Operating Revenue"),
                        "Resultado bruto": fila(inc, "Gross Profit"),
                        "Resultado operativo": fila(inc, "Operating Income", "EBIT"),
                        "Ganancia neta": fila(inc, "Net Income", "Net Income Common Stockholders")})
    fcf = fila(cf, "Free Cash Flow")
    if fcf is not None:
        out["Caja libre"] = fcf
    out.index = pd.to_datetime(out.index)
    out = out.sort_index().dropna(subset=["Ventas"])
    return out.tail(8) if len(out) else None


def seccion_trimestres(t, e):
    """Ficha: cómo viene la empresa en los últimos trimestres, comparado con su último balance anual. No interviene en la
    estrategia (que usa solo balances anuales)."""
    st.subheader("Últimos trimestres", divider="gray")
    try:
        q = trimestres(t)
    except Exception:       # noqa: BLE001
        q = None
    if q is None or len(q) < 4:
        st.caption("Yahoo no tiene los balances trimestrales de esta empresa por ahora.")
        return
    ult4, ant4 = q.tail(4), q.iloc[-8:-4] if len(q) >= 8 else None
    v = ult4["Ventas"].sum()
    filas = [("Ventas últimos 12 meses", f"USD {v / 1e9:,.1f} mil M".replace(",", "X").replace(".", ",").replace("X", "."))]
    if ant4 is not None and ant4["Ventas"].sum() > 0:
        filas.append(("Crecimiento contra los 12 meses anteriores", pct((v / ant4["Ventas"].sum() - 1) * 100, 1)))
    if ult4["Ventas"].iloc[-1] and len(q) >= 5 and q["Ventas"].iloc[-5] > 0:
        filas.append(("Último trimestre contra el mismo del año anterior", pct((q["Ventas"].iloc[-1] / q["Ventas"].iloc[-5] - 1) * 100, 1)))
    if ult4["Resultado bruto"].notna().all() and v:
        mb = ult4["Resultado bruto"].sum() / v
        ref = _f(e.get("mb_ult"))
        filas.append(("Margen bruto 12 meses", f"{mb * 100:.1f}%".replace(".", ",")
                      + (f" (anual: {ref * 100:.1f}%)".replace(".", ",") if ref is not None else "")))
    if ult4["Resultado operativo"].notna().all() and v:
        filas.append(("Margen operativo 12 meses", f"{ult4['Resultado operativo'].sum() / v * 100:.1f}%".replace(".", ",")))
    if ult4["Ganancia neta"].notna().all() and v:
        filas.append(("Margen neto 12 meses", f"{ult4['Ganancia neta'].sum() / v * 100:.1f}%".replace(".", ",")))
    if "Caja libre" in ult4 and ult4["Caja libre"].notna().all():
        filas.append(("Caja libre 12 meses", f"USD {ult4['Caja libre'].sum() / 1e9:,.2f} mil M".replace(",", "X").replace(".", ",").replace("X", ".")))
    izq, der = st.columns([1.4, 1])
    with izq:
        d = q[["Ventas", "Ganancia neta"]].copy() / 1e9
        d.index = [f"T{(i.month - 1) // 3 + 1} {i.year}" for i in d.index]
        d = d.reset_index(names="Trimestre").melt("Trimestre", var_name="Serie", value_name="USD mil M")
        orden = list(dict.fromkeys(d["Trimestre"]))
        ch = alt.Chart(d).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("Trimestre:N", sort=orden, title=None, axis=alt.Axis(labelAngle=0)), xOffset="Serie:N",
            y=alt.Y("USD mil M:Q", title="USD miles de millones", axis=alt.Axis(gridOpacity=0.25)),
            color=alt.Color("Serie:N", scale=alt.Scale(domain=["Ventas", "Ganancia neta"], range=[AZUL, VERDE]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["Trimestre:N", "Serie:N", alt.Tooltip("USD mil M:Q", format=",.2f")])
        st.altair_chart(ch.properties(height=250), width="stretch")
    with der:
        st.markdown("<div class='caja'>" + "".join(f"<div class='filtro'><span>{a}</span><span class='v'>{b}</span></div>"
                                                  for a, b in filas) + "</div>", unsafe_allow_html=True)
    st.caption("Datos trimestrales de Yahoo, solo para ver cómo viene la empresa desde su último balance anual. La estrategia de "
               "calidad usa únicamente los balances anuales de la SEC.")


def seccion_pesos(t, ratio_txt, cedear):
    """Ficha: el CEDEAR en pesos (precio teórico al CCL, CCL implícito y liquidez en BYMA)."""
    st.subheader("El CEDEAR en pesos", divider="gray")
    if not ratio_cedear(ratio_txt):
        st.caption("No tengo el ratio de este CEDEAR.")
        return
    try:
        d = cedear_en_pesos(t, ratio_txt, cedear)
    except Exception:       # noqa: BLE001
        st.caption("No se pudieron bajar las cotizaciones en este momento.")
        return
    if d["dif"] is not None:
        barato = d["dif"] < 0
        txt = f"{'Más barato' if barato else 'Más caro'} que el CCL: {pct(d['dif'], 1)}"
        st.markdown(chip(txt, "verde" if barato else ("naranja" if d["dif"] > 1 else "gris")), unsafe_allow_html=True)
    r = d["ratio"]
    rtxt = f"{r:.0f}" if r and r >= 1 else ratio_txt
    celdas = [("Precio en Nueva York", "USD " + (f"{d['usd']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if d["usd"] else "—"),
               f"cierre del {d['fecha_usd']}" if d["fecha_usd"] else ""),
              ("Ratio del CEDEAR", ratio_txt, f"{rtxt} CEDEARs = 1 acción" if r and r >= 1 else ""),
              ("Dólar CCL del día", ars(d["ccl"], 2), "dolarapi.com"),
              ("Precio teórico del CEDEAR", ars(d["teorico"], 2), f"precio NY × CCL ÷ {rtxt}"),
              ("Precio en BYMA", ars(d["ars"], 2), f"último operado ({d['fecha_ars']})" if d["fecha_ars"] else "sin precio en BYMA"),
              ("CCL implícito", ars(d["implicito"], 2), f"precio BYMA × {rtxt} ÷ precio NY"),
              ("Diferencia contra el CCL", pct(d["dif"], 1) if d["dif"] is not None else "—", "negativo = barato"),
              ("Operado en BYMA", ars(d["operado"]) + " por día" if d["operado"] is not None else "—",
               "liquidez baja" if d["liquidez_baja"] else ("promedio de 30 ruedas" if d["operado"] is not None else ""))]
    st.markdown("<div class='pesos'>" + "".join(f"<div><span>{a}</span><b class='num'>{b}</b><small>{c}</small></div>" for a, b, c in celdas)
                + "</div>", unsafe_allow_html=True)
    aviso("<b>Cómo leerlo:</b> si el CCL implícito del CEDEAR está por debajo del CCL del día, el CEDEAR está barato respecto de "
          "la acción en Nueva York; si está por encima, está caro. Diferencias de menos de 1% son normales (los horarios de cierre "
          "no coinciden del todo).", "azul")


def tabla_cartera_pesos(tickers):
    """Cartera en pesos: precio del CEDEAR en BYMA, CCL implícito y liquidez de cada posición."""
    uni = {r["ticker"]: r for r in (U.todas() if U else [])}
    filas = []
    for t in tickers:
        r = uni.get(t, {})
        if not ratio_cedear(r.get("ratio_cedear")):
            continue
        try:
            d = cedear_en_pesos(t, r["ratio_cedear"], r.get("cedear") or t)
        except Exception:   # noqa: BLE001
            continue
        filas.append({"Acción": t, "Empresa": C.nombre(t), "Ratio": r["ratio_cedear"], "CEDEAR en BYMA": ars(d["ars"], 2),
                      "CCL implícito": ars(d["implicito"], 2), "vs CCL del día": d["dif"],
                      "Liquidez BYMA": "baja" if d["liquidez_baja"] else ("ok" if d["liquidez_baja"] is not None else "")})
    if not filas:
        st.caption("Sin cotizaciones de BYMA por ahora.")
        return
    tabla(pd.DataFrame(filas), fmt={"vs CCL del día": "%+.1f%%"},
          estilos={"vs CCL del día": lambda v: css_color("verde") if v < 0 else (css_color("naranja") if v > 1 else ""),
                   "Liquidez BYMA": por_prefijo({"baja": "rojo", "ok": "verde"})})
    ccl = dolares().get("CCL")
    st.caption((f"CCL del día: {ars(ccl, 2)}. " if ccl else "") + "Verde = el CEDEAR está más barato que el CCL. Liquidez baja = menos de "
               f"USD {LIQUIDEZ_MIN_USD:,.0f} operados por día en BYMA.".replace(",", "."))


def pagina_explorador():
    sel = st.query_params.get("empresa")
    if sel:
        if st.button("← Volver al explorador", type="tertiary"):
            del st.query_params["empresa"]
            st.rerun()
        ficha_empresa(sel)
        return
    encabezado("TODAS LAS EMPRESAS CON CEDEAR", "Explorador")
    df, info = datos_explorador(_marca_archivos("universo.csv", "explorador_calidad.json", "panel_momentum.json",
                                                "panel_screener.json", "cartera_calidad.json"))
    partes = [f"{len(df)} empresas"]
    if info["n_pasan"]:
        partes.append(f"{info['n_pasan']} pasan los filtros de calidad")
    st.caption(" · ".join(partes) + (f" · calidad al {pd.Timestamp(info['fecha_cal']).strftime('%d/%m/%Y')}" if info["fecha_cal"] else
                                      " · las métricas de calidad aparecen después de la primera corrida del explorador"))
    c1, c2, c3 = st.columns([1.8, 1.8, 3.4])
    buscar = c1.text_input("Buscar", placeholder="Empresa o ticker", label_visibility="collapsed")
    sectores = c2.multiselect("Sector", sorted(x for x in df["Sector"].dropna().unique() if x), placeholder="Todos los sectores",
                              label_visibility="collapsed")
    filtro = c3.segmented_control("Filtro", ["Todas", "Pasan calidad", "En cartera", "Reversión"], default="Todas",
                                  label_visibility="collapsed") or "Todas"
    f = df
    if buscar:
        q = buscar.strip().lower()
        f = f[f["Ticker"].str.lower().str.contains(q, regex=False) | f["Empresa"].str.lower().str.contains(q, regex=False)
              | f["CEDEAR"].str.lower().str.contains(q, regex=False)]
    if sectores:
        f = f[f["Sector"].isin(sectores)]
    f = {"Pasan calidad": f[f["_pasa"]], "En cartera": f[f["_en"]], "Reversión": f[f["_scr"]]}.get(filtro, f)
    numericas = ["Calidad", "Puesto calidad", "ROIC/ROE", "Ventas/año", "Deuda/EBITDA", "Rend. 10 años", "Puesto momentum",
                 "Caída desde máx.", "Volumen (USD M)"]
    f = f.copy()
    for c in numericas:
        f[c] = pd.to_numeric(f[c], errors="coerce")
    # orden elegido por el usuario (las que no tienen el dato van al final)
    criterios = {"Calidad": ("Calidad", False), "ROIC": ("ROIC/ROE", False), "Ventas": ("Ventas/año", False),
                 "Rend. 10 años": ("Rend. 10 años", False), "Momentum": ("Puesto momentum", True),
                 "Caída desde máximo": ("Caída desde máx.", False), "Volumen": ("Volumen (USD M)", False), "Nombre": ("Empresa", True)}
    o1, o2 = st.columns([3, 4])
    criterio = o1.selectbox("Ordenar por", list(criterios), key="exp_orden")
    extras = {"CEDEAR": "CEDEAR", "Deuda/EBITDA": "Deuda", "Caída desde máx.": "Caída", "Volumen (USD M)": "Volumen"}
    mas = o2.multiselect("Más columnas", list(extras), format_func=lambda c: extras[c], placeholder="Más columnas: CEDEAR, deuda, caída, volumen",
                         key="exp_mas")
    col, asc = criterios[criterio]
    f = f.sort_values([col, "Volumen (USD M)"], ascending=[asc, False], na_position="last")
    st.markdown(tabla_explorador(f, mas), unsafe_allow_html=True)
    st.caption("Tocá el nombre de una empresa para abrir su ficha. Las celdas vacías son datos que esa empresa no tiene "
               "(por ejemplo, las que no presentan balances en la SEC no tienen métricas de calidad).")


ESTADO_CHIP = {"Cartera calidad": "azul", "Cartera momentum": "violeta", "Señal reversión": "verde", "Comprable (calidad)": "verde",
               "Pasa filtros de calidad": "gris"}


def tabla_explorador(f, extras):
    """Lista del explorador en HTML: sin desplazamiento lateral, con logo y enlace a la ficha de cada empresa."""
    def n(v, fmt):
        return "" if pd.isna(v) else (fmt % v).replace(".", ",")
    cols = [("Empresa", ""), ("Sector", "")]
    if "CEDEAR" in extras:
        cols.append(("CEDEAR", ""))
    cols += [("Calidad", ""), ("ROIC", "n"), ("Ventas", "n"), ("Rend. 10a", "n"), ("Momentum", "n")]
    cols += [(lab, "n") for c, lab in (("Deuda/EBITDA", "Deuda"), ("Caída desde máx.", "Caída"), ("Volumen (USD M)", "Volumen"))
             if c in extras]
    cols.append(("Estado", ""))
    cab = "".join(f"<th class='{k}'>{c}</th>" for c, k in cols)
    filas = []
    for _, r in f.iterrows():
        t = r["Ticker"]
        ced = f" · CEDEAR {html.escape(str(r['CEDEAR']))}" if str(r["CEDEAR"]) != t else ""
        celdas = [f"<td><a class='emp' href='?empresa={html.escape(t)}' target='_self'>{logo_html(t, 30)}"
                  f"<span><b>{html.escape(str(r['Empresa']))}</b><small>{html.escape(t)}{ced}</small></span></a></td>",
                  f"<td class='sec'>{html.escape(str(r['Sector'] or ''))}</td>"]
        if "CEDEAR" in extras:
            celdas.append(f"<td>{html.escape(str(r['CEDEAR']))}</td>")
        cal = r["Calidad"]
        celdas.append("<td></td>" if pd.isna(cal) else
                      f"<td><span class='barra'><span><i style='width:{max(0, min(100, cal)):.0f}%'></i></span><b class='num'>{cal:.0f}</b></span></td>")
        rend = r["Rend. 10 años"]
        color_r = "" if pd.isna(rend) else f" style='color:{T_ROJO if rend < 5 else T_VERDE if rend >= 10 else T_AMARILLO};font-weight:600'"
        celdas += [f"<td class='n'>{n(r['ROIC/ROE'], '%.0f%%')}</td>", f"<td class='n'>{n(r['Ventas/año'], '%.0f%%')}</td>",
                   f"<td class='n'{color_r}>{n(rend, '%.1f%%')}</td>", f"<td class='n'>{n(r['Puesto momentum'], '%d')}</td>"]
        if "Deuda/EBITDA" in extras:
            d = r["Deuda/EBITDA"]
            celdas.append(f"<td class='n'>{'' if pd.isna(d) else 'caja neta' if d <= 0 else n(d, '%.1fx')}</td>")
        if "Caída desde máx." in extras:
            celdas.append(f"<td class='n'>{n(r['Caída desde máx.'], '%.0f%%')}</td>")
        if "Volumen (USD M)" in extras:
            celdas.append(f"<td class='n'>{n(r['Volumen (USD M)'], 'USD %.0f M')}</td>")
        est = [e for e in str(r["Estado"]).split(" · ") if e and e != "—"]
        celdas.append("<td>" + "".join(chip(html.escape(e), ESTADO_CHIP.get(e, "gris")) for e in est) + "</td>")
        filas.append("<tr>" + "".join(celdas) + "</tr>")
    return (f"<div class='tbl-wrap' style='max-height:720px'><table class='tbl exp'><thead><tr>{cab}</tr></thead>"
            f"<tbody>{''.join(filas)}</tbody></table></div>").replace("$", "&#36;")


# ============================================================================ datos en vivo: TradingView, dólar, BYMA, balances
import streamlit.components.v1 as _componentes   # noqa: E402


def widget_tradingview(script, config, alto):
    """Widget gratuito de TradingView (lleva su logo y enlace, como piden sus condiciones). Alto fijo en píxeles: dentro
    del cuadro de Streamlit los altos en % no funcionan. Toma el modo claro u oscuro de la app y se recarga si cambia."""
    h = alto - 26
    cfg = {**config, "isTransparent": True, "locale": "es"}
    if script != "embed-widget-ticker-tape.js":
        cfg.update(width="100%", height=h)
        cfg.pop("autosize", None)
    _componentes.html(
        "<style>html,body{margin:0;padding:0;background:transparent}a{color:#98A2B3}</style>"
        f"<div id='tv' class='tradingview-widget-container' style='height:{h}px;width:100%'>"
        f"<div class='tradingview-widget-container__widget' style='height:{h}px;width:100%'></div></div>"
        "<div style='font:11px Inter,sans-serif;color:#98A2B3;text-align:right;padding-top:6px'>"
        "<a href='https://es.tradingview.com/' rel='noopener nofollow' target='_blank'>Datos de TradingView</a></div>"
        "<script>(function(){var b=window.parent.document.body,osc=b.classList.contains('tema-oscuro');"
        f"var c={json.dumps(cfg)};c.colorTheme=osc?'dark':'light';"
        f"var s=document.createElement('script');s.src='https://s3.tradingview.com/external-embedding/{script}';s.async=true;"
        "s.text=JSON.stringify(c);document.getElementById('tv').appendChild(s);"
        "new MutationObserver(function(){if(b.classList.contains('tema-oscuro')!==osc){location.reload();}})"
        ".observe(b,{attributes:true,attributeFilter:['class']});})();</script>",
        height=alto)


def detectar_tema():
    """Marca el documento con la clase tema-oscuro cuando el tema de Streamlit es oscuro (la usan los estilos propios y los
    widgets). Se instala una sola vez en la página y sigue los cambios del menú ⋮ → Settings."""
    _componentes.html(
        "<script>(function(){var d=window.parent.document;if(d.getElementById('detector-tema'))return;"
        "var s=d.createElement('script');s.id='detector-tema';s.text=\"(function(){function f(){var a=document.querySelector('.stApp');"
        "if(!a)return;var m=getComputedStyle(a).color.match(/[0-9.]+/g);if(!m)return;"
        "var l=0.3*m[0]+0.59*m[1]+0.11*m[2];document.body.classList.toggle('tema-oscuro',l>140);}f();setInterval(f,400);})();\";"
        "d.head.appendChild(s);})();</script>", height=0)


TRADUCCION_EVENTOS = {
    "Non-Farm Employment Change": "Empleo (nóminas no agrícolas)", "Unemployment Rate": "Desempleo",
    "Average Hourly Earnings m/m": "Salarios por hora", "CPI m/m": "Inflación (CPI)", "CPI y/y": "Inflación anual (CPI)",
    "Core CPI m/m": "Inflación núcleo (CPI)", "PPI m/m": "Inflación mayorista (PPI)", "Core PPI m/m": "Inflación mayorista núcleo",
    "Core PCE Price Index m/m": "Inflación PCE núcleo", "Federal Funds Rate": "Tasa de la Fed", "FOMC Statement": "Comunicado de la Fed",
    "FOMC Press Conference": "Conferencia de la Fed", "FOMC Meeting Minutes": "Minutas de la Fed", "Fed Chair Powell Speaks": "Habla el presidente de la Fed",
    "ISM Manufacturing PMI": "ISM industrial", "ISM Services PMI": "ISM de servicios", "Retail Sales m/m": "Ventas minoristas",
    "Core Retail Sales m/m": "Ventas minoristas núcleo", "Advance GDP q/q": "PIB (preliminar)", "Prelim GDP q/q": "PIB (segunda estimación)",
    "Final GDP q/q": "PIB (final)", "JOLTS Job Openings": "Vacantes laborales (JOLTS)", "ADP Non-Farm Employment Change": "Empleo privado (ADP)",
    "Unemployment Claims": "Pedidos de subsidio por desempleo", "Prelim UoM Consumer Sentiment": "Confianza del consumidor (Michigan)",
    "CB Consumer Confidence": "Confianza del consumidor", "Empire State Manufacturing Index": "Industria de Nueva York",
    "Philly Fed Manufacturing Index": "Industria de Filadelfia"}


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def agenda_semana():
    """Datos de impacto alto de EE.UU. que faltan esta semana (calendario público de ForexFactory). [] si no responde."""
    import requests
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10,
                         headers={"User-Agent": "Mozilla/5.0 (Streamlimits)"})
        datos = r.json() if r.ok else []
    except Exception:       # noqa: BLE001
        return []
    ahora = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires")
    out, vistos = [], set()
    for e in datos if isinstance(datos, list) else []:
        if e.get("country") != "USD" or e.get("impact") != "High":
            continue
        try:
            f = pd.Timestamp(e["date"]).tz_convert("America/Argentina/Buenos_Aires")
        except Exception:   # noqa: BLE001
            continue
        if f < ahora - pd.Timedelta(hours=1):
            continue
        nombre = TRADUCCION_EVENTOS.get(e.get("title", ""), e.get("title", ""))
        if (nombre, f.date()) in vistos:
            continue
        vistos.add((nombre, f.date()))
        out.append((f, nombre))
    return sorted(out)[:6]


CINTA_TV = [{"proName": "FOREXCOM:SPXUSD", "title": "S&P 500"}, {"proName": "FOREXCOM:NSXUSD", "title": "Nasdaq 100"},
            {"proName": "FOREXCOM:DJI", "title": "Dow Jones"}, {"proName": "BCBA:IMV", "title": "Merval"},
            {"proName": "OANDA:XAUUSD", "title": "Oro"}, {"proName": "TVC:USOIL", "title": "Petróleo"},
            {"proName": "BITSTAMP:BTCUSD", "title": "Bitcoin"}]


@st.cache_data(ttl=600, show_spinner=False)
def dolares():
    """Cotizaciones del dólar en Argentina (dolarapi.com, gratis). {nombre: venta}."""
    import requests
    out = {}
    for clave, nombre in (("contadoconliqui", "CCL"), ("bolsa", "MEP"), ("oficial", "Oficial")):
        try:
            r = requests.get(f"https://dolarapi.com/v1/dolares/{clave}", timeout=10)
            if r.ok:
                out[nombre] = float(r.json().get("venta"))
        except Exception:       # noqa: BLE001
            pass
    return out


def ratio_cedear(texto):
    """'15:1' -> 15 CEDEARs por acción; '1:3' -> 1/3."""
    try:
        a, b = str(texto).split(":")
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def cotizacion_cedear(ticker, cedear, cierre=None):
    """Último precio en NY (USD), último precio del CEDEAR en BYMA (ARS) y monto operado por día en BYMA (ARS, 30 ruedas)."""
    out = {}
    try:
        h = yf.Ticker(ticker).history(period="10d", auto_adjust=False)
        if len(h):
            out["usd"] = float(h["Close"].dropna().iloc[-1])
            out["fecha_usd"] = h.index[-1].strftime("%d/%m")
    except Exception:       # noqa: BLE001
        pass
    for sim in dict.fromkeys((f"{cedear}.BA", f"{cedear.replace('.', '-')}.BA", f"{cedear.replace('.', '')}.BA")):
        try:
            h = yf.Ticker(sim).history(period="3mo", auto_adjust=False)
        except Exception:   # noqa: BLE001
            continue
        h = h.dropna(subset=["Close"])
        if len(h):
            out["ars"] = float(h["Close"].iloc[-1])
            out["fecha_ars"] = h.index[-1].strftime("%d/%m")
            out["operado_ars"] = float((h["Close"] * h["Volume"]).tail(30).mean())
            break
    return out


LIQUIDEZ_MIN_USD = 50_000      # menos de esto por día en BYMA (al CCL) = liquidez baja


def cedear_en_pesos(t, ratio_txt, cedear):
    """Precio teórico, CCL implícito y liquidez en BYMA de un CEDEAR."""
    q = cotizacion_cedear(t, cedear, ultimo_cierre())
    ccl = dolares().get("CCL")
    r = ratio_cedear(ratio_txt)
    d = {"usd": q.get("usd"), "ars": q.get("ars"), "ccl": ccl, "ratio": r, "operado": q.get("operado_ars"),
         "fecha_usd": q.get("fecha_usd"), "fecha_ars": q.get("fecha_ars")}
    d["teorico"] = q["usd"] * ccl / r if q.get("usd") and ccl and r else None
    d["implicito"] = q["ars"] * r / q["usd"] if q.get("usd") and q.get("ars") and r else None
    d["dif"] = (d["implicito"] / ccl - 1) * 100 if d["implicito"] and ccl else None
    d["liquidez_baja"] = (d["operado"] / ccl < LIQUIDEZ_MIN_USD) if d["operado"] is not None and ccl else None
    return d


def ars(v, dec=0):
    return "—" if v is None else "$ " + f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fecha_balance(t, dia):
    """Próximo balance de una empresa según Yahoo (calendario y, si no, la lista de fechas de resultados). None si no hay."""
    hoy = pd.Timestamp(dia)

    def sin_zona(f):
        f = pd.Timestamp(f)
        return f.tz_localize(None) if f.tzinfo is not None else f
    fechas = []
    try:
        cal = yf.Ticker(t).calendar
        if isinstance(cal, dict):
            fechas += [sin_zona(f) for f in (cal.get("Earnings Date") or []) if f is not None]
        elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
            fechas += [sin_zona(f) for f in cal.loc["Earnings Date"].dropna()]
    except Exception:       # noqa: BLE001
        pass
    if not any(f >= hoy for f in fechas):
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=8)
            if ed is not None and len(ed):
                fechas += [sin_zona(f) for f in ed.index]
        except Exception:   # noqa: BLE001
            pass
    fut = sorted(f for f in fechas if f >= hoy)
    return fut[0].strftime("%Y-%m-%d") if fut else None


def proximos_balances(tickers):
    """{ticker: fecha del próximo balance} de las empresas en cartera."""
    from concurrent.futures import ThreadPoolExecutor
    dia = date.today().isoformat()
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = dict(zip(tickers, ex.map(lambda t: fecha_balance(t, dia), tickers)))
    return {t: f for t, f in res.items() if f}


@st.cache_data(ttl=300, show_spinner=False)
def variaciones_dia(tickers, _marca=None):
    """Precio y variación del día de cada acción (Yahoo). Se renueva cada 5 minutos."""
    datos = yf.download(list(tickers), period="5d", interval="1d", auto_adjust=False, group_by="ticker", threads=True,
                        progress=False)
    out = {}
    for t in tickers:
        try:
            c = datos[t]["Close"].dropna()
        except (KeyError, TypeError):
            continue
        if len(c) >= 2:
            out[t] = (float(c.iloc[-1]), (float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100, c.index[-1].strftime("%d/%m"))
    return out


def mapa_cedears(en_cartera):
    """Mapa de calor propio: las acciones con CEDEAR por sector, del tamaño de su valor de mercado y del color de su
    variación del día (precios de Yahoo, cada 5 minutos)."""
    import plotly.express as px
    c1, c2 = st.columns([2, 1.4])
    c1.markdown("<div class='tit-sec'>Mapa de los CEDEARs hoy</div>", unsafe_allow_html=True)
    vista = c2.segmented_control("Mapa", ["Todas", "Mis carteras"], default="Todas", key="mapa_vista",
                                 label_visibility="collapsed") or "Todas"
    uni = [r for r in (U.todas() if U else []) if r.get("incluida") == "1"]
    if vista == "Mis carteras":
        uni = [r for r in uni if r["ticker"] in en_cartera]
    if not uni:
        st.caption("Sin acciones para mostrar.")
        return
    try:
        var = variaciones_dia(tuple(sorted(r["ticker"] for r in uni)), pd.Timestamp.now().floor("5min").isoformat())
    except Exception:       # noqa: BLE001
        st.caption("No se pudieron bajar los precios en este momento.")
        return
    filas = []
    for r in uni:
        t = r["ticker"]
        if t not in var:
            continue
        tam = pd.to_numeric(r.get("valor_mercado"), errors="coerce")
        if pd.isna(tam) or tam <= 0:
            tam = pd.to_numeric(r.get("volumen_usd"), errors="coerce") * 250     # sin dato: aproximado por el volumen
        if pd.isna(tam) or tam <= 0:
            continue
        precio, v, fecha = var[t]
        filas.append({"Sector": r.get("sector") or "Otros", "Ticker": t, "Empresa": C.nombre(t) if t in C.CEDEARS else r.get("nombre") or t,
                      "Tamaño": float(tam), "Var": max(-3.0, min(3.0, v)), "VarReal": v, "Precio": precio,
                      "Etiqueta": f"{v:+.2f}%".replace(".", ","), "PrecioTxt": f"{precio:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")})
    if not filas:
        st.caption("Sin precios para mostrar.")
        return
    df = pd.DataFrame(filas)
    fig = px.treemap(df, path=[px.Constant("Acciones con CEDEAR"), "Sector", "Ticker"], values="Tamaño", color="Var",
                     color_continuous_scale=[(0, "#D92D20"), (0.4, "#F97066"), (0.5, "#98A2B3"), (0.6, "#32D583"), (1, "#067647")],
                     range_color=(-3, 3), custom_data=["Empresa", "Etiqueta", "PrecioTxt"])
    fig.update_traces(texttemplate="<b>%{label}</b><br>%{customdata[1]}", textposition="middle center",
                      hovertemplate="<b>%{label}</b> · %{customdata[0]}<br>%{customdata[1]} hoy · USD %{customdata[2]}<extra></extra>",
                      marker=dict(line=dict(width=1, color="rgba(0,0,0,0.15)")), root_color="rgba(0,0,0,0)", tiling=dict(pad=2))
    fig.update_layout(height=560, margin=dict(t=10, l=0, r=0, b=0), coloraxis_showscale=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter, sans-serif", color="#FFFFFF"))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    fechas = sorted({x[2] for x in var.values()})
    st.caption(f"Tamaño: valor de mercado · color: variación del día (rojo baja, verde sube, hasta ±3%) · precios de Yahoo "
               f"al {fechas[-1] if fechas else ''}, se actualizan cada 5 minutos. Tocá un sector para agrandarlo.")


# ============================================================================ página: inicio
def _tarjeta_cartera(titulo, etiqueta, color_et, valor, filas, tickers, pie, href):
    datos = "".join(f"<div><span>{a}</span><b{(' style=' + chr(39) + 'color:' + c + chr(39)) if c else ''}>{b}</b></div>"
                    for a, b, c in filas)
    logos = "".join(logo_html(t, 28) for t in tickers)
    txt, fondo = _FONDO[color_et]
    return (f"<a class='cartera' href='{href}' target='_self'><div class='cab'><span>{titulo}</span>"
            f"<span class='chip' style='background:{fondo};color:{txt}'>{etiqueta}</span></div>"
            f"<div class='valor num'>{valor}</div><div class='datos'>{datos}</div>"
            f"<div class='logos'>{logos}</div><div class='pie'>{pie}</div></a>")


def _color_ret(v):
    return None if v is None or pd.isna(v) else (T_VERDE if v > 0.05 else T_ROJO if v < -0.05 else None)


def pagina_inicio():
    widget_tradingview("embed-widget-ticker-tape.js", {"symbols": CINTA_TV, "showSymbolLogo": True, "displayMode": "adaptive"}, 76)
    hoy = date.today()
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    encabezado(f"{dias[hoy.weekday()]} {fmt_fecha(hoy)}", "Inicio")

    # --- cartera de calidad, valuada al último cierre (igual que su página)
    E0 = leer_json("cartera_calidad.json") or C.estado_nuevo()
    panel_c = leer_json("panel_calidad.json") or {}
    real = not str(E0.get("origen") or "").startswith("backtest") and bool(E0.get("posiciones"))
    pm = leer_json("panel_momentum.json") or {}
    ps = leer_json("panel_screener.json") or {}
    tick_cal = list(E0.get("posiciones", {})) if real else []
    tick_mom = [x["Acción"] for x in pm.get("cartera", [])]
    desde = min([pd.Timestamp(E0.get("inicio") or hoy), pd.Timestamp(pm.get("inicio") or hoy)]) - pd.Timedelta(days=10)
    try:
        with st.spinner("Actualizando precios..."):
            px = precios_ajustados(tuple(sorted(set(tick_cal))), desde.strftime("%Y-%m-%d"), ultimo_cierre())
    except Exception:       # noqa: BLE001
        px = None
    tarjetas = []
    if real and px is not None:
        E = C.actualizar_valores(E0, px)
        cap = E.get("capital", 10000)
        valor = E["caja"] + sum(p["valor"] for p in E["posiciones"].values())
        r_c, r_s = (valor / cap - 1) * 100, (E["spy_ref"] / cap - 1) * 100
        caja = E["caja"] / valor * 100 if valor else 0
        filas = [(f"Desde el {pd.Timestamp(E['inicio']).strftime('%d/%m')}", pct(r_c), _color_ret(r_c)),
                 ("S&amp;P mismo período", pct(r_s), None),
                 ("Posiciones", f"{len(E['posiciones'])}" + (f" + {caja:.0f}% en SPY" if caja > 1 else ""), None)]
        val_txt = usd(valor)
    else:
        filas, val_txt = [("Estado", "arranca en la próxima revisión", None)], "—"
    prox_c = proxima_revision_calidad(hoy, E0.get("ultima_oficial"))
    trim = prox_c is not None and prox_c.month in C.MESES_REVISION
    tarjetas.append(_tarjeta_cartera("Cartera de calidad", "Largo plazo", "azul", val_txt, filas, tick_cal,
                                     f"Próxima revisión: <b>{dias[prox_c.weekday()]} {prox_c.strftime('%d/%m')}</b>"
                                     + (" · trimestral" if trim else "") if prox_c else "", "calidad"))
    # --- momentum (panel semanal / mensual)
    prox_m = proxima_operacion_momentum(hoy)
    if pm:
        cap_m = float(os.environ.get("MOMENTUM_CAPITAL") or 10000)
        r_m = (pm["valor"] / cap_m - 1) * 100 if pm.get("valor") else None
        r_sm = None
        try:
            spy = precios_ajustados(tuple(), pd.Timestamp(pm["inicio"]).strftime("%Y-%m-%d"), ultimo_cierre())["SPY"].dropna()
            spy = spy[spy.index <= pd.Timestamp(pm["cierre"])]
            r_sm = (spy.iloc[-1] / spy.iloc[0] - 1) * 100
        except Exception:   # noqa: BLE001
            pass
        filas_m = [(f"Desde el {pd.Timestamp(pm['inicio']).strftime('%d/%m')}", pct(r_m), _color_ret(r_m)),
                   ("S&amp;P mismo período", pct(r_sm), None), ("Posiciones", str(len(tick_mom)), None)]
        val_m = usd(pm.get("valor")) + f"<small> al {pd.Timestamp(pm['cierre']).strftime('%d/%m')}</small>"
    else:
        filas_m, val_m = [("Estado", "sin datos todavía", None)], "—"
    tarjetas.append(_tarjeta_cartera("Momentum", "Mensual", "violeta", val_m, filas_m, tick_mom,
                                     f"Próxima operación: <b>{dias[prox_m.weekday()]} {prox_m.strftime('%d/%m')}</b>" if prox_m else "",
                                     "momentum"))
    # --- reversión (panel diario del screener)
    senales = [t for t, v in ps.get("filas", {}).items() if v.get("pasa")]
    abiertas = ps.get("abiertas", [])
    if ps:
        filas_r = [("Operaciones abiertas", str(len(abiertas)), None),
                   ("Mercado", "a favor" if ps.get("mercado_ok") else "en contra", T_VERDE if ps.get("mercado_ok") else T_ROJO)]
        val_r = f"{len(senales)} {'señal' if len(senales) == 1 else 'señales'} hoy"
    else:
        filas_r, val_r = [("Estado", "aparece después de la próxima corrida del screener", None)], "—"
    tarjetas.append(_tarjeta_cartera("Reversión", "Diaria", "verde", val_r, filas_r, senales[:10] or [a["Ticker"] for a in abiertas][:10],
                                     "El screener corre de lunes a viernes de madrugada", "reversion"))
    st.markdown("<div class='carteras'>" + "".join(tarjetas) + "</div>", unsafe_allow_html=True)

    # --- qué hacer
    tareas = []
    if prox_m:
        ords = pm.get("ordenes", [])
        if ords:
            det = "; ".join(f"{o['Orden'].lower()} {o['Acción']}" for o in ords)
            det = f"Con el ranking de hoy: {det}. El mail del día confirma las órdenes."
        else:
            det = "Con el ranking de hoy no habría que hacer nada."
        tareas.append((prox_m, "Momentum: operación del mes", det, "Momentum", "violeta"))
    if prox_c:
        libres = 10 - len(tick_cal)
        det = ("Revisión trimestral: puede rotar hasta 2 posiciones. " if trim else "Revisión mensual. ") + (
            f"Hay {libres} lugares libres para completar con las mejores del ranking." if libres > 0 and real else "")
        tareas.append((prox_c, "Calidad: " + ("revisión trimestral" if trim else "revisión del mes"), det.strip(), "Calidad", "azul"))
    if ps:
        vencen = [a for a in abiertas if (a.get("Ruedas restantes") or 99) <= 5]
        det = (f"Señal de compra: {', '.join(senales)}." if senales else "Hoy no hay señales de compra.") + (
            f" Vencen esta semana: {', '.join(a['Ticker'] for a in vencen)}." if vencen else "")
        tareas.append((hoy, "Reversión: señales del screener", det, "Reversión", "verde"))
    rev = [(t, x) for t, x in (panel_c.get("tesis") or {}).items() if x.get("estado") in ("REVISAR", "SIN DATOS")]
    tareas.append((None, "Tesis para revisar",
                   "; ".join(f"{t}: {', '.join(x['motivos'])}" for t, x in rev) if rev else
                   "Sin alertas en la última revisión (ninguna posición cae más de 25% contra el S&amp;P).", "Tesis", "gris"))
    filas_t = []
    for f_, tit, det, et, col in sorted(tareas, key=lambda x: (x[0] is None, x[0] or hoy)):
        urg = f_ is not None and (f_ - hoy).days <= 3
        fecha = "Hoy" if f_ == hoy else (f_.strftime("%d/%m") if f_ else "—")
        txt, fondo = _FONDO[col]
        filas_t.append(f"<div class='tarea'><span class='fecha{' urgente' if urg else ''}'>{fecha}</span><div><b>{tit}</b>"
                       f"<span>{det}</span></div><span class='chip' style='background:{fondo};color:{txt}'>{et}</span></div>")
    st.markdown("<div class='caja-inicio'><div class='tit'>Qué hacer</div>" + "".join(filas_t) + "</div>", unsafe_allow_html=True)

    # --- mercado
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("<div class='tit-sec'>S&amp;P 500</div>", unsafe_allow_html=True)
        widget_tradingview("embed-widget-symbol-overview.js", {
            "symbols": [["S&P 500", "FOREXCOM:SPXUSD|12M"], ["Nasdaq 100", "FOREXCOM:NSXUSD|12M"]], "chartOnly": False,
            "width": "100%", "height": "100%", "showVolume": False, "hideDateRanges": False, "scalePosition": "right",
            "lineColor": "#2459D6", "topColor": "rgba(36,89,214,0.18)", "bottomColor": "rgba(36,89,214,0)", "chartType": "area",
            "dateRanges": ["1d|1", "1m|30", "12m|1D", "60m|1W"]}, 400)
    with c2:
        st.markdown("<div class='tit-sec'>Dólar</div>", unsafe_allow_html=True)
        d = dolares()
        filas_d = [(n, ars(d.get(n), 2)) for n in ("CCL", "MEP", "Oficial")]
        if d.get("CCL") and d.get("Oficial"):
            filas_d.append(("Brecha CCL / oficial", pct((d["CCL"] / d["Oficial"] - 1) * 100, 1, False)))
        st.markdown("<div class='caja-inicio'>" + "".join(f"<div class='fila-d'><b>{a}</b><span class='num'>{b}</span></div>"
                                                          for a, b in filas_d)
                    + "<p>El CCL es el dólar de los CEDEARs · dolarapi.com</p></div>", unsafe_allow_html=True)
    c3, c4 = st.columns([2, 1])
    with c3:
        mapa_cedears(set(tick_cal) | set(tick_mom))
    with c4:
        st.markdown("<div class='tit-sec'>Próximos balances</div>", unsafe_allow_html=True)
        todos = tuple(sorted(set(tick_cal) | set(tick_mom)))
        bal = proximos_balances(todos) if todos else {}
        filas_b = sorted(bal.items(), key=lambda x: x[1])[:8]
        if filas_b:
            st.markdown("<div class='caja-inicio'>" + "".join(
                f"<div class='fila-d'><span class='tk'>{logo_html(t, 26)}{html.escape(C.nombre(t))}</span>"
                f"<span class='num'>{pd.Timestamp(f_).strftime('%d/%m')}</span></div>" for t, f_ in filas_b)
                + "<p>Después de cada balance, revisar la tesis.</p></div>", unsafe_allow_html=True)
        else:
            st.caption("Sin fechas de balances disponibles por ahora.")
    st.markdown("<div class='tit-sec'>Calendario económico</div>", unsafe_allow_html=True)
    dias_c = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    ag = agenda_semana()
    if ag:
        st.markdown("<div class='aviso aviso-azul'><b>Lo importante que falta esta semana:</b> " + " · ".join(
            f"{html.escape(n)} ({dias_c[f.weekday()]} {f.strftime('%d/%m')}, {f.strftime('%H:%M')})" for f, n in ag) + "</div>",
            unsafe_allow_html=True)
    st.caption("Agenda de los datos económicos que mueven al mercado, en hora de Argentina. Más barritas = más importante. "
               "A la derecha: valor real (aparece cuando se publica), pronóstico y dato anterior. Si el real sale muy distinto del "
               "pronóstico, el mercado suele moverse fuerte ese día.")
    widget_tradingview("embed-widget-events.js", {"importanceFilter": "0,1", "countryFilter": "us,ar", "width": "100%",
                                                  "height": "100%"}, 620)
    st.caption("Datos de mercado de TradingView y dolarapi.com, con demora. Análisis con fines educativos; no es recomendación de inversión.")



pg = st.navigation([st.Page(pagina_inicio, title="Inicio", icon=":material/home:", default=True),
                    st.Page(pagina_calidad, title="Cartera de calidad", icon=":material/account_balance:", url_path="calidad"),
                    st.Page(pagina_reversion, title="Reversión (screener)", icon=":material/autorenew:", url_path="reversion"),
                    st.Page(pagina_momentum, title="Momentum residual", icon=":material/trending_up:", url_path="momentum"),
                    st.Page(pagina_explorador, title="Explorador", icon=":material/travel_explore:", url_path="explorador")])
st.sidebar.markdown("<div class='marca'><svg width='28' height='28' viewBox='0 0 28 28' aria-hidden='true'><rect width='28' height='28' "
                    "rx='7' style='fill:var(--acento)'></rect><path d='M7 18l5-5 4 3 5-7' stroke='#FFFFFF' stroke-width='2.2' fill='none' "
                    "stroke-linecap='round' stroke-linejoin='round'></path></svg>Streamlimits</div>", unsafe_allow_html=True)
st.sidebar.caption("Estrategias con CEDEARs · datos con fines educativos, no es recomendación de inversión.")
st.sidebar.caption("Modo claro u oscuro: menú ⋮ (arriba a la derecha) → Settings.")
with st.sidebar:
    detectar_tema()
pg.run()
