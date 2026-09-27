"""
STOCK SCREENER - Acciones de EE.UU. con CEDEAR
==============================================
Filtra acciones según 5 criterios y entrega un Excel con colores.

  1. Volumen      : volumen promedio diario en USD alto.
  2. EMAs         : precio arriba (o cerca) de la EMA 200 semanal, y la
                    EMA 20 pegada a la EMA 200 o el precio arriba de la EMA 20.
  3. Corrección   : caída de 25% a 60% desde el máximo de 2 años.
  4. Consolidación: si la tendencia previa era bajista, más de 100 días
                    lateralizando dentro de una banda de precio; si era
                    alcista, 30-120 días desde el último máximo.
  5. Valuación P/E: APAGADO (se muestra como dato informativo).
  6. Mercado      : solo se compra si el S&P 500 está arriba de su media de
                    200 días.
  7. Beta         : beta histórico >= 1,3, calculado con 2 años de retornos
                    semanales contra el S&P (solo datos pasados).

Además avisa si la empresa presenta balance en los próximos días y si se
esperan ganancias en alza o en baja (P/E proyectado vs actual).

INSTALACIÓN (una sola vez)
--------------------------
    pip install yfinance pandas openpyxl reportlab

USO
---
    python screener.py                  # corre sobre la lista por defecto
    python screener.py AAPL MSFT NVDA   # corre sobre los tickers que indiques

Genera "screener_AAAA-MM-DD.xlsx" (detalle) y "screener_AAAA-MM-DD.pdf" (resumen).
Necesita internet (baja los datos de Yahoo Finance).
"""

import sys
import time
from datetime import date

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None


# =============================================================================
# CONFIGURACIÓN - todo lo que se puede ajustar está acá
# =============================================================================

# Prender / apagar cada filtro. Un filtro apagado se calcula y se muestra en
# el Excel igual, pero no cuenta para decidir si la acción "pasa".
FILTROS_ACTIVOS = {
    "volumen": True,
    "emas": True,
    "correccion": True,
    "consolidacion": True,
    "valuacion": False,   # apagado en la estrategia nueva (se muestra igual)
    "mercado": True,
    "beta": True,
}

CONFIG = {
    # --- 1. Volumen ---
    "volumen_min_usd": 20_000_000,       # promedio diario mínimo, en USD
    "volumen_dias": 30,                  # ruedas para promediar

    # --- 2. EMAs semanales ---
    "ema_corta": 20,
    "ema_larga": 200,
    "precio_cerca_ema200": 0.10,         # "cerca" = hasta 10% por debajo de la EMA200 (original: 0.05)
    "ema20_pegada_ema200": 0.05,         # "pegadas" = a menos de 5% una de otra

    # --- 3. Corrección desde el máximo ---
    "beta_alto_desde": 1.3,              # beta >= 1.3 se considera alto
    "correccion_beta_alto": (0.25, 0.60),  # estrategia nueva: 25-60% para todas (original: 0.35-0.40)
    "correccion_beta_bajo": (0.25, 0.60),  # (original: 0.15-0.25)
    "correccion_ventana_semanas": 104,   # busca el máximo en los últimos 2 años

    # --- 4. Consolidación ---
    "rango_banda_max": 0.20,             # lateraliza si (máx / mín - 1) <= 20%
    "rango_min_dias_si_bajista": 100,    # días corridos en rango
    "dias_desde_max_si_alcista": (30, 120),  # original: (30, 45)
    "ventana_ultimo_max_ruedas": 126,    # busca el "último máximo" en ~6 meses

    # --- 5. Valuación P/E ---
    "pe_tipo": "trailing",               # "trailing" (últimos 12 meses) o "forward"
    "large_cap_desde_usd": 50_000_000_000,
    "pe_large_cap": (8, 35),             # original: (12, 17)
    "pe_small_mid_cap": (5, 25),         # original: (5, 10)

    # --- 7. Beta histórico ---
    "beta_min": 1.3,                     # beta mínimo (2 años de retornos semanales vs S&P)
    "beta_semanas": 104,

    # --- 6. Mercado ---
    "mercado_media_dias": 200,           # el S&P tiene que estar arriba de esta media

    # --- Salida ---
    "mantener_ruedas": 126,              # vender a las 126 ruedas (~6 meses)

    # --- Avisos (no filtran, solo informan) ---
    "aviso_balance_dias": 10,            # avisa si presenta balance en los próximos N días
}

# Lista por defecto: 139 acciones con CEDEAR en BYMA (verificado contra el listado oficial de BYMA de
# feb-2026 y el de Rankia de sep-2026). Se sacaron 15 que NO tienen CEDEAR: UPS, NXPI, INTU, BLK, MCO,
# LOW, EXPE, MAR, REGN, AA, CMCSA, DUK, SO, AMT, SPG. Barrick cambió su símbolo de GOLD a B en 2025.
# Códigos distintos en BYMA: BAC = BA.C, BRK-B = BRKB, DIS = DISN.
LISTA_TICKERS = sorted(set([
    # Tecnología
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX", "AMD", "AVGO", "CRM", "ADBE",
    "ORCL", "IBM", "INTC", "QCOM", "TXN", "MU", "CSCO", "ADI", "AMAT", "LRCX", "KLAC", "TSM",
    "ASML", "SAP", "NOW", "ACN", "HPQ", "DELL", "SHOP", "SPOT", "SNAP", "PINS", "ROKU", "ZM",
    "DOCU", "TWLO", "UBER", "ABNB", "PLTR", "SNOW", "COIN", "XYZ", "PYPL", "EBAY", "ETSY", "SONY",
    "GLOB", "MELI", "BABA", "JD", "BIDU", "NIO",
    # Finanzas
    "V", "MA", "AXP", "JPM", "BAC", "C", "GS", "MS", "WFC", "USB", "SCHW", "SPGI",
    "BK", "BRK-B",
    # Consumo
    "KO", "PEP", "MCD", "SBUX", "NKE", "DIS", "HD", "WMT", "COST", "TGT", "PG", "CL", "KMB",
    "MO", "PM", "BKNG", "F", "GM", "TM", "HMC", "ARCO",
    # Salud
    "PFE", "JNJ", "MRK", "ABBV", "LLY", "BMY", "AMGN", "GILD", "UNH", "CVS", "MDT", "ABT", "TMO",
    "DHR", "BIIB", "VRTX", "MRNA", "NVS", "AZN", "GSK",
    # Energía y materiales
    "XOM", "CVX", "COP", "OXY", "SLB", "HAL", "PBR", "VALE", "BP", "SHEL", "RIO", "BHP", "NEM",
    "B", "FCX", "DOW",
    # Industria, telecom y otros
    "CAT", "DE", "BA", "GE", "HON", "MMM", "LMT", "RTX", "FDX", "T", "VZ", "TMUS",
    "NEE", "ADP",
]))

