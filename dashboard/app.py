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

INICIO_MOM_REAL = M.INICIO
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
</style>
""", unsafe_allow_html=True)


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


def grafico_pesos(pesos, objetivo, tope, etiqueta_tope):
    d = pesos.sort_values(ascending=False).reset_index()
    d.columns = ["Acción", "Peso"]
    barras = alt.Chart(d).mark_bar(color=AZUL, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=26).encode(
        x=alt.X("Acción:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Peso:Q", title="% de la cartera", scale=alt.Scale(domain=[0, max(tope + 3, float(d["Peso"].max()) + 3)]),
                axis=alt.Axis(gridOpacity=0.25)),
        tooltip=["Acción:N", alt.Tooltip("Peso:Q", format=".1f", title="% de la cartera")])
    reglas = alt.Chart(pd.DataFrame({"y": [objetivo, tope], "Línea": [f"objetivo {objetivo:.0f}%", etiqueta_tope]})).mark_rule(
        strokeDash=[4, 4], color="#777").encode(y="y:Q", tooltip=["Línea:N"])
    st.altair_chart((barras + reglas).properties(height=250), width="stretch")
    st.caption(f"Líneas punteadas: objetivo {objetivo:.0f}% por posición y {etiqueta_tope} (si lo supera, se recorta).")


# ============================================================================ tablas comunes
def tabla_anual(an, nombre_cartera):
    t = an.copy()
    t["Diferencia"] = t[nombre_cartera] - t["S&P 500"]
    t["¿Gana al S&P?"] = np.where(t["Diferencia"] > 0, "✓ sí", "✗ no")
    t.index.name = "Año"
    cfg = {k: st.column_config.NumberColumn(format="%+.1f%%") for k in t.columns if k != "¿Gana al S&P?"}
    st.dataframe(t.reset_index(), hide_index=True, width="stretch", height=36 * (len(t) + 1) + 3,
                 column_config={"Año": st.column_config.NumberColumn(format="%d"), **cfg})


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
    f["Resultado"] = txt_pct(pd.to_numeric(f["Resultado"], errors="coerce") * 100)
    st.caption(f"{len(f)} movimientos")
    st.dataframe(f[["Fecha", "Origen", "Orden", "Acción", "Empresa", "Peso", "Resultado", "Motivo"]], hide_index=True, width="stretch",
                 height=min(36 * (len(f) + 1) + 3, 560), column_config={
                     "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                     "Peso": st.column_config.NumberColumn("% de la cartera", format="%.1f%%"),
                     "Resultado": st.column_config.TextColumn("Resultado", help="Solo en ventas: ganancia o pérdida de la posición"),
                     "Motivo": st.column_config.TextColumn(width="large")})


def ventas_con_stats(v, nombre_fn, nota_motivo=None):
    """v: Acción, Compra, Venta, Resultado (0-1), Motivo, [Origen]."""
    if not len(v):
        st.info("Todavía no hubo ventas.")
        return
    v = v.copy()
    v["Compra"], v["Venta"] = pd.to_datetime(v["Compra"]), pd.to_datetime(v["Venta"])
    v["Años"] = (v["Venta"] - v["Compra"]).dt.days / 365.25
    v["Resultado"] = pd.to_numeric(v["Resultado"], errors="coerce") * 100
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Ventas", len(v))
    c2.metric("Con ganancia", pct((v["Resultado"] > 0).mean() * 100, 0, False))
    c3.metric("Resultado promedio", pct(v["Resultado"].mean(), 0))
    c4.metric("Mejor", f"{v.loc[v['Resultado'].idxmax(), 'Acción']} {pct(v['Resultado'].max(), 0)}")
    c5.metric("Peor", f"{v.loc[v['Resultado'].idxmin(), 'Acción']} {pct(v['Resultado'].min(), 0)}")
    v.insert(1, "Empresa", [nombre_fn(t) for t in v["Acción"]])
    v = v.sort_values("Venta", ascending=False)
    cols = ["Acción", "Empresa", "Compra", "Venta", "Años", "Resultado", "Motivo"] + (["Origen"] if "Origen" in v else [])
    st.dataframe(v[cols], hide_index=True, width="stretch", height=min(36 * (len(v) + 1) + 3, 520), column_config={
        "Compra": st.column_config.DateColumn(format="DD/MM/YYYY"), "Venta": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Años": st.column_config.NumberColumn(format="%.1f"), "Resultado": st.column_config.NumberColumn(format="%+.0f%%"),
        "Motivo": st.column_config.TextColumn(nota_motivo or "Motivo", width="large")})


# ============================================================================ datos
@st.cache_data(ttl=3600, show_spinner=False)
def precios_ajustados(tickers, desde):
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


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def datos_momentum(inicio_real):
    M.INICIO = INICIO_BACKTEST_MOM
    try:
        px, vo = M.descargar()
        motor = M.Motor(px, vo)
        bt = M.simular(motor)
    finally:
        M.INICIO = inicio_real
    real = M.simular(motor)
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
| **Vender** | Se rompe la tesis | Deja de cumplir un filtro mínimo: se vende entera |
| **Rotar** | Feb, may, ago y nov | Si cayó del puesto 20, se cambia por la mejor del ranking (máx. 2) |
| **Recortar** | Creció demasiado o está carísima | Más de 25% baja a 20%; precio extremo y más de 12,5% baja a 10% |
| **Sumar** | Sobra plata | Completa hacia el 10% las posiciones por debajo de 8,5% |
| **Nunca** | Por una caída de precio | Si cae más de 25% contra el S&P, lo revisa el equipo |

Quedan afuera las extranjeras que no presentan balances con normas de EE.UU. y seis empresas con datos poco confiables (Ford, GM, JD,
Alibaba, Baidu y NIO). Costos: 0,5% por operación. Análisis cuantitativo con fines educativos; no es una recomendación de inversión.
"""