# Las 48 acciones de las primeras pruebas (solo informativo)
LISTA_48_ORIGINAL = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX",
    "AMD", "AVGO", "CRM", "ADBE", "ORCL", "IBM", "INTC", "QCOM",
    "PYPL", "V", "MA", "JPM", "BAC", "GS", "MS", "WFC",
    "KO", "PEP", "MCD", "SBUX", "NKE", "DIS", "HD", "LOW",
    "XOM", "CVX", "PBR", "VALE", "BABA", "MELI", "UBER", "ABNB",
    "PFE", "JNJ", "MRK", "ABBV", "UNH", "COIN", "PLTR", "SNOW",
]

NOMBRES_FILTROS = {
    "volumen": "Volumen",
    "emas": "EMAs",
    "correccion": "Corrección",
    "consolidacion": "Consolidación",
    "valuacion": "P/E",
    "mercado": "Mercado",
    "beta": "Beta",
}


# =============================================================================
# PASO 1 - DESCARGA
# =============================================================================

def descargar_precios(tickers):
    """Baja toda la historia diaria de todos los tickers en una sola llamada.
    Devuelve {ticker: DataFrame con columnas Close y Volume}."""
    print(f"Descargando precios de {len(tickers)} acciones...")
    datos = yf.download(
        tickers, period="max", interval="1d", auto_adjust=True,
        group_by="ticker", threads=True, progress=False,
    )
    precios = {}
    for t in tickers:
        try:
            if isinstance(datos.columns, pd.MultiIndex):
                df = datos[t]
            else:
                df = datos
            df = df[["Close", "Volume"]].dropna(subset=["Close"])
            if not df.empty:
                precios[t] = df
        except KeyError:
            pass
    return precios


def descargar_fundamentales(tickers):
    """Pide beta, capitalización y P/E una sola vez por acción."""
    print("Descargando datos fundamentales (beta, capitalización, P/E)...")
    fundamentales = {}
    for i, t in enumerate(tickers, 1):
        print(f"  {i}/{len(tickers)} {t}", end="\r")
        info = {}
        for intento in range(3):  # reintenta si Yahoo limita las consultas
            try:
                info = yf.Ticker(t).info or {}
                break
            except Exception:
                time.sleep(3 * (intento + 1))
        fundamentales[t] = {
            "beta": info.get("beta"),
            "market_cap": info.get("marketCap"),
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "nombre": info.get("shortName") or info.get("longName") or "",
            "balance_ts": info.get("earningsTimestampStart") or info.get("earningsTimestamp"),
            "roe": info.get("returnOnEquity"),
            "margen": info.get("profitMargins"),
            "sector": info.get("sector") or "",
        }
    print(" " * 40, end="\r")
    return fundamentales


# =============================================================================
# NIVEL DE CALIDAD DE CADA ACCIÓN (solo para identificar, no filtra)
# =============================================================================
# Puntaje = promedio del percentil de 3 datos actuales: tamaño (capitalización),
# rentabilidad sobre el patrimonio (ROE) y margen neto. Empresas que pierden plata
# no pueden ser Premium.
#   Premium       = 20 mejores puntajes
#   Sólida        = siguientes 50
#   Especulativa  = resto
NIVEL_PREMIUM, NIVEL_SOLIDA = 20, 50


def clasificar_niveles(fundamentales):
    df = pd.DataFrame({t: {"mcap": f.get("market_cap"), "roe": f.get("roe"), "margen": f.get("margen")}
                       for t, f in fundamentales.items()}).T.apply(pd.to_numeric, errors="coerce")
    if df.empty:
        return {}
    pct = df.rank(pct=True).fillna(0)
    df["puntaje"] = (pct["mcap"] + pct["roe"] + pct["margen"]) / 3 * 100
    df.loc[~(df["margen"] > 0), "puntaje"] -= 50          # con pérdidas, nunca Premium
    df = df.sort_values("puntaje", ascending=False)
    niveles = {}
    for k, t in enumerate(df.index):
        nivel = "Premium" if k < NIVEL_PREMIUM else "Sólida" if k < NIVEL_PREMIUM + NIVEL_SOLIDA else "Especulativa"
        niveles[t] = {"Nivel": nivel, "Puntaje calidad": round(float(df.loc[t, "puntaje"]), 1)}
    return niveles


ESTRELLAS = {"Premium": "★★★", "Sólida": "★★", "Especulativa": "★"}


# =============================================================================
# PASO 2 - INDICADORES
# =============================================================================

def dias_en_rango(close, banda):
    """Cuántos días corridos hacia atrás (desde hoy) el precio se mantuvo
    dentro de una banda: máximo / mínimo - 1 <= banda."""
    invertido = close.iloc[::-1]
    amplitud = invertido.cummax() / invertido.cummin() - 1
    n = int((amplitud <= banda).sum())  # la amplitud solo crece hacia atrás
    if n < 2:
        return 0, close.index[-1]
    inicio = close.index[-n]
    return (close.index[-1] - inicio).days, inicio


def beta_historico(close, spy, semanas=104):
    """Beta semanal vs S&P con los últimos `semanas`, hasta la semana ANTERIOR
    (igual que en el backtest). Devuelve la serie semanal."""
    close = close.copy()
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    ws = close.resample("W-FRI").last().pct_change()
    wb = spy.resample("W-FRI").last().pct_change().reindex(ws.index)
    return (ws.rolling(semanas, min_periods=52).cov(wb) / wb.rolling(semanas, min_periods=52).var()).shift(1)


def calcular_indicadores(ticker, df, fund, cfg):
    close = df["Close"]
    fila = {"Ticker": ticker, "Nombre": fund.get("nombre", "")}

    # 1. Volumen promedio en USD
    ult = df.tail(cfg["volumen_dias"])
    fila["Volumen prom. USD (M)"] = (ult["Close"] * ult["Volume"]).mean() / 1e6

    # 2. EMAs semanales (semanas cerradas los viernes)
    semanal = close.resample("W-FRI").last().dropna()
    fila["Semanas de historia"] = len(semanal)
    ema_c = semanal.ewm(span=cfg["ema_corta"], adjust=False).mean().iloc[-1]
    ema_l = semanal.ewm(span=cfg["ema_larga"], adjust=False).mean().iloc[-1]
    precio = close.iloc[-1]
    fila["Precio"] = precio
    fila["EMA20 sem."] = ema_c
    fila["EMA200 sem."] = ema_l
    fila["Precio vs EMA200 %"] = (precio / ema_l - 1) * 100
    fila["EMA20 vs EMA200 %"] = (ema_c / ema_l - 1) * 100

    # 3. Corrección desde el máximo de la ventana
    ventana = semanal.tail(cfg["correccion_ventana_semanas"])
    fila["Máximo 2 años"] = ventana.max()
    fila["Caída desde máx. %"] = (1 - precio / ventana.max()) * 100
    spy = globals().get("SPY_SERIE")
    beta = None
    if spy is not None:
        b = beta_historico(close, spy, cfg.get("beta_semanas", 104))
        if len(b) and pd.notna(b.iloc[-1]):
            beta = float(b.iloc[-1])
    fila["Beta"] = beta
    fila["Beta Yahoo"] = fund.get("beta")
    fila["Beta alto"] = "Sí" if (beta is not None and beta >= cfg["beta_alto_desde"]) else "No"

    # 4. Consolidación
    dias_rango, inicio_rango = dias_en_rango(close, cfg["rango_banda_max"])
    fila["Días en rango"] = dias_rango
    # Tendencia previa: precio al empezar el rango vs 1 año antes de eso
    pos_inicio = close.index.get_loc(inicio_rango)
    pos_antes = max(pos_inicio - 252, 0)
    tend_alcista = close.iloc[pos_inicio] > close.iloc[pos_antes]
    fila["Tendencia previa"] = "Alcista" if tend_alcista else "Bajista"
    reciente = close.tail(cfg["ventana_ultimo_max_ruedas"])
    fila["Días desde últ. máx."] = (close.index[-1] - reciente.idxmax()).days

    # 5. Valuación
    mcap = fund.get("market_cap")
    fila["Capitalización USD (B)"] = mcap / 1e9 if mcap else None
    fila["Categoría"] = (
        "Large cap" if (mcap and mcap >= cfg["large_cap_desde_usd"]) else "Small/Mid cap"
    )
    pe = fund.get("pe_forward") if cfg["pe_tipo"] == "forward" else fund.get("pe_trailing")
    fila["P/E"] = pe
    return fila


# =============================================================================
# PASO 3 - FILTROS
# =============================================================================

def evaluar(fila, cfg):
    """Devuelve {filtro: True/False} para una fila de indicadores."""
    r = {}

    r["volumen"] = fila["Volumen prom. USD (M)"] * 1e6 >= cfg["volumen_min_usd"]

    if fila["Semanas de historia"] < cfg["ema_larga"]:
        r["emas"] = False
    else:
        precio_ok = fila["Precio vs EMA200 %"] >= -cfg["precio_cerca_ema200"] * 100
        pegadas = abs(fila["EMA20 vs EMA200 %"]) <= cfg["ema20_pegada_ema200"] * 100
        arriba_ema20 = fila["Precio"] > fila["EMA20 sem."]
        r["emas"] = bool(precio_ok and (pegadas or arriba_ema20))

    lo, hi = cfg["correccion_beta_alto"] if fila["Beta alto"] == "Sí" else cfg["correccion_beta_bajo"]
    r["correccion"] = lo * 100 <= fila["Caída desde máx. %"] <= hi * 100

    if fila["Tendencia previa"] == "Bajista":
        r["consolidacion"] = fila["Días en rango"] >= cfg["rango_min_dias_si_bajista"]
    else:
        lo, hi = cfg["dias_desde_max_si_alcista"]
        r["consolidacion"] = lo <= fila["Días desde últ. máx."] <= hi

    pe = fila["P/E"]
    if pe is None or (isinstance(pe, float) and np.isnan(pe)):
        r["valuacion"] = False
    else:
        lo, hi = cfg["pe_large_cap"] if fila["Categoría"] == "Large cap" else cfg["pe_small_mid_cap"]
        r["valuacion"] = lo <= pe <= hi

    bmin = cfg.get("beta_min")
    bv = fila.get("Beta")
    r["beta"] = True if not bmin else bool(bv is not None and pd.notna(bv) and bv >= bmin)

    # Mercado: si no se informa (por ejemplo en los backtests), no filtra.
    r["mercado"] = bool(fila.get("S&P sobre media 200", True))

    return r


def estado_mercado(cfg=CONFIG):
    """Devuelve (True/False, precio S&P, media) según el S&P 500 vs su media."""
    try:
        d = yf.download("SPY", period="5y", interval="1d", auto_adjust=True, progress=False)
        if isinstance(d.columns, pd.MultiIndex) and "Close" not in d.columns.get_level_values(0):
            d = d.xs("SPY", axis=1, level=0)
        spy = d["Close"].squeeze().dropna()
        if spy.index.tz is not None:
            spy.index = spy.index.tz_localize(None)
        globals()["SPY_SERIE"] = spy
        media = spy.rolling(cfg["mercado_media_dias"]).mean().iloc[-1]
        return bool(spy.iloc[-1] > media), float(spy.iloc[-1]), float(media)
    except Exception:
        return True, None, None


def avisos(fund, cfg=CONFIG):
    """Aviso de balance próximo y tendencia de ganancias (P/E proyectado vs actual)."""
    import datetime as _dt
    res = {"Balance en (días)": None, "Ganancias esperadas": ""}
    ts = fund.get("balance_ts")
    if ts:
        try:
            dias = (_dt.datetime.fromtimestamp(int(ts)).date() - date.today()).days
            if dias >= 0:
                res["Balance en (días)"] = dias
        except Exception:
            pass
    pt, pf = fund.get("pe_trailing"), fund.get("pe_forward")
    if pt and pf and pt > 0 and pf > 0:
        res["Ganancias esperadas"] = "En alza" if pf < pt else "En baja"
    aviso = []
    d = res["Balance en (días)"]
    if d is not None and d <= cfg["aviso_balance_dias"]:
        aviso.append(f"Balance en {d} días: esperar")
    if res["Ganancias esperadas"] == "En baja":
        aviso.append("Ganancias esperadas en baja")
    res["Aviso"] = "; ".join(aviso)
    return res