def pagina_calidad():
    st.title("Cartera de calidad")
    st.caption("10 empresas de calidad para el largo plazo · revisión mensual el primer día hábil desde el 15 · mismo programa y datos "
               "que el backtest 2011-2026")
    E0 = leer_json("cartera_calidad.json")
    if not E0:
        st.error("No encuentro cartera_calidad.json en el repositorio.")
        return
    panel, H = leer_json("panel_calidad.json"), leer_json("historial_calidad.json")
    P = E0["posiciones"]
    entradas = [p["fecha_entrada"] for p in P.values()] + [E0["ultima_fecha"]]
    desde = (min(pd.Timestamp(d) for d in entradas) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    with st.spinner("Actualizando precios..."):
        px = precios_ajustados(tuple(sorted(P)), desde)
    E = C.actualizar_valores(E0, px)
    valor = E["caja"] + sum(p["valor"] for p in E["posiciones"].values())
    cap = E.get("capital", 10000)
    ult = pd.Timestamp(px.index[-1])
    hoy = date.today()
    prox = proxima_revision_calidad(hoy, E0.get("ultima_oficial"))
    tesis = (panel or {}).get("tesis", {})
    rank = pd.DataFrame((panel or {}).get("ranking", []))
    castigadas = set(rank.loc[rank["castigada"], "Acción"]) if len(rank) else set()
    pesos_vivos = {t: p["valor"] / valor * 100 for t, p in E["posiciones"].items()}

    # serie combinada: backtest + sistema real (escalado para que sea continua)
    evo_real = pd.DataFrame(E0.get("evolucion", []), columns=["fecha", "cartera", "spy"])
    evo_real = pd.concat([evo_real, pd.DataFrame([{"fecha": ult.strftime("%Y-%m-%d"), "cartera": valor, "spy": E["spy_ref"]}])])
    evo_real = evo_real.drop_duplicates("fecha", keep="last")
    evo_real.index = pd.to_datetime(evo_real.pop("fecha"))
    evo_real = evo_real.sort_index()
    comb = None
    if H:
        hb = pd.DataFrame(H["evolucion"])
        hb.index = pd.to_datetime(hb.pop("fecha"))
        f_c, f_s = hb["cartera"].iloc[-1] / cap, hb["spy"].iloc[-1] / cap
        cont = evo_real[evo_real.index > hb.index[-1]]
        comb = pd.DataFrame({"Cartera de calidad": pd.concat([hb["cartera"], cont["cartera"] * f_c]),
                             "S&P 500": pd.concat([hb["spy"], cont["spy"] * f_s]), "Promedio de la lista": hb["lista"]})

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cartera del sistema", usd(valor), help=f"Cartera de referencia que arrancó con {usd(cap)} el {fmt_fecha(E['inicio'])}")
    c2.metric("Desde el inicio real", pct((valor / cap - 1) * 100), help=f"Desde el {fmt_fecha(E['inicio'])}")
    c3.metric("S&P 500 mismo período", pct((E["spy_ref"] / cap - 1) * 100))
    if comb is not None:
        c4.metric("Anual desde 2011", pct(stats_serie(comb["Cartera de calidad"]).get("anual"), 1, False),
                  help="Backtest desde 2011 + sistema real, mismas reglas")
    c5.metric("Próxima revisión", prox.strftime("%d/%m/%Y") if prox else "—", help="Primer día hábil desde el 15, a la noche")
    st.caption(f"Precios al cierre del {ult.strftime('%d/%m/%Y')}. El sistema real continúa el backtest desde el "
               f"{pd.Timestamp(E['inicio']).strftime('%d/%m/%Y')}, con las mismas reglas, datos y fechas de compra.")

    tabs = st.tabs(["Resumen", "Cartera", "Evolución", "Operaciones", "Ranking", "Cómo funciona"])
    with tabs[0]:
        corr = (panel or {}).get("correccion")
        if corr is not None and corr <= -0.10:
            aviso(f"<b>Mercado en corrección:</b> el S&amp;P está {pct(-corr * 100, 0, False)} debajo de su máximo del último año. "
                  "Momento de comprar, no de vender: los aportes van a las posiciones por debajo del 10%.", "rojo")
        st.subheader("1. Qué hacer")
        if panel:
            oficial = panel["modo"] == "OFICIAL"
            st.markdown(f"Última revisión: **{fmt_fecha(panel['fecha'])}** · " + ("oficial" if oficial else "consulta (no registrada)")
                        + (" · revisión trimestral" if panel.get("revision_trimestral") else ""))
            if not oficial:
                aviso("Fue una <b>consulta</b>: muestra qué haría el sistema, pero no quedó registrada.", "naranja")
            if panel["ordenes"]:
                o = pd.DataFrame(panel["ordenes"])
                o.insert(2, "Empresa", [C.nombre(t) for t in o["Acción"]])
                o.insert(3, "CEDEAR", [C.cedear(t) for t in o["Acción"]])
                o["Peso"] = pd.to_numeric(o["Peso"], errors="coerce") * 100
                o["Resultado"] = txt_pct(pd.to_numeric(o["Resultado"], errors="coerce") * 100)
                st.dataframe(o, hide_index=True, width="stretch", column_config={
                    "Peso": st.column_config.NumberColumn("% de la cartera", format="%.1f%%"),
                    "Motivo": st.column_config.TextColumn(width="large")})
                st.caption("Primero las ventas, después las compras. Para cada cliente, usar el % de la cartera.")
            else:
                aviso("<b>Ese mes no hubo que hacer nada.</b> En una cartera de largo plazo, es lo normal.", "verde")
        else:
            aviso(f"La primera revisión del sistema real es el <b>{fmt_fecha(prox) if prox else '15 de octubre'}</b> a la noche. "
                  "Hasta entonces, la cartera es la que dejó el backtest.")
        st.subheader("2. Para revisar a mano")
        rev = [(t, x) for t, x in tesis.items() if x["estado"] in ("REVISAR", "SIN DATOS")]
        if rev:
            for t, x in rev:
                st.markdown(f"- **{t}** ({C.nombre(t)}): {'; '.join(x['motivos'])}. El sistema no vende por esto: lo decide el equipo.")
        else:
            st.markdown("Nada: ninguna tesis en duda y ninguna posición cae más de 25% contra el S&P.")
        st.subheader("3. Si entra plata (aportes o clientes nuevos)")
        faltan = sorted([(w, t) for t, w in pesos_vivos.items() if w < 9.7 and tesis.get(t, {}).get("estado", "INTACTA") == "INTACTA"
                         and t not in castigadas])
        if faltan:
            st.markdown("**Aportes**, en este orden hasta que se termine: " + " · ".join(
                f"**{t}** hasta {pct(10 - w, 1, False)} de la cartera" for w, t in faltan) + ". Si todas llegan al 10%, repartir el resto "
                "en partes iguales.")
        else:
            st.markdown("**Aportes:** todas están cerca del 10%: repartir en partes iguales.")
        st.markdown("**Clientes nuevos:** entrar en 3 tramos (un tercio ahora, otro en un mes y el último al mes siguiente, o antes si el "
                    "mercado cae 10%), comprando la cartera en los pesos de la pestaña Cartera.")
        st.subheader("4. Alertas")
        alertas = []
        for t, w in pesos_vivos.items():
            if w > 20:
                alertas.append(f"**{t}** pesa {pct(w, 1, False)}: si pasa del 25% se recorta a 20%.")
        sect = pd.Series([C.grupo(t) for t in E["posiciones"]]).value_counts()
        for s_, n_ in sect[sect >= 3].items():
            alertas.append(f"Hay {n_} empresas de **{s_.lower()}**: es el máximo por sector.")
        if E["caja"] / valor > 0.03:
            alertas.append(f"Hay {pct(E['caja'] / valor * 100, 1, False)} de liquidez estacionada en SPY esperando la próxima compra.")
        st.markdown("\n".join(f"- {a}" for a in alertas) if alertas else "Sin alertas.")

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
        st.dataframe(cart, hide_index=True, width="stretch", column_config={
            "Peso %": st.column_config.NumberColumn(format="%.1f%%"),
            "Suba desde la compra %": st.column_config.NumberColumn(format="%+.0f%%", help="Suba de la acción (con dividendos) desde que entró"),
            "vs S&P desde la compra %": st.column_config.NumberColumn(format="%+.0f%%", help="Cuánto más (o menos) que el S&P en el mismo período"),
            "En cartera desde": st.column_config.DateColumn(format="DD/MM/YYYY")})
        pesos = cart.set_index("Acción")["Peso %"]
        if E["caja"] / valor > 0.005:
            pesos["SPY*"] = E["caja"] / valor * 100
        grafico_pesos(pesos, 10, 25, "tope 25%")
        st.caption("SPY\\* = liquidez estacionada hasta la próxima compra.")
        st.subheader("La tesis de cada posición")
        tt = []
        pos_hoy = rank.set_index("Acción")["Puesto"] if len(rank) else pd.Series(dtype=float)
        for t, p in E["posiciones"].items():
            s_ = p.get("tesis") or {}
            num = lambda k: (s_.get(k) if s_.get(k) is not None else np.nan)
            tt.append({"Acción": t, "Empresa": C.nombre(t), "Rentabilidad %": num("rent_prom") * 100, "Ventas crec. %": num("ventas_cagr") * 100,
                       "Rend. esperado %": num("rend_esperado") * 100, "Puesto al comprar": s_.get("Puesto"),
                       "Puesto hoy": str(int(pos_hoy.get(t))) if pd.notna(pos_hoy.get(t)) else "fuera del top 30" if len(rank) else "",
                       "Motivos para revisar": "; ".join(tesis.get(t, {}).get("motivos", []))})
        st.dataframe(pd.DataFrame(tt), hide_index=True, width="stretch", column_config={
            "Rentabilidad %": st.column_config.NumberColumn("ROIC/ROE al comprar", format="%.0f%%"),
            "Ventas crec. %": st.column_config.NumberColumn("Ventas/año al comprar", format="%.0f%%"),
            "Rend. esperado %": st.column_config.NumberColumn("Rend. 10 años al comprar", format="%.1f%%"),
            "Puesto al comprar": st.column_config.NumberColumn(format="%d")})
        st.caption("Se vende si deja de cumplir un filtro mínimo. Se revisa a mano si el ROIC baja 2 años seguidos, si el margen bruto cae "
                   "más de 3 puntos desde la compra o si la acción cae más de 25% contra el S&P. Puesto hoy: solo figura si está en el top 30.")

    with tabs[2]:
        if comb is not None:
            log = st.toggle("Escala logarítmica", value=True, key="cal_log")
            grafico_evolucion(comb, {"Cartera de calidad": AZUL, "S&P 500": GRIS, "Promedio de la lista": NARANJA}, log=log,
                              marca=(H["fin"], "Empieza el sistema real"))
            st.caption("USD 10.000 invertidos en enero de 2011. Hasta la línea punteada es el backtest; después, el sistema real con las mismas "
                       "reglas. El promedio de la lista compra todas las acciones en partes iguales.")
            res_bt = {r["Cartera"]: r for r in H.get("resumen", []) if r.get("Período") == "Todo"}
            nombres_bt = {"Cartera de calidad": "Cartera de calidad", "S&P 500": "S&P 500 (SPY)", "Promedio de la lista": "Promedio de la lista (igual peso)"}
            cols = st.columns(4)
            for col, nom in zip(cols[:3], ["Cartera de calidad", "S&P 500", "Promedio de la lista"]):
                s_ = stats_serie(comb[nom])
                caida = res_bt.get(nombres_bt[nom], {}).get("Peor caída %", s_.get("caida"))
                col.metric(nom, pct(s_.get("anual"), 1, False) + " anual")
                col.caption(f"Peor caída: {pct(caida, 1)}")
            cols[3].metric("USD 10.000 →", usd(comb["Cartera de calidad"].dropna().iloc[-1]))
            an = anual_desde({"Cartera de calidad": comb["Cartera de calidad"], "S&P 500": comb["S&P 500"]})
            an["Promedio de la lista"] = pd.Series({a["Año"]: a["Lista"] for a in H["anual"]})
            st.subheader("Año por año")
            grafico_anual(an[["Cartera de calidad", "S&P 500"]], {"Cartera de calidad": AZUL, "S&P 500": GRIS})
            tabla_anual(an, "Cartera de calidad")
        else:
            st.info("Falta historial_calidad.json en el repositorio (lo genera el backtest).")
        if len(evo_real) >= 3:
            st.subheader("Solo el sistema real")
            grafico_evolucion(evo_real.rename(columns={"cartera": "Cartera de calidad", "spy": "S&P 500"})[["Cartera de calidad", "S&P 500"]],
                              {"Cartera de calidad": AZUL, "S&P 500": GRIS})

    with tabs[3]:
        ops_bt = pd.DataFrame(H["operaciones"]) if H else pd.DataFrame()
        ops_real = pd.DataFrame(E0.get("operaciones", []))
        if len(ops_real):
            ops_real["Origen"] = "Sistema real"
            for k in ("Peso", "Resultado"):
                if k not in ops_real:
                    ops_real[k] = np.nan
        partes = [x for x in (ops_bt, ops_real) if len(x)]
        st.subheader("Historial de movimientos")
        historial_con_filtros(pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(), "cal", C.nombre)
        st.subheader("Resultado de cada posición vendida")
        v_bt = pd.DataFrame(H["ventas"]) if H else pd.DataFrame()
        v_real = pd.DataFrame(E0.get("cerradas", []))
        if len(v_real):
            v_real["Origen"] = "Sistema real"
        partes = [x[["Acción", "Compra", "Venta", "Resultado", "Motivo", "Origen"]] for x in (v_bt, v_real) if len(x)]
        ventas_con_stats(pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(), C.nombre)

    with tabs[4]:
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
            st.dataframe(r[["Puesto", "Acción", "Empresa", "Sector", "Puntaje", "Rentabilidad", "Ventas", "Deuda", "Rend10", "Tendencia",
                            "Situación"]], hide_index=True, width="stretch", height=560, column_config={
                "Puntaje": st.column_config.NumberColumn(format="%.0f"),
                "Rentabilidad": st.column_config.NumberColumn("ROIC/ROE", format="%.0f%%"),
                "Ventas": st.column_config.NumberColumn("Ventas/año", format="%.0f%%"),
                "Deuda": st.column_config.NumberColumn("Deuda/EBITDA", format="%.1fx"),
                "Rend10": st.column_config.NumberColumn("Rend. 10 años", format="%.1f%%"),
                "Tendencia": st.column_config.ProgressColumn("Tendencia", format="%.0f", min_value=0, max_value=100)})
            esp = r[(r["Puesto"] <= 20) & (~r["comprable"]) & (~r["Acción"].isin(en_cart))].copy()
            if len(esp):
                st.subheader("Lista de espera")
                st.caption("Entre las 20 mejores en calidad, pero hoy no se pueden comprar. Precio de compra = precio al que rendiría 10% anual.")
                esp["Tiene que bajar %"] = (1 - esp["PrecioCompra"] / esp["Precio"]) * 100
                st.dataframe(esp[["Puesto", "Acción", "Empresa", "Precio", "PrecioCompra", "Tiene que bajar %", "Situación"]], hide_index=True,
                             width="stretch", column_config={
                                 "Precio": st.column_config.NumberColumn("Precio hoy (USD)", format="%.2f"),
                                 "PrecioCompra": st.column_config.NumberColumn("Precio de compra (USD)", format="%.2f"),
                                 "Tiene que bajar %": st.column_config.NumberColumn(format="%.0f%%")})

    with tabs[5]:
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


def tabla_cartera_mom(cart):
    st.dataframe(cart.sort_values("Peso %", ascending=False), hide_index=True, width="stretch", column_config={
        "Peso %": st.column_config.NumberColumn(format="%.1f%%"), "Resultado %": st.column_config.NumberColumn(format="%+.1f%%"),
        "Puesto": st.column_config.NumberColumn(format="%d", help="Puesto en el ranking de hoy (se vende si pasa del 30)"),
        "Desde": st.column_config.DateColumn(format="DD/MM/YYYY")})


def pagina_momentum():
    st.title("Momentum residual")
    st.caption("10 acciones con la mejor suba propia de los últimos 12 meses · se opera el primer día hábil de cada mes · se vende solo "
               "si sale del top 30")
    with st.spinner("Calculando con los precios de hoy (la primera vez tarda hasta un minuto)..."):
        d = datos_momentum(INICIO_MOM_REAL)
    R, B = d["real"], d["bt"]
    inicio = pd.Timestamp(INICIO_MOM_REAL)
    arranco = len(R["cart"]) > 0
    hoy = date.today()
    prox = proxima_operacion_momentum(hoy)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cartera del sistema", usd(R["valor"]), help=f"Cartera de referencia de {usd(M.CAPITAL_REF)} desde el {fmt_fecha(inicio)}")
    c2.metric("Desde el inicio real", pct((R["serie"].iloc[-1] / R["serie"].iloc[0] - 1) * 100) if arranco else "—")
    c3.metric("S&P 500 mismo período", pct((R["spy"].iloc[-1] / R["spy"].iloc[0] - 1) * 100) if arranco else "—")
    c4.metric("Anual desde 2011 (backtest)", pct(stats_serie(B["serie"]).get("anual"), 1, False))
    c5.metric("Próxima operación", prox.strftime("%d/%m/%Y") if prox else "—", help="Primer día hábil del mes, al cierre")
    st.caption(f"Precios al cierre del {pd.Timestamp(d['cierre']).strftime('%d/%m/%Y')}.")
    if not arranco:
        aviso(f"El sistema real arranca el <b>{fmt_fecha(inicio)}</b>. Mientras tanto se muestra la compra inicial que haría hoy y la "
              "historia del backtest desde 2011 con las mismas reglas.")

    tabs = st.tabs(["Resumen", "Cartera", "Evolución", "Operaciones", "Ranking", "Cómo funciona"])
    with tabs[0]:
        st.subheader("1. Qué hacer")
        st.markdown(("**Hoy es día de operar.** " if prox == hoy else f"Próxima operación: **{fmt_fecha(prox)}**. ")
                    + "Estas son las órdenes que saldrían con el ranking de hoy (el mail del día confirma las definitivas):")
        if d["ords"]:
            orden = {"VENDER": 0, "RECORTAR": 1, "COMPRAR": 2, "SUMAR": 3}
            o = pd.DataFrame(sorted(d["ords"], key=lambda x: orden[x["Orden"]]))
            o.insert(2, "Empresa", [M.nombre(t) for t in o["Acción"]])
            o.insert(3, "CEDEAR", [M.cedear(t) for t in o["Acción"]])
            o["% de la cartera"] = o["Monto"] / (R["valor"] or M.CAPITAL_REF) * 100
            o["Resultado %"] = txt_pct(o["Resultado %"], 1)
            st.dataframe(o[["Orden", "Acción", "Empresa", "CEDEAR", "Puesto", "% de la cartera", "Resultado %", "Motivo"]], hide_index=True,
                         width="stretch", column_config={"% de la cartera": st.column_config.NumberColumn(format="%.1f%%"),
                                                         "Motivo": st.column_config.TextColumn(width="large")})
            st.caption("Primero las ventas, después las compras.")
        else:
            aviso("<b>No habría que hacer nada:</b> las 10 siguen dentro del top 30 y ninguna pasa del 20%.", "verde")
        st.subheader("2. Si aportás plata")
        if arranco:
            faltan = R["cart"][R["cart"]["Peso %"] < 9.7].sort_values("Peso %")
            st.markdown(("En este orden hasta que se termine: " + " · ".join(
                f"**{r['Acción']}** hasta {pct(10 - r['Peso %'], 1, False)} de la cartera" for _, r in faltan.iterrows()) + ".")
                if len(faltan) else "Todas están cerca del 10%: repartilo en partes iguales entre las 10.")
        else:
            st.markdown("Cuando arranque el sistema, acá aparece dónde poner los aportes.")
        st.subheader("3. Alertas")
        alertas = []
        if arranco:
            for _, r in R["cart"].iterrows():
                if r["Peso %"] > 20:
                    alertas.append(f"**{r['Acción']}** pesa {pct(r['Peso %'], 1, False)}: se recorta a 12,5%.")
                if pd.isna(r["Puesto"]) or r["Puesto"] > 30:
                    alertas.append(f"**{r['Acción']}** salió del top 30: se vende en la próxima operación.")
                elif r["Puesto"] >= 25:
                    alertas.append(f"**{r['Acción']}** está en el puesto {int(r['Puesto'])}: se vende si pasa del 30.")
            sect = R["cart"]["Sector"].value_counts()
            for s_, n_ in sect[sect >= 3].items():
                alertas.append(f"Hay {n_} acciones de **{s_.lower()}** (solo informativo).")
        st.markdown("\n".join(f"- {a}" for a in alertas) if alertas else "Sin alertas.")

    with tabs[1]:
        if arranco:
            tabla_cartera_mom(R["cart"])
            grafico_pesos(R["cart"].set_index("Acción")["Peso %"], 10, 20, "tope 20%")
        else:
            st.markdown("**Compra inicial si la cartera arrancara hoy** (10% en cada una):")
            ini = pd.DataFrame([{"Acción": t, "Empresa": M.nombre(t), "CEDEAR": M.cedear(t), "Sector": M.SECTOR.get(t, "Otros"),
                                 "Puesto": d["rk"]["Puesto"].get(t), "Suba 12 meses %": d["rk"]["Suba 12-1 %"].get(t)}
                                for t in d["hold2"]]).sort_values("Puesto")
            st.dataframe(ini, hide_index=True, width="stretch", column_config={"Suba 12 meses %": st.column_config.NumberColumn(format="%+.0f%%")})
            st.caption("Es una referencia: la compra real sale en el mail del primer día hábil desde la fecha de inicio.")
        with st.expander("Cartera que tendría hoy el backtest (si se hubiera seguido desde 2011)"):
            tabla_cartera_mom(B["cart"])

    with tabs[2]:
        log = st.toggle("Escala logarítmica", value=True, key="mom_log")
        grafico_evolucion(pd.DataFrame({"Momentum": B["serie"], "S&P 500": B["spy"]}), {"Momentum": AZUL, "S&P 500": GRIS}, log=log)
        st.caption(f"Backtest: USD 10.000 desde el {fmt_fecha(B['serie'].index[0])} con las mismas reglas y el mismo código del mail. "
                   "La lista de acciones es la de hoy (sesgo de supervivencia).")
        s_m, s_s = stats_serie(B["serie"]), stats_serie(B["spy"])
        cols = st.columns(4)
        cols[0].metric("Momentum", pct(s_m.get("anual"), 1, False) + " anual")
        cols[0].caption(f"Peor caída: {pct(s_m.get('caida'), 1)}")
        cols[1].metric("S&P 500", pct(s_s.get("anual"), 1, False) + " anual")
        cols[1].caption(f"Peor caída: {pct(s_s.get('caida'), 1)}")
        cols[2].metric("Volatilidad anual", pct(s_m.get("vol"), 1, False))
        cols[2].caption(f"S&P 500: {pct(s_s.get('vol'), 1, False)}")
        cols[3].metric("USD 10.000 →", usd(B["serie"].iloc[-1]))
        an = anual_desde({"Momentum": B["serie"], "S&P 500": B["spy"]})
        st.subheader("Año por año")
        grafico_anual(an, {"Momentum": AZUL, "S&P 500": GRIS})
        tabla_anual(an, "Momentum")
        if arranco and len(R["serie"]) >= 5:
            st.subheader("Solo el sistema real")
            grafico_evolucion(pd.DataFrame({"Momentum": R["serie"], "S&P 500": R["spy"]}), {"Momentum": AZUL, "S&P 500": GRIS})

    with tabs[3]:
        opciones = ["Backtest desde 2011"] + (["Sistema real"] if arranco else [])
        cual = st.radio("Ver", opciones, horizontal=True, key="mom_ver", index=len(opciones) - 1)
        X = R if cual == "Sistema real" else B
        st.subheader("Historial de órdenes")
        h = X["historial"]
        if len(h):
            hh = h[["Fecha", "Orden", "Acción", "Peso", "Resultado", "Motivo"]].copy()
            hh["Origen"] = cual
            historial_con_filtros(hh, "mom_r" if cual == "Sistema real" else "mom_b", M.nombre)
        else:
            st.info("Todavía no hay órdenes.")
        st.subheader("Operaciones cerradas")
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
        st.dataframe(rk[["Puesto", "Acción", "Empresa", "CEDEAR", "Sector", "Suba 12-1 %", "Volatilidad %", "Puntaje", "Situación"]],
                     hide_index=True, width="stretch", height=560, column_config={
                         "Suba 12-1 %": st.column_config.NumberColumn("Suba 12 meses", format="%+.0f%%"),
                         "Volatilidad %": st.column_config.NumberColumn("Volatilidad", format="%.0f%%"),
                         "Puntaje": st.column_config.NumberColumn(format="%.2f")})

    with tabs[5]:
        st.markdown(REGLAS_MOMENTUM)


pg = st.navigation([st.Page(pagina_calidad, title="Cartera de calidad", icon="🏛️", default=True),
                    st.Page(pagina_momentum, title="Momentum residual", icon="🚀", url_path="momentum")])
st.sidebar.caption("Estrategias con CEDEARs · datos con fines educativos, no es recomendación de inversión.")
pg.run()