def procesar(tickers, precios, fundamentales, cfg=CONFIG, activos=FILTROS_ACTIVOS, mercado_ok=None):
    filas = []
    for t in tickers:
        if t not in precios:
            filas.append({"Ticker": t, "Error": "Sin datos de precio"})
            continue
        try:
            fila = calcular_indicadores(t, precios[t], fundamentales.get(t, {}), cfg)
            if mercado_ok is not None:
                fila["S&P sobre media 200"] = mercado_ok
            fila.update(avisos(fundamentales.get(t, {}), cfg))
            fila.update(globals().get("NIVELES", {}).get(t, {"Nivel": "", "Puntaje calidad": None}))
            fu = fundamentales.get(t, {})
            fila["ROE %"] = fu.get("roe") * 100 if fu.get("roe") is not None else None
            fila["Margen neto %"] = fu.get("margen") * 100 if fu.get("margen") is not None else None
            fila["Sector"] = fu.get("sector", "")
            res = evaluar(fila, cfg)
            for f, ok in res.items():
                fila["✔ " + NOMBRES_FILTROS[f]] = bool(ok)
            fallas = [NOMBRES_FILTROS[f] for f, ok in res.items() if activos[f] and not ok]
            fila["Filtros que falla"] = len(fallas)
            fila["Falla en"] = ", ".join(fallas)
            fila["PASA"] = len(fallas) == 0
            filas.append(fila)
        except Exception as e:
            filas.append({"Ticker": t, "Error": str(e)})

    df = pd.DataFrame(filas)
    if "Filtros que falla" in df:
        df = df.sort_values(["Filtros que falla", "Ticker"], na_position="last")
    return df.reset_index(drop=True)


# =============================================================================
# PASO 4 - EXCEL
# =============================================================================

def exportar_excel(df, ruta, cfg=CONFIG, activos=FILTROS_ACTIVOS):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    verde = PatternFill("solid", fgColor="C6EFCE")
    rojo = PatternFill("solid", fgColor="FFC7CE")
    gris = PatternFill("solid", fgColor="EDEDED")
    encabezado = PatternFill("solid", fgColor="1F3864")

    cols_filtro = ["✔ " + n for n in NOMBRES_FILTROS.values()]
    orden = (["Ticker", "Nombre", "Nivel", "PASA", "Aviso", "Filtros que falla", "Falla en"] + cols_filtro + [
        "Volumen prom. USD (M)", "Precio", "EMA20 sem.", "EMA200 sem.",
        "Precio vs EMA200 %", "EMA20 vs EMA200 %", "Máximo 2 años",
        "Caída desde máx. %", "Beta", "Beta Yahoo", "Beta alto", "Tendencia previa",
        "Días en rango", "Días desde últ. máx.", "Capitalización USD (B)",
        "Categoría", "P/E", "Ganancias esperadas", "Balance en (días)", "Puntaje calidad", "ROE %",
        "Margen neto %", "Sector",
        "Semanas de historia", "Error",
    ])
    df = df[[c for c in orden if c in df.columns]]
    aprobadas = df[df.get("PASA", pd.Series(False, index=df.index)) == True]  # noqa: E712

    # Resumen
    total = len(df)
    resumen = [("Fecha", date.today().isoformat()), ("Acciones analizadas", total), ("", "")]
    resumen.append(("Filtro", "Pasan / Estado"))
    for f, nombre in NOMBRES_FILTROS.items():
        col = "✔ " + nombre
        n = int((df[col] == True).sum()) if col in df else 0
        estado = "" if activos[f] else "  (APAGADO)"
        resumen.append((nombre, f"{n} de {total}{estado}"))
    resumen.append(("PASAN TODOS LOS ACTIVOS", f"{len(aprobadas)} de {total}"))
    resumen += [("", ""), ("Parámetros", "")]
    resumen += [(k, str(v)) for k, v in cfg.items()]
    df_res = pd.DataFrame(resumen, columns=["Concepto", "Valor"])

    with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
        df_res.to_excel(xw, sheet_name="Resumen", index=False)
        df.to_excel(xw, sheet_name="Todas", index=False)
        aprobadas.to_excel(xw, sheet_name="Aprobadas", index=False)

        for nombre_hoja in ["Todas", "Aprobadas"]:
            ws = xw.sheets[nombre_hoja]
            cols = list(df.columns)
            for j, col in enumerate(cols, 1):
                c = ws.cell(row=1, column=j)
                c.fill, c.font = encabezado, Font(bold=True, color="FFFFFF")
                c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                ws.column_dimensions[get_column_letter(j)].width = (
                    28 if col in ("Nombre", "Falla en", "Aviso") else 13
                )
                for i in range(2, ws.max_row + 1):
                    cel = ws.cell(row=i, column=j)
                    if col in cols_filtro or col == "PASA":
                        if cel.value is True:
                            cel.value, cel.fill = "Sí", verde
                        elif cel.value is False:
                            cel.value, cel.fill = "No", rojo
                        # filtro apagado: gris
                        filtro = next((f for f, n in NOMBRES_FILTROS.items() if "✔ " + n == col), None)
                        if filtro and not activos[filtro]:
                            cel.fill = gris
                        cel.alignment = Alignment(horizontal="center")
                    elif isinstance(cel.value, float):
                        cel.number_format = "#,##0.00"
            ws.row_dimensions[1].height = 32
            ws.freeze_panes = "C2"
            ws.auto_filter.ref = ws.dimensions

        ws = xw.sheets["Resumen"]
        ws.column_dimensions["A"].width = 32
        ws.column_dimensions["B"].width = 36
        for c in ws[1]:
            c.fill, c.font = encabezado, Font(bold=True, color="FFFFFF")
        for fila in ws.iter_rows(min_row=2):
            if fila[0].value in ("Filtro", "Parámetros", "PASAN TODOS LOS ACTIVOS"):
                fila[0].font = fila[1].font = Font(bold=True)


# =============================================================================
# PRINCIPAL
# =============================================================================

# =============================================================================
# SEGUIMIENTO DE OPERACIONES (abiertas y cerradas recientemente)
# =============================================================================
# Si existe un archivo "cartera.csv" (columnas: Ticker,Fecha,Precio - fecha en
# formato AAAA-MM-DD), se siguen esas compras reales. Si no existe, se muestran
# las operaciones que habría abierto el sistema en los últimos meses.

def _serie_dias(df, fund, cfg, desde):
    """Indicadores del screener para cada rueda desde `desde` (vectorizado)."""
    df = df.copy()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    c = df["Close"]
    idx, cv = c.index, c.values.astype(float)
    vol = ((c * df["Volume"]).rolling(cfg["volumen_dias"], min_periods=1).mean() / 1e6).values
    sem = c.resample("W-FRI").last().dropna()
    ec = sem.ewm(span=cfg["ema_corta"], adjust=False).mean().values
    el = sem.ewm(span=cfg["ema_larga"], adjust=False).mean().values
    maxprev = sem.rolling(cfg["correccion_ventana_semanas"] - 1, min_periods=1).max().values
    pos_sem = sem.index.get_indexer(idx.to_period("W-FRI").end_time.normalize())
    ac, al = 2 / (cfg["ema_corta"] + 1), 2 / (cfg["ema_larga"] + 1)
    pe_hoy = fund.get("pe_forward" if cfg["pe_tipo"] == "forward" else "pe_trailing")
    mcap_hoy = fund.get("market_cap")
    spy = globals().get("SPY_SERIE")
    if spy is not None:
        bser = beta_historico(c, spy, cfg.get("beta_semanas", 104))
        beta_dia = bser.reindex(idx.to_period("W-FRI").end_time.normalize()).values
    else:
        beta_dia = np.full(len(idx), np.nan)
    filas = []
    for i in np.where(idx >= pd.Timestamp(desde))[0]:
        p, x = pos_sem[i], cv[i]
        ema_c = x if p == 0 else ac * x + (1 - ac) * ec[p - 1]
        ema_l = x if p == 0 else al * x + (1 - al) * el[p - 1]
        maximo = x if p == 0 else max(x, maxprev[p - 1])
        lo = max(0, i - 1500)
        inv = cv[lo:i + 1][::-1]
        amp = np.maximum.accumulate(inv) / np.minimum.accumulate(inv) - 1
        k = int((amp <= cfg["rango_banda_max"]).sum())
        inicio = i if k < 2 else i - k + 1
        j = max(0, i - cfg["ventana_ultimo_max_ruedas"] + 1)
        j += int(np.argmax(cv[j:i + 1]))
        esc = x / cv[-1]
        beta = beta_dia[i] if pd.notna(beta_dia[i]) else None
        mcap = mcap_hoy * esc if mcap_hoy else None
        filas.append({
            "Fecha": idx[i], "i": i, "Volumen prom. USD (M)": vol[i], "Semanas de historia": p + 1,
            "Precio": x, "EMA20 sem.": ema_c, "EMA200 sem.": ema_l,
            "Precio vs EMA200 %": (x / ema_l - 1) * 100, "EMA20 vs EMA200 %": (ema_c / ema_l - 1) * 100,
            "Caída desde máx. %": (1 - x / maximo) * 100,
            "Beta": beta,
            "Beta alto": "Sí" if (beta is not None and beta >= cfg["beta_alto_desde"]) else "No",
            "Días en rango": (idx[i] - idx[inicio]).days if k >= 2 else 0,
            "Tendencia previa": "Alcista" if cv[inicio] > cv[max(inicio - 252, 0)] else "Bajista",
            "Días desde últ. máx.": (idx[i] - idx[j]).days,
            "Categoría": "Large cap" if (mcap and mcap >= cfg["large_cap_desde_usd"]) else "Small/Mid cap",
            "P/E": pe_hoy * esc if pe_hoy else None,
        })
    return pd.DataFrame(filas)


def _fila_operacion(t, close, spy, fecha_entrada, precio_entrada, cfg):
    close = close.copy()
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    fecha_entrada = pd.Timestamp(fecha_entrada)
    k = int(close.index.searchsorted(fecha_entrada))
    if k >= len(close):
        k = len(close) - 1
    precio_entrada = precio_entrada or float(close.iloc[k])
    m = cfg["mantener_ruedas"]
    cerrada = k + m <= len(close) - 1
    fecha_salida = close.index[k + m] if cerrada else fecha_entrada + pd.offsets.BDay(m)
    precio_final = float(close.iloc[k + m]) if cerrada else float(close.iloc[-1])
    ret = precio_final / precio_entrada - 1
    ret_spy = None
    if spy is not None:
        s = spy.reindex(close.index).ffill()
        s0, s1 = s.iloc[k], (s.iloc[k + m] if cerrada else s.iloc[-1])
        if pd.notna(s0) and pd.notna(s1):
            ret_spy = s1 / s0 - 1
    dias = int(np.busday_count(date.today(), fecha_salida.date())) if not cerrada else 0
    return {
        "Ticker": t, "Entrada": fecha_entrada.date(), "Precio entrada": precio_entrada,
        "Precio actual" if not cerrada else "Precio salida": precio_final,
        "Resultado %": ret * 100, "S&P mismo período %": ret_spy * 100 if ret_spy is not None else None,
        "vs S&P %": (ret - ret_spy) * 100 if ret_spy is not None else None,
        "Vender el": fecha_salida.date(), "Ruedas restantes": dias, "Estado": "Cerrada" if cerrada else "Abierta",
    }


def seguimiento(precios, fundamentales, cfg=CONFIG, activos=FILTROS_ACTIVOS, meses_atras=24, dias_cerradas=30):
    """Devuelve (abiertas, cerradas_recientes, origen)."""
    import os
    spy = globals().get("SPY_SERIE")
    ops, origen = [], "sistema"
    if os.path.exists("cartera.csv"):
        origen = "cartera"
        cart = pd.read_csv("cartera.csv")
        for _, r in cart.iterrows():
            t = str(r["Ticker"]).strip().upper()
            if t in precios:
                ops.append(_fila_operacion(t, precios[t]["Close"], spy, r["Fecha"], r.get("Precio"), cfg))
    elif spy is not None:
        spy_ok = spy > spy.rolling(cfg["mercado_media_dias"]).mean()
        desde = (pd.Timestamp.today() - pd.DateOffset(months=meses_atras)).normalize()
        for t, df in precios.items():
            try:
                ind = _serie_dias(df, fundamentales.get(t, {}), cfg, desde)
                if ind.empty:
                    continue
                ind["S&P sobre media 200"] = spy_ok.reindex(ind["Fecha"]).ffill().fillna(False).values
                ev = ind.apply(lambda f: evaluar(f, cfg), axis=1, result_type="expand")
                ok = ev[[f for f in activos if activos[f]]].all(axis=1)
                ultimo = -10**9
                for _, f in ind[ok].iterrows():
                    if f["i"] - ultimo >= cfg["mantener_ruedas"]:   # sin repetir si ya está en cartera
                        ultimo = f["i"]
                        ops.append(_fila_operacion(t, df["Close"], spy, f["Fecha"], f["Precio"], cfg))
            except Exception as e:
                print(f"  (seguimiento {t}: {e})")
    ops = pd.DataFrame(ops)
    if ops.empty:
        return ops, ops, origen
    niv = globals().get("NIVELES", {})
    ops.insert(1, "Nivel", ops["Ticker"].map(lambda t: niv.get(t, {}).get("Nivel", "")))
    abiertas = ops[ops["Estado"] == "Abierta"].sort_values("Vender el").reset_index(drop=True)
    import datetime as _dt
    limite = date.today() - _dt.timedelta(days=dias_cerradas)
    cerradas = ops[(ops["Estado"] == "Cerrada") & (ops["Vender el"] >= limite)].sort_values("Vender el").reset_index(drop=True)
    return abiertas, cerradas, origen


def generar_pdf(df, ruta_pdf, cfg=CONFIG, activos=FILTROS_ACTIVOS, abiertas=None, cerradas=None,
                origen="sistema", ejemplo=False):
    """Arma un PDF de 1-2 páginas con el resumen del día."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    azul, verde, rojo, gris = (colors.HexColor(c) for c in ("#1F3864", "#C6EFCE", "#FFC7CE", "#F2F2F2"))
    ss = getSampleStyleSheet()
    tit = ParagraphStyle("t", parent=ss["Title"], textColor=azul, fontSize=17, spaceAfter=2)
    sub = ParagraphStyle("s", parent=ss["Normal"], textColor=colors.grey, fontSize=9, alignment=1, spaceAfter=10)
    h = ParagraphStyle("h", parent=ss["Heading2"], textColor=azul, fontSize=12, spaceBefore=10, spaceAfter=5)
    n = ParagraphStyle("n", parent=ss["Normal"], fontSize=9.5, leading=13)
    c = ParagraphStyle("c", parent=n, fontSize=8, leading=10)
    cb = ParagraphStyle("cb", parent=c, fontName="Helvetica-Bold", textColor=colors.white)

    def tabla(filas, anchos, colores=None):
        t = Table([[Paragraph(str(x), cb if i == 0 else c) for x in f] for i, f in enumerate(filas)],
                  colWidths=anchos, repeatRows=1)
        st = [("BACKGROUND", (0, 0), (-1, 0), azul), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BFBFBF")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        st += colores or []
        t.setStyle(TableStyle(st))
        return t

    def num(v, fmt="{:.1f}"):
        try:
            return "" if v is None or pd.isna(v) else fmt.format(v)
        except (TypeError, ValueError):
            return ""

    ok_df = "PASA" in df
    aprob = df[df["PASA"] == True] if ok_df else df.iloc[0:0]  # noqa: E712
    orden_nivel = {"Premium": 0, "Sólida": 1, "Especulativa": 2}
    if len(aprob) and "Nivel" in aprob:
        aprob = aprob.assign(_o=aprob["Nivel"].map(orden_nivel).fillna(3)).sort_values(["_o", "Ticker"])
    color_nivel = {"Premium": colors.HexColor("#FFE699"), "Sólida": colors.HexColor("#DDEBF7"),
                   "Especulativa": colors.HexColor("#EDEDED")}
    niveles = globals().get("NIVELES", {})
    nivel_de = lambda t: niveles.get(t, {}).get("Nivel", "")
    story = [Paragraph(f"Screener CEDEARs · {date.today().strftime('%d/%m/%Y')}", tit),
             Paragraph(f"{len(df)} acciones analizadas · Datos de Yahoo Finance al último cierre", sub)]
    if ejemplo:
        banda = Table([[Paragraph("<b>EJEMPLO CON DATOS ILUSTRATIVOS</b> — muestra cómo se ve el resumen un día "
                                  "con señales y operaciones abiertas. No son datos reales.", n)]], colWidths=[17 * cm])
        banda.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF2CC")),
                                   ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#BF9000")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [banda, Spacer(1, 6)]
    en_cartera = set(abiertas["Ticker"]) if abiertas is not None and len(abiertas) else set()

    # Estado del mercado
    m = globals().get("MERCADO")
    if m and m[1]:
        txt = (f"<b>Mercado:</b> S&amp;P 500 (SPY) en {m[1]:,.0f} vs. media de 200 días {m[2]:,.0f} → "
               + ("<b>ARRIBA: se pueden tomar señales.</b>" if m[0] else "<b>ABAJO: no tomar señales nuevas.</b>"))
        caja = Table([[Paragraph(txt, n)]], colWidths=[17 * cm])
        caja.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), verde if m[0] else rojo),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story += [caja, Spacer(1, 6)]

    # Acciones que pasan cada filtro
    corto = {"Consolidación": "Consolid.", "Corrección": "Correc.", "Volumen": "Vol.", "Mercado": "Merc."}
    nf = len(NOMBRES_FILTROS)
    filas = [["Filtro"] + [corto.get(x, x) for x in NOMBRES_FILTROS.values()]]
    fila = ["Pasan"]
    for f, nombre in NOMBRES_FILTROS.items():
        col = "✔ " + nombre
        k = int((df[col] == True).sum()) if col in df else 0  # noqa: E712
        fila.append(f"{k} de {len(df)}" + ("" if activos[f] else " (apag.)"))
    filas.append(fila)
    story += [Paragraph("Acciones que pasan cada filtro", h), tabla(filas, [2.2 * cm] + [14.8 / nf * cm] * nf)]

    # Señales de entrada
    story.append(Paragraph(f"Señales de entrada de hoy: {len(aprob)}", h))
    if len(aprob):
        filas = [["Ticker", "Nivel", "Nombre", "Precio", "Caída desde máx.", "Beta", "P/E", "Aviso / acción"]]
        colores = []
        for i, (_, r) in enumerate(aprob.iterrows(), start=1):
            nv = r.get("Nivel", "") or ""
            if nv in color_nivel:
                colores.append(("BACKGROUND", (1, i), (1, i), color_nivel[nv]))
            aviso = r.get("Aviso", "") or ""
            if r["Ticker"] in en_cartera:
                accion, col = "Ya en cartera: no comprar", gris
            elif aviso:
                accion, col = aviso, colors.HexColor("#FFF2CC")
            else:
                accion, col = "<b>COMPRAR</b>", verde
            colores.append(("BACKGROUND", (7, i), (7, i), col))
            filas.append([f"<b>{r['Ticker']}</b>", f"<b>{nv}</b>" if nv == "Premium" else nv,
                          str(r.get("Nombre", ""))[:22], num(r.get("Precio"), "{:,.2f}"),
                          num(r.get("Caída desde máx. %"), "{:.0f}%"), num(r.get("Beta"), "{:.2f}"), num(r.get("P/E")), accion])
        story.append(tabla(filas, [1.4 * cm, 2.4 * cm, 2.9 * cm, 1.6 * cm, 1.7 * cm, 1.1 * cm, 1.2 * cm, 4.7 * cm], colores))
        story.append(Paragraph("Nivel de calidad (solo informativo): Premium = 20 mejores por tamaño, ROE y margen; "
                               "Sólida = siguientes 50; Especulativa = resto. No está probado que cambie el resultado.",
                               ParagraphStyle("nv", parent=n, fontSize=7.5, textColor=colors.grey, spaceBefore=3)))
    else:
        story.append(Paragraph("Hoy ninguna acción cumple todos los filtros.", n))

    # Operaciones abiertas
    titulo_ab = "Operaciones abiertas" + (" (tu cartera)" if origen == "cartera" else " (según el sistema)")
    story.append(Paragraph(titulo_ab, h))
    if abiertas is not None and len(abiertas):
        filas = [["Ticker", "Nivel", "Entrada", "Precio entrada", "Precio hoy", "Result.", "vs S&amp;P", "Vender el", "Estado"]]
        colores = []
        for i, (_, r) in enumerate(abiertas.iterrows(), start=1):
            res, vs, rest = r["Resultado %"], r.get("vs S&P %"), int(r["Ruedas restantes"])
            nv = nivel_de(r["Ticker"])
            if nv in color_nivel:
                colores.append(("BACKGROUND", (1, i), (1, i), color_nivel[nv]))
            if rest <= 0:
                estado, col = "<b>VENDER HOY</b>", rojo
            elif rest <= 5:
                estado, col = f"Vender en {rest} ruedas", colors.HexColor("#FFF2CC")
            else:
                estado, col = f"Faltan {rest} ruedas", None
            if col is not None:
                colores.append(("BACKGROUND", (8, i), (8, i), col))
            filas.append([f"<b>{r['Ticker']}</b>", nv, r["Entrada"].strftime("%d/%m/%Y"), num(r["Precio entrada"], "{:,.2f}"),
                          num(r["Precio actual"], "{:,.2f}"),
                          f"<font color='{'#2E7D32' if res >= 0 else '#C00000'}'><b>{res:+.1f}%</b></font>",
                          num(vs, "{:+.1f}%"), r["Vender el"].strftime("%d/%m/%Y"), estado])
        story.append(tabla(filas, [1.3 * cm, 2.4 * cm, 1.9 * cm, 1.8 * cm, 1.7 * cm, 1.6 * cm, 1.5 * cm, 1.9 * cm, 2.9 * cm], colores))
        prom = abiertas["Resultado %"].mean()
        story.append(Paragraph(f"{len(abiertas)} operaciones abiertas · resultado promedio {prom:+.1f}% · "
                               f"con USD 10.000 en cada una: {abiertas['Resultado %'].sum() * 100:+,.0f} USD",
                               ParagraphStyle("x", parent=n, fontSize=8.5, textColor=colors.grey, spaceBefore=3)))
    else:
        story.append(Paragraph("No hay operaciones abiertas.", n))

    if cerradas is not None and len(cerradas):
        story.append(Paragraph("Cerradas en los últimos 30 días", h))
        filas = [["Ticker", "Entrada", "Salida", "Resultado", "S&amp;P mismo período", "vs S&amp;P"]]
        for _, r in cerradas.iterrows():
            res = r["Resultado %"]
            filas.append([f"<b>{r['Ticker']}</b>", r["Entrada"].strftime("%d/%m/%Y"), r["Vender el"].strftime("%d/%m/%Y"),
                          f"<font color='{'#2E7D32' if res >= 0 else '#C00000'}'><b>{res:+.1f}%</b></font>",
                          num(r.get("S&P mismo período %"), "{:+.1f}%"), num(r.get("vs S&P %"), "{:+.1f}%")])
        story.append(tabla(filas, [2 * cm, 2.8 * cm, 2.8 * cm, 2.6 * cm, 3.6 * cm, 3.2 * cm]))

    # Tablero: las 30 más cercanas a dar señal (el detalle de todas está en el Excel)
    story.append(Paragraph("Tablero: las 30 acciones más cercanas a dar señal", h))
    cols_f = ["✔ " + x for x in NOMBRES_FILTROS.values()]
    filas = [["Ticker", "Nivel"] + [corto.get(x, x) for x in NOMBRES_FILTROS.values()] + ["Caída", "Fallas"]]
    colores = []
    base_t = df[df["Filtros que falla"].notna()].head(30) if "Filtros que falla" in df else df.head(30)
    for i, (_, r) in enumerate(base_t.iterrows(), start=1):
        nv = r.get("Nivel", "") or ""
        if nv in color_nivel:
            colores.append(("BACKGROUND", (1, i), (1, i), color_nivel[nv]))
        fila = [f"<b>{r['Ticker']}</b>", nv]
        for j, col in enumerate(cols_f, start=2):
            v = r.get(col)
            fila.append("Sí" if v is True else "No" if v is False else "")
            f_key = list(NOMBRES_FILTROS)[j - 2]
            col_bg = gris if not activos[f_key] else (verde if v is True else rojo if v is False else gris)
            colores.append(("BACKGROUND", (j, i), (j, i), col_bg))
        fl = r.get("Filtros que falla")
        fila += [num(r.get("Caída desde máx. %"), "{:.0f}%"), "PASA" if fl == 0 else num(fl, "{:.0f}")]
        if fl == 0:
            colores.append(("BACKGROUND", (nf + 3, i), (nf + 3, i), verde))
        filas.append(fila)
    story.append(tabla(filas, [1.4 * cm, 2.4 * cm] + [9.8 / nf * cm] * nf + [1.3 * cm, 1.3 * cm], colores))

    if origen == "sistema" and abiertas is not None:
        story.append(Paragraph("Las operaciones \"según el sistema\" son las que habría abierto la estrategia. Para "
                               "seguir tus compras reales, cargalas en un archivo cartera.csv (Ticker,Fecha,Precio).",
                               ParagraphStyle("y", parent=n, fontSize=7.5, textColor=colors.grey, spaceBefore=3)))
    story += [Spacer(1, 8), Paragraph(
        "<b>Reglas:</b> no comprar si la acción ya está en cartera · si hay aviso de balance, esperar a que "
        "presente · vender a los 6 meses. <i>Análisis con fines educativos, no es recomendación de inversión.</i>",
        ParagraphStyle("r", parent=n, fontSize=8, textColor=colors.grey))]

    SimpleDocTemplate(ruta_pdf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.5 * cm, title="Screener CEDEARs").build(story)


def enviar_mail(df, ruta, ruta_pdf=None, abiertas=None):
    """Envía el Excel por Gmail. Usa estas variables de entorno:
    GMAIL_USER (cuenta que envía), GMAIL_APP_PASSWORD (contraseña de
    aplicación de Google) y MAIL_TO (destinatarios separados por coma)."""
    import os
    import smtplib
    from email.message import EmailMessage

    usuario = os.environ["GMAIL_USER"]
    clave = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    destinos = [d.strip() for d in os.environ.get("MAIL_TO", usuario).split(",") if d.strip()]

    lineas = [f"Screener del {date.today().strftime('%d/%m/%Y')} - {len(df)} acciones analizadas", ""]
    m = globals().get("MERCADO")
    if m and m[1]:
        lineas += [f"Mercado: S&P {m[1]:,.0f} vs media de 200 días {m[2]:,.0f} -> "
                   + ("arriba, se pueden tomar señales." if m[0] else "ABAJO: no tomar señales nuevas."), ""]
    lineas.append("Acciones que pasan cada filtro:")
    for f, n in NOMBRES_FILTROS.items():
        col = "✔ " + n
        pasan = int((df[col] == True).sum()) if col in df else 0  # noqa: E712
        lineas.append(f"  - {n}: {pasan}" + ("" if FILTROS_ACTIVOS[f] else " (apagado)"))
    lineas.append("")
    aprob = df[df["PASA"] == True] if "PASA" in df else df.iloc[0:0]  # noqa: E712
    if len(aprob):
        lineas.append("PASAN TODOS LOS FILTROS:")
        for _, r in aprob.iterrows():
            extra = f"  <- {r['Aviso']}" if isinstance(r.get("Aviso"), str) and r["Aviso"] else ""
            nv = r.get("Nivel", "") or ""
            beta_txt = f"beta {r['Beta']:.2f}" if pd.notna(r.get("Beta")) else "beta s/d"
            lineas.append(f"  - {ESTRELLAS.get(nv, '')} {r['Ticker']} [{nv}] (caída {r['Caída desde máx. %']:.0f}%, {beta_txt}){extra}")
        lineas.append("Recordá: no comprar si la acción ya está en cartera. Regla de salida: vender a los 6 meses.")
    else:
        lineas.append("Hoy ninguna acción pasa todos los filtros.")
    if "Filtros que falla" in df:
        cerca = df[(df["Filtros que falla"] >= 1)].head(5)
        if len(cerca):
            lineas += ["", "Las más cercanas:"]
            for _, r in cerca.iterrows():
                lineas.append(f"  - {r['Ticker']}: falla en {r['Falla en']}")
    if abiertas is not None and len(abiertas):
        vender = abiertas[abiertas["Ruedas restantes"] <= 0]
        if len(vender):
            lineas += ["", "VENDER HOY: " + ", ".join(vender["Ticker"])]
        lineas += ["", f"Operaciones abiertas: {len(abiertas)}"]
        for _, r in abiertas.iterrows():
            lineas.append(f"  - {r['Ticker']}: {r['Resultado %']:+.1f}% desde el {r['Entrada'].strftime('%d/%m/%Y')}, "
                          f"vender el {r['Vender el'].strftime('%d/%m/%Y')}")
    lineas += ["", "Adjuntos: el resumen en PDF y el detalle completo en Excel."]

    msg = EmailMessage()
    asunto = f"{len(aprob)} señales" if len(aprob) else "sin señales"
    if abiertas is not None and len(abiertas) and (abiertas["Ruedas restantes"] <= 0).any():
        asunto += " · VENDER: " + ", ".join(abiertas.loc[abiertas["Ruedas restantes"] <= 0, "Ticker"])
    msg["Subject"] = f"Screener CEDEARs {date.today().strftime('%d/%m/%Y')}: {asunto}"
    msg["From"] = usuario
    msg["To"] = ", ".join(destinos)
    msg.set_content("\n".join(lineas))
    with open(ruta, "rb") as fh:
        msg.add_attachment(
            fh.read(), filename=ruta, maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if ruta_pdf and os.path.exists(ruta_pdf):
        with open(ruta_pdf, "rb") as fh:
            msg.add_attachment(fh.read(), filename=ruta_pdf, maintype="application", subtype="pdf")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(usuario, clave)
        s.send_message(msg)
    print(f"Mail enviado a: {', '.join(destinos)}")


def main():
    if yf is None:
        sys.exit("Falta la librería yfinance. Instalala con:\n    pip install yfinance pandas openpyxl")

    # (ignora argumentos internos que agregan Jupyter / Google Colab)
    args = [a for a in sys.argv[1:] if not a.startswith("-") and not a.endswith(".json")]
    tickers = [t.upper() for t in args] or LISTA_TICKERS
    precios = descargar_precios(tickers)
    if not precios:
        sys.exit("No se pudieron descargar precios de Yahoo Finance. Probá de nuevo más tarde.")
    fundamentales = descargar_fundamentales(tickers)
    global MERCADO, NIVELES
    NIVELES = clasificar_niveles(fundamentales)
    MERCADO = estado_mercado()
    df = procesar(tickers, precios, fundamentales, mercado_ok=MERCADO[0])

    ruta = f"screener_{date.today().isoformat()}.xlsx"
    exportar_excel(df, ruta)

    print("\n" + "=" * 50)
    ok, px_spy, media = MERCADO
    if px_spy:
        print(f"  Mercado: S&P {px_spy:,.0f} vs media 200 {media:,.0f} -> "
              + ("OK, se puede comprar" if ok else "ABAJO de la media: no comprar"))
    for f, n in NOMBRES_FILTROS.items():
        col = "✔ " + n
        pasan = int((df[col] == True).sum()) if col in df else 0
        print(f"  {n:<14} pasan {pasan:>3} de {len(df)}" + ("" if FILTROS_ACTIVOS[f] else "  (apagado)"))
    aprob = df[df["PASA"] == True] if "PASA" in df else df.iloc[0:0]  # noqa: E712
    print("=" * 50)
    print(f"  PASAN TODO: {', '.join(aprob['Ticker']) if len(aprob) else 'ninguna'}")
    print(f"\nExcel guardado en: {ruta}")

    print("Revisando operaciones abiertas...")
    abiertas, cerradas, origen = seguimiento(precios, fundamentales)
    if len(abiertas) or len(cerradas):
        with pd.ExcelWriter(ruta, engine="openpyxl", mode="a") as xw:
            if len(abiertas):
                abiertas.to_excel(xw, sheet_name="Operaciones abiertas", index=False)
            if len(cerradas):
                cerradas.to_excel(xw, sheet_name="Cerradas recientes", index=False)
    for _, r in abiertas.iterrows():
        marca = "  <- VENDER HOY" if r["Ruedas restantes"] <= 0 else ""
        print(f"  {r['Ticker']:<6}{r['Resultado %']:+6.1f}%  vender el {r['Vender el']}{marca}")

    ruta_pdf = f"screener_{date.today().isoformat()}.pdf"
    try:
        generar_pdf(df, ruta_pdf, abiertas=abiertas, cerradas=cerradas, origen=origen)
        print(f"PDF de resumen guardado en: {ruta_pdf}")
    except ImportError:
        ruta_pdf = None
        print("(Para generar el PDF de resumen instalá reportlab: pip install reportlab)")

    import os
    if os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"):
        enviar_mail(df, ruta, ruta_pdf, abiertas)


if __name__ == "__main__":
    main()
    if sys.platform.startswith("win") and len(sys.argv) == 1:
        input("\nPresioná Enter para cerrar...")
