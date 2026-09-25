"""
MOMENTUM RESIDUAL - mail mensual
================================
Corre el primer día hábil de cada mes y manda por mail qué vender, qué comprar y
qué mantener, con un PDF de resumen y un Excel con el detalle.

No necesita saber qué tenés: lleva una "cartera según el sistema" que arranca en
MOMENTUM_INICIO y sigue las reglas. Los montos se muestran para una cartera de
referencia (MOMENTUM_CAPITAL, por defecto USD 10.000) y en % de la cartera, para
que los escales a tu caso.

Reglas:
  * Ranking el último día hábil de cada mes: para cada acción se estima con 36 meses
    cuánto de su movimiento explica el S&P; el puntaje es la suba "propia" de los
    últimos 12 meses (sin el último) dividida por su variabilidad.
  * Solo acciones con más de USD 20 millones operados por día.
  * 10 acciones. Se vende una acción solo cuando sale del top 30.
  * Cada compra nueva recibe el 10% de la cartera; el sobrante completa las más chicas.
  * Si una acción pasa del 20% de la cartera, se recorta a 12,5%.

Variables de entorno (GitHub → Settings → Secrets and variables → Actions):
  GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_TO  (secretos, los mismos del screener)
  MOMENTUM_CAPITAL (variable opcional): tamaño aproximado de tu cartera de momentum en USD
  MOMENTUM_INICIO  (variable opcional): desde cuándo se lleva la cartera del sistema (AAAA-MM-DD)
  FORZAR=1: manda el mail aunque no sea el primer día hábil (queda marcado como ANTICIPO)
"""
import os
import sys
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

TOP = 10
BUFFER = 30
VOL_MIN_USD = 20_000_000
COSTO = 0.005
TOPE = 0.20
RECORTE_A = 0.125
MESES_REGRESION = 36
INICIO = os.environ.get("MOMENTUM_INICIO") or "2026-09-25"   # la cartera del sistema arranca acá
CAPITAL_REF = float(os.environ.get("MOMENTUM_CAPITAL") or 10_000)

# Acciones con CEDEAR en BYMA (verificado contra el listado oficial de BYMA de feb-2026 y el de
# Rankia de sep-2026). Formato: "ticker en Yahoo": ("nombre de la empresa", "código del CEDEAR en BYMA").
# Se sacaron 15 que NO tienen CEDEAR: UPS, NXPI, INTU, BLK, MCO, LOW, EXPE, MAR, REGN, AA, CMCSA,
# DUK, SO, AMT, SPG. Barrick cambió su símbolo de GOLD a B en 2025.
CEDEARS = {
    # Tecnología y semiconductores
    "AAPL": ("Apple", "AAPL"), "MSFT": ("Microsoft", "MSFT"), "GOOGL": ("Alphabet, Google", "GOOGL"),
    "AMZN": ("Amazon", "AMZN"), "META": ("Meta Platforms, Facebook", "META"), "NVDA": ("NVIDIA", "NVDA"),
    "TSLA": ("Tesla", "TSLA"), "NFLX": ("Netflix", "NFLX"), "AMD": ("Advanced Micro Devices", "AMD"),
    "AVGO": ("Broadcom", "AVGO"), "CRM": ("Salesforce", "CRM"), "ADBE": ("Adobe", "ADBE"),
    "ORCL": ("Oracle", "ORCL"), "IBM": ("IBM", "IBM"), "INTC": ("Intel", "INTC"), "QCOM": ("Qualcomm", "QCOM"),
    "TXN": ("Texas Instruments", "TXN"), "MU": ("Micron Technology", "MU"), "CSCO": ("Cisco Systems", "CSCO"),
    "ADI": ("Analog Devices", "ADI"), "AMAT": ("Applied Materials", "AMAT"), "LRCX": ("Lam Research", "LRCX"),
    "KLAC": ("KLA Corporation", "KLAC"), "TSM": ("Taiwan Semiconductor, TSMC", "TSM"),
    "ASML": ("ASML Holding", "ASML"), "SAP": ("SAP", "SAP"), "NOW": ("ServiceNow", "NOW"),
    "ACN": ("Accenture", "ACN"), "HPQ": ("HP Inc.", "HPQ"), "DELL": ("Dell Technologies", "DELL"),
    "SHOP": ("Shopify", "SHOP"), "SPOT": ("Spotify", "SPOT"), "SNAP": ("Snap, Snapchat", "SNAP"),
    "PINS": ("Pinterest", "PINS"), "ROKU": ("Roku", "ROKU"), "ZM": ("Zoom Communications", "ZM"),
    "DOCU": ("DocuSign", "DOCU"), "TWLO": ("Twilio", "TWLO"), "UBER": ("Uber Technologies", "UBER"),
    "ABNB": ("Airbnb", "ABNB"), "PLTR": ("Palantir Technologies", "PLTR"), "SNOW": ("Snowflake", "SNOW"),
    "COIN": ("Coinbase", "COIN"), "XYZ": ("Block, ex Square", "XYZ"), "PYPL": ("PayPal", "PYPL"),
    "EBAY": ("eBay", "EBAY"), "ETSY": ("Etsy", "ETSY"), "SONY": ("Sony Group", "SONY"),
    "GLOB": ("Globant", "GLOB"), "MELI": ("MercadoLibre", "MELI"), "BABA": ("Alibaba", "BABA"),
    "JD": ("JD.com", "JD"), "BIDU": ("Baidu", "BIDU"), "NIO": ("NIO", "NIO"),
    # Finanzas
    "V": ("Visa", "V"), "MA": ("Mastercard", "MA"), "AXP": ("American Express", "AXP"),
    "JPM": ("JPMorgan Chase", "JPM"), "BAC": ("Bank of America", "BA.C"), "C": ("Citigroup", "C"),
    "GS": ("Goldman Sachs", "GS"), "MS": ("Morgan Stanley", "MS"), "WFC": ("Wells Fargo", "WFC"),
    "USB": ("U.S. Bancorp", "USB"), "SCHW": ("Charles Schwab", "SCHW"), "SPGI": ("S&P Global", "SPGI"),
    "BK": ("Bank of New York Mellon", "BK"), "BRK-B": ("Berkshire Hathaway", "BRKB"),
    # Consumo
    "KO": ("Coca-Cola", "KO"), "PEP": ("PepsiCo", "PEP"), "MCD": ("McDonald's", "MCD"),
    "SBUX": ("Starbucks", "SBUX"), "NKE": ("Nike", "NKE"), "DIS": ("Walt Disney", "DISN"),
    "HD": ("Home Depot", "HD"), "WMT": ("Walmart", "WMT"), "COST": ("Costco", "COST"), "TGT": ("Target", "TGT"),
    "PG": ("Procter & Gamble", "PG"), "CL": ("Colgate-Palmolive", "CL"), "KMB": ("Kimberly-Clark", "KMB"),
    "MO": ("Altria", "MO"), "PM": ("Philip Morris", "PM"), "BKNG": ("Booking Holdings", "BKNG"),
    "F": ("Ford Motor", "F"), "GM": ("General Motors", "GM"), "TM": ("Toyota Motor", "TM"),
    "HMC": ("Honda Motor", "HMC"), "ARCO": ("Arcos Dorados", "ARCO"),
    # Salud
    "PFE": ("Pfizer", "PFE"), "JNJ": ("Johnson & Johnson", "JNJ"), "MRK": ("Merck & Co.", "MRK"),
    "ABBV": ("AbbVie", "ABBV"), "LLY": ("Eli Lilly", "LLY"), "BMY": ("Bristol-Myers Squibb", "BMY"),
    "AMGN": ("Amgen", "AMGN"), "GILD": ("Gilead Sciences", "GILD"), "UNH": ("UnitedHealth Group", "UNH"),
    "CVS": ("CVS Health", "CVS"), "MDT": ("Medtronic", "MDT"), "ABT": ("Abbott Laboratories", "ABT"),
    "TMO": ("Thermo Fisher Scientific", "TMO"), "DHR": ("Danaher", "DHR"), "BIIB": ("Biogen", "BIIB"),
    "VRTX": ("Vertex Pharmaceuticals", "VRTX"), "MRNA": ("Moderna", "MRNA"), "NVS": ("Novartis", "NVS"),
    "AZN": ("AstraZeneca", "AZN"), "GSK": ("GSK", "GSK"),
    # Energía y materiales
    "XOM": ("Exxon Mobil", "XOM"), "CVX": ("Chevron", "CVX"), "COP": ("ConocoPhillips", "COP"),
    "OXY": ("Occidental Petroleum", "OXY"), "SLB": ("SLB, Schlumberger", "SLB"), "HAL": ("Halliburton", "HAL"),
    "PBR": ("Petrobras", "PBR"), "BP": ("BP", "BP"), "SHEL": ("Shell", "SHEL"), "VALE": ("Vale", "VALE"),
    "RIO": ("Rio Tinto", "RIO"), "BHP": ("BHP Group", "BHP"), "NEM": ("Newmont", "NEM"),
    "B": ("Barrick Mining, ex Barrick Gold", "B"), "FCX": ("Freeport-McMoRan", "FCX"), "DOW": ("Dow Inc.", "DOW"),
    # Industria, telecomunicaciones y servicios
    "CAT": ("Caterpillar", "CAT"), "DE": ("Deere & Company, John Deere", "DE"), "BA": ("Boeing", "BA"),
    "GE": ("GE Aerospace", "GE"), "HON": ("Honeywell", "HON"), "MMM": ("3M", "MMM"),
    "LMT": ("Lockheed Martin", "LMT"), "RTX": ("RTX, Raytheon", "RTX"), "FDX": ("FedEx", "FDX"),
    "T": ("AT&T", "T"), "VZ": ("Verizon", "VZ"), "TMUS": ("T-Mobile US", "TMUS"),
    "NEE": ("NextEra Energy", "NEE"), "ADP": ("Automatic Data Processing", "ADP"),
}

# Si alguna acción no se puede operar, agregala en la variable de GitHub MOMENTUM_EXCLUIR (separadas por coma).
_EXCLUIR = {t.strip().upper() for t in (os.environ.get("MOMENTUM_EXCLUIR") or "").split(",") if t.strip()}
TICKERS = sorted(t for t in CEDEARS if t not in _EXCLUIR)


def nombre(t):
    return CEDEARS.get(t, (t, t))[0]


def cedear(t):
    return CEDEARS.get(t, (t, t))[1]


def con_nombre(t):
    """'BAC (Bank of America, CEDEAR BA.C)' para textos."""
    extra = f", CEDEAR {cedear(t)}" if cedear(t) != t else ""
    return f"{t} ({nombre(t)}{extra})"


SECTOR = {}
for _s, _ts in {
    "Semiconductores": "NVDA AMD AVGO INTC QCOM TXN MU ADI AMAT LRCX KLAC NXPI TSM ASML",
    "Tecnología": "AAPL MSFT CRM ADBE ORCL IBM CSCO SAP INTU NOW ACN HPQ DELL SHOP ZM DOCU TWLO PLTR SNOW SONY GLOB",
    "Comunicación": "GOOGL META NFLX DIS SNAP PINS ROKU SPOT T VZ TMUS CMCSA BIDU",
    "Consumo discrecional": "AMZN TSLA MELI BABA JD EBAY ETSY UBER ABNB NKE SBUX MCD HD LOW TGT BKNG EXPE MAR F GM TM HMC ARCO NIO",
    "Financiero": "V MA AXP JPM BAC C GS MS WFC USB SCHW BLK SPGI MCO BK BRK-B PYPL COIN XYZ",
    "Consumo básico": "KO PEP WMT COST PG CL KMB MO PM",
    "Salud": "PFE JNJ MRK ABBV LLY BMY AMGN GILD UNH CVS MDT ABT TMO DHR BIIB REGN VRTX MRNA NVS AZN GSK",
    "Energía": "XOM CVX COP OXY SLB HAL PBR BP SHEL",
    "Materiales y minería": "VALE RIO BHP NEM B FCX AA DOW",
    "Industria": "CAT DE BA GE HON MMM LMT RTX UPS FDX ADP",
    "Servicios públicos": "NEE DUK SO",
    "Inmobiliario": "AMT SPG",
}.items():
    for _t in _ts.split():
        SECTOR[_t] = _s

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def hoy_ar():
    fijo = os.environ.get("HOY")          # solo para pruebas
    if fijo:
        return date.fromisoformat(fijo)
    return (pd.Timestamp.utcnow() - pd.Timedelta(hours=3)).date()


def es_primer_dia_habil(d):
    return d.weekday() < 5 and all(date(d.year, d.month, k).weekday() >= 5 for k in range(1, d.day))


# ============================================================================ datos
def descargar():
    inicio_datos = (pd.Timestamp(INICIO) - pd.DateOffset(years=4)).strftime("%Y-%m-%d")
    for intento in range(3):
        try:
            datos = yf.download(TICKERS + ["SPY"], start=inicio_datos, interval="1d", auto_adjust=True,
                                group_by="ticker", threads=True, progress=False)
            break
        except Exception as e:          # noqa: BLE001
            print("Reintentando descarga:", e)
            time.sleep(20)
    close, volume = {}, {}
    for t in TICKERS + ["SPY"]:
        try:
            df = datos[t] if isinstance(datos.columns, pd.MultiIndex) else datos
            df = df[["Close", "Volume"]].dropna(subset=["Close"])
            if len(df):
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                close[t], volume[t] = df["Close"], df["Volume"]
        except KeyError:
            pass
    if "SPY" not in close:
        raise RuntimeError("No se pudieron bajar los precios del S&P (SPY).")
    idx = close["SPY"].index
    px = pd.DataFrame(close).reindex(idx).ffill()
    vo = pd.DataFrame(volume).reindex(idx)
    return px, vo


class Motor:
    def __init__(self, px, vo):
        self.px, self.idx = px, px.index
        self.acc = [t for t in TICKERS if t in px.columns]
        self.dvol = (px[self.acc] * vo[self.acc]).rolling(30, min_periods=10).mean()
        self.vol252 = px[self.acc].pct_change().rolling(252, min_periods=200).std() * np.sqrt(252)
        per = self.idx.to_period("M")
        pm = px[self.acc].groupby(per).last()
        self.rm = pm.pct_change()
        self.rs = px["SPY"].groupby(per).last().pct_change()
        self.mes_pos = {p: j for j, p in enumerate(pm.index)}
        self.pos = {pd.Timestamp(d): k for k, d in enumerate(self.idx)}
        self._cache = {}

    def ranking(self, k):
        """DataFrame ordenado por puntaje de momentum residual con datos hasta el cierre k."""
        if k in self._cache:
            return self._cache[k]
        j = self.mes_pos[self.idx[k].to_period("M")]
        Y = self.rm.iloc[max(0, j - MESES_REGRESION + 1): j + 1].values
        x = self.rs.iloc[max(0, j - MESES_REGRESION + 1): j + 1].values
        sc = {}
        if len(x) >= 24:
            for c, t in enumerate(self.acc):
                y = Y[:, c]
                ok = ~np.isnan(y) & ~np.isnan(x)
                if ok.sum() < 24 or np.isnan(y[-12:-1]).any():
                    continue
                b, a = np.polyfit(x[ok], y[ok], 1)
                e = y - a - b * x
                sd = np.nanstd(e[ok], ddof=1)
                if sd > 0:
                    sc[t] = np.nansum(e[-12:-1]) / sd
        sc = pd.Series(sc, dtype=float)
        liq = self.dvol.iloc[k].reindex(sc.index) >= VOL_MIN_USD
        sc = sc[liq]
        r = self.px.iloc[k - 21][sc.index] / self.px.iloc[k - 252][sc.index] - 1
        rk = pd.DataFrame({"Puntaje": sc, "Suba 12-1 %": r * 100,
                           "Volatilidad %": self.vol252.iloc[k].reindex(sc.index) * 100}).sort_values("Puntaje", ascending=False)
        rk["Puesto"] = range(1, len(rk) + 1)
        rk["Sector"] = [SECTOR.get(t, "Otros") for t in rk.index]
        self._cache[k] = rk
        return rk


def aplicar_reglas(hold, caja, rk, precios, fecha, ejecutar=True):
    """Aplica las reglas del mes. hold: {ticker: {"cant", "costo", "compra"}}. Devuelve (hold, caja, órdenes, cerradas)."""
    hold = {t: dict(h) for t, h in hold.items()}
    puesto = rk["Puesto"].to_dict()
    top_b = set(rk.index[:BUFFER])
    val = lambda t: hold[t]["cant"] * precios[t]
    ordenes, cerradas = [], []
    for t in [t for t in hold if t not in top_b]:
        h = hold.pop(t)
        v = h["cant"] * precios[t]
        caja += v * (1 - COSTO)
        res = (v * (1 - COSTO) / h["costo"] - 1) * 100
        ordenes.append({"Orden": "VENDER", "Acción": t, "Puesto": puesto.get(t), "Monto": v, "Resultado %": res,
                        "Motivo": f"Salió del top {BUFFER}" + (f" (puesto {puesto[t]})" if t in puesto else " (sin datos suficientes)")})
        cerradas.append({"Acción": t, "Sector": SECTOR.get(t, "Otros"), "Compra": h["compra"], "Venta": fecha,
                         "Invertido": h["costo"], "Cobrado": v * (1 - COSTO), "Resultado %": res})
    total = caja + sum(val(t) for t in hold)
    for t in list(hold):
        if total > 0 and val(t) / total > TOPE:
            v0 = val(t)
            vender = v0 - total * RECORTE_A
            f = vender / v0
            caja += vender * (1 - COSTO)
            hold[t]["cant"] *= (1 - f)
            hold[t]["costo"] *= (1 - f)
            ordenes.append({"Orden": "RECORTAR", "Acción": t, "Puesto": puesto.get(t), "Monto": vender, "Resultado %": None,
                            "Motivo": f"Pesaba {v0 / total:.0%}; baja a {RECORTE_A:.1%}".replace(".", ",")})
    obj = total / TOP
    inicial = len(hold) == 0
    nuevas = [t for t in rk.index if t not in hold][:max(0, TOP - len(hold))]
    m_cada = (obj if caja >= obj * len(nuevas) else caja / len(nuevas)) if nuevas else 0
    for t in nuevas:
        m = min(m_cada, caja)
        if m <= 0:
            break
        hold[t] = {"cant": m * (1 - COSTO) / precios[t], "costo": m, "compra": fecha}
        caja -= m
        ordenes.append({"Orden": "COMPRAR", "Acción": t, "Puesto": puesto.get(t), "Monto": m, "Resultado %": None,
                        "Motivo": "Compra inicial: 10% de la cartera" if inicial else "Mejor del ranking que no está en cartera"})
    sumas = {}
    while caja > 0.5:
        chicas = sorted([t for t in hold if val(t) < obj - 0.5], key=val)
        if not chicas:
            break
        t = chicas[0]
        m = min(obj - val(t), caja)
        hold[t]["cant"] += m * (1 - COSTO) / precios[t]
        hold[t]["costo"] += m
        caja -= m
        sumas[t] = sumas.get(t, 0) + m
    for t, m in sumas.items():
        ordenes.append({"Orden": "SUMAR", "Acción": t, "Puesto": puesto.get(t), "Monto": m, "Resultado %": None,
                        "Motivo": "Posición chica: se completa hacia el 10%"})
    return hold, caja, ordenes, cerradas


def simular(motor):
    idx, px = motor.idx, motor.px
    dias = idx[idx >= pd.Timestamp(INICIO)]
    eventos = {}
    for _, g in pd.Series(dias, index=dias).groupby(dias.to_period("M")):
        d_op = pd.Timestamp(g.iloc[0])
        eventos[d_op] = motor.pos[d_op] - 1
    hold, caja = {}, float(CAPITAL_REF)
    serie, historial, cerradas = [], [], []
    if len(dias) == 0:                    # todavía no arrancó: la primera orden es la compra inicial
        d0 = pd.Timestamp(idx[-1])
        return hold, caja, pd.Series([caja], index=[d0]), pd.Series([caja], index=[d0]), \
            pd.DataFrame(), pd.DataFrame(), set()
    for d in dias:
        d = pd.Timestamp(d)
        k = motor.pos[d]
        if d in eventos:
            rk = motor.ranking(eventos[d])
            precios = px.iloc[k]
            hold, caja, ords, cer = aplicar_reglas(hold, caja, rk, precios, d)
            for o in ords:
                historial.append({"Mail": d.date(), **o})
            cerradas += cer
        serie.append(caja + sum(h["cant"] * px.iloc[k][t] for t, h in hold.items()))
    serie = pd.Series(serie, index=dias)
    spy = CAPITAL_REF * px["SPY"].loc[dias[0]:] / px["SPY"].loc[dias[0]]
    return hold, caja, serie, spy, pd.DataFrame(historial), pd.DataFrame(cerradas), set(eventos)


# ============================================================================ salidas
def usd(v):
    return "USD " + f"{v:,.0f}".replace(",", ".")


def pct(v, dec=1, signo=True):
    if v is None or pd.isna(v):
        return "—"
    return (f"{v:+.{dec}f}%" if signo else f"{v:.{dec}f}%").replace(".", ",")


def fecha_larga(d):
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def generar_pdf(ruta, ctx):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    serie, spy, cart, rk, ords = ctx["serie"], ctx["spy"], ctx["cartera"], ctx["rk"], ctx["ordenes"]
    fig, ax = plt.subplots(figsize=(8.2, 2.7), dpi=150)
    ax.plot(serie.index, serie.values, color="#1f5fa8", lw=2, label="Cartera según el sistema")
    ax.plot(spy.index, spy.values, color="#8a8a8a", lw=1.5, label="Mismo dinero en el S&P 500")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usd(v)))
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.tick_params(labelsize=7)
    ax.grid(axis="y", color="#eeeeee")
    fig.tight_layout(); fig.savefig("mom_evo.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.2, 2.4), dpi=150)
    pesos = cart["Peso %"].values
    ax.bar(cart["Acción"], pesos, color=["#1f5fa8" if w <= TOPE * 100 else "#c0392b" for w in pesos])
    ax.axhline(100 / TOP, color="#2e7d32", lw=1, ls="--")
    ax.axhline(TOPE * 100, color="#c0392b", lw=1, ls=":")
    ax.text(len(pesos) - 0.5, 100 / TOP + 0.4, "objetivo 10%", fontsize=7, color="#2e7d32", ha="right")
    ax.text(len(pesos) - 0.5, TOPE * 100 + 0.4, "tope 20%", fontsize=7, color="#c0392b", ha="right")
    ax.set_ylim(0, max(24, max(pesos) + 3) if len(pesos) else 24)
    ax.set_ylabel("% de la cartera", fontsize=8)
    ax.tick_params(labelsize=7.5)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig("mom_pesos.png"); plt.close(fig)

    AZUL = colors.HexColor("#1F3864"); GRIS = colors.HexColor("#F2F2F2"); CAJA = colors.HexColor("#EEF3FA")
    VER, ROJ, NAR, GRI = "#1e7b3a", "#b3261e", "#b76e00", "#555555"
    ss = getSampleStyleSheet()
    T = ParagraphStyle("t", parent=ss["Title"], textColor=AZUL, fontSize=18, leading=22, alignment=0, spaceAfter=0)
    S = ParagraphStyle("s", parent=ss["Normal"], textColor=colors.grey, fontSize=9, spaceAfter=8)
    H = ParagraphStyle("h", parent=ss["Heading2"], textColor=AZUL, fontSize=12.5, spaceBefore=10, spaceAfter=5)
    N = ParagraphStyle("n", parent=ss["Normal"], fontSize=9.5, leading=13, spaceAfter=4)
    B = ParagraphStyle("b", parent=N, leftIndent=12, bulletIndent=0, spaceAfter=2)
    C = ParagraphStyle("c", parent=N, fontSize=8.5, leading=10.5, spaceAfter=0)
    CB = ParagraphStyle("cb", parent=C, fontName="Helvetica-Bold", textColor=colors.white)
    K1 = ParagraphStyle("k1", parent=N, fontSize=8, textColor=colors.grey, alignment=1, spaceAfter=0)
    K2 = ParagraphStyle("k2", parent=N, fontSize=15, leading=18, fontName="Helvetica-Bold", alignment=1, spaceAfter=0)
    NOTA = ParagraphStyle("nota", parent=N, fontSize=7.5, leading=9.5, textColor=colors.grey)
    col = lambda c, s_: f"<font color='{c}'>{s_}</font>"
    b = lambda t_: Paragraph(t_, B, bulletText="•")
    pc = lambda v, d=1: "—" if v is None or pd.isna(v) else col(VER if v >= 0 else ROJ, pct(v, d))

    def lab(t_):
        extra = f" · CEDEAR <b>{cedear(t_)}</b>" if cedear(t_) != t_ else ""
        return f"<b>{t_}</b><br/><font size='7' color='#555555'>{nombre(t_)}{extra}</font>"

    def tabla(data, widths, fondos=None):
        rows = [[Paragraph(str(v), CB if i == 0 else C) for v in r] for i, r in enumerate(data)]
        t_ = Table(rows, colWidths=widths, repeatRows=1)
        st = [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for i in range(1, len(data)):
            if i % 2 == 0:
                st.append(("BACKGROUND", (0, i), (-1, i), GRIS))
        for i, c_ in (fondos or []):
            st.append(("BACKGROUND", (0, i), (-1, i), c_))
        t_.setStyle(TableStyle(st))
        return t_

    def kpis(items):
        t_ = Table([[Paragraph(a, K1) for a, _ in items], [Paragraph(v, K2) for _, v in items]],
                   colWidths=[17 * cm / len(items)] * len(items))
        t_.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CAJA), ("BOX", (0, 0), (-1, -1), 0.6, AZUL),
                                ("LINEAFTER", (0, 0), (-2, -1), 0.4, colors.HexColor("#C9D6EA")),
                                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        return t_

    hoy, modo = ctx["hoy"], ctx["modo"]
    mr = ctx["mes_ref"]
    titulo = f"Momentum residual · {MESES[mr.month - 1].capitalize()} {mr.year}" + (" (anticipo)" if modo == "ANTICIPO" else "")
    sub = (f"{fecha_larga(hoy).capitalize()} · ranking con el cierre del {ctx['cierre'].strftime('%d/%m/%Y')} · "
           + ("operar al cierre de hoy" if modo == "ORDEN" else
              f"<b>{col(NAR, 'ANTICIPO: no operar. Las órdenes se confirman el primer día hábil del mes que viene.')}</b>"))
    gan, gan_s = (serie.iloc[-1] / serie.iloc[0] - 1) * 100, (spy.iloc[-1] / spy.iloc[0] - 1) * 100
    mes = serie.resample("ME").last().pct_change().dropna()
    story = [Paragraph(titulo, T), Paragraph(sub, S),
             kpis([("Cartera del sistema", usd(ctx["valor"])),
                   (f"Desde el {pd.Timestamp(INICIO).strftime('%d/%m/%Y')}", pc(gan)),
                   ("S&amp;P mismo período", pc(gan_s)),
                   ("Último mes", pc(mes.iloc[-1] * 100) if len(mes) else "—"),
                   ("Órdenes", str(len(ords)))]),
             Spacer(1, 8), Paragraph("1. Qué hacer" + (" hoy" if modo == "ORDEN" else " (anticipo)"), H),
             Paragraph(f"Montos para una cartera de <b>{usd(CAPITAL_REF)}</b>. Para la tuya, usá la columna <b>% de la cartera</b>: "
                       "por ejemplo, 10% de una cartera de USD 25.000 son USD 2.500. Primero las ventas, después las compras.", N)]
    COLA = {"VENDER": ROJ, "RECORTAR": NAR, "COMPRAR": VER, "SUMAR": "#1f5fa8"}
    if len(ords):
        filas = [["#", "Orden", "Acción", "Puesto", "% cartera", "Monto", "Result.", "Motivo"]]
        for i, o in enumerate(ords, 1):
            filas.append([str(i), f"<b>{col(COLA[o['Orden']], o['Orden'])}</b>", lab(o['Acción']),
                          str(o["Puesto"] or "—"), pct(o["Monto"] / ctx["valor"] * 100, 1, False), usd(o["Monto"] * CAPITAL_REF / ctx["valor"]),
                          pc(o["Resultado %"]), o["Motivo"]])
        story.append(tabla(filas, [0.6 * cm, 2 * cm, 3.4 * cm, 1.5 * cm, 1.6 * cm, 1.9 * cm, 1.6 * cm, 4.4 * cm]))
    else:
        story.append(Paragraph(f"<b>{col(VER, 'Este mes no hay que hacer nada:')}</b> las 10 acciones siguen dentro del top 30 "
                               "y ninguna pasa del 20% de la cartera.", N))
    story.append(Paragraph("Para pasar los montos a CEDEARs usá el ratio de cada uno y el precio en pesos de tu broker; "
                           "redondeá a la cantidad entera más cercana. Costos estimados: 0,5% por operación.", NOTA))

    faltan = cart[cart["Peso %"] < 100 / TOP - 0.3].sort_values("Peso %")
    story.append(Paragraph("2. Si este mes aportás plata", H))
    if len(faltan):
        partes = [f"<b>{r['Acción']}</b> ({nombre(r['Acción'])}) hasta {pct(100 / TOP - r['Peso %'], 1, False)} de la cartera "
                  f"({usd((100 / TOP - r['Peso %']) / 100 * CAPITAL_REF)})" for _, r in faltan.iterrows()]
        story.append(Paragraph("Ponelo en este orden hasta que se termine: " + " · ".join(partes) +
                               ". Si todas llegan al 10%, repartí el resto en partes iguales entre las 10.", N))
    else:
        story.append(Paragraph("Todas están cerca del 10%: repartí el aporte en partes iguales entre las 10.", N))

    alertas = []
    for o in ords:
        if o["Orden"] == "RECORTAR":
            alertas.append(f"<b>{col(NAR, 'Concentración:')}</b> {o['Acción']} {o['Motivo'].lower()}.")
    sec = cart["Sector"].value_counts()
    for s_, n_ in sec[sec >= 3].items():
        alertas.append(f"<b>{col(NAR, 'Sector:')}</b> quedan {n_} acciones de {s_.lower()} "
                       f"({', '.join(cart.loc[cart['Sector'] == s_, 'Acción'])}). Solo informativo.")
    cerca = cart[(cart["Puesto"].fillna(999) >= BUFFER - 5) & (cart["Puesto"].fillna(999) <= BUFFER)]
    if len(cerca):
        alertas.append(f"<b>{col(GRI, 'Cerca de salir:')}</b> " + ", ".join(f"{r['Acción']} (puesto {int(r['Puesto'])})"
                       for _, r in cerca.iterrows()) + f". Se venden solo si pasan del puesto {BUFFER}.")
    if alertas:
        story.append(Paragraph("Alertas", H))
        story += [b(a) for a in alertas]

    filas = [["Acción", "Sector", "Desde", "Peso", "Monto", "Result.", "Puesto", "Estado"]]
    fondos = []
    for i, (_, r) in enumerate(cart.iterrows(), 1):
        filas.append([lab(r['Acción']), r["Sector"], r["Desde"].strftime("%d/%m/%y"), pct(r["Peso %"], 1, False),
                      usd(r["Peso %"] / 100 * CAPITAL_REF), pc(r["Resultado %"]), str(int(r["Puesto"])) if pd.notna(r["Puesto"]) else "—",
                      col(VER, r["Estado"]) if r["Estado"] == "NUEVA" else r["Estado"]])
        if r["Estado"] == "NUEVA":
            fondos.append((i, colors.HexColor("#E2EFDA")))
    story += [PageBreak(), Paragraph("3. Cartera del sistema después de operar", H),
              Paragraph(f"Si arrancás hoy, comprá estas {len(cart)} acciones en partes iguales (10% cada una).", N),
              tabla(filas, [3.3 * cm, 2.7 * cm, 1.7 * cm, 1.3 * cm, 1.9 * cm, 1.7 * cm, 1.5 * cm, 2.9 * cm], fondos),
              Spacer(1, 4), Image("mom_pesos.png", width=16.5 * cm, height=4.8 * cm),
              ]
    bloque4 = [Paragraph("4. Cómo viene", H)]
    if len(serie) < 5:
        bloque4.append(Paragraph("La cartera del sistema recién arranca: el gráfico y la comparación con el S&amp;P aparecen "
                               "a partir del mes que viene.", N))
    else:
        bloque4.append(Image("mom_evo.png", width=17 * cm, height=5.6 * cm))
    tab = pd.DataFrame({"c": serie, "s": spy}).resample("ME").last()
    tab = pd.concat([pd.DataFrame({"c": [serie.iloc[0]], "s": [spy.iloc[0]]}, index=[serie.index[0] - timedelta(days=1)]), tab])
    filas = [["Mes", "Cartera", "Mes", "S&amp;P mes", "Acumulado", "S&amp;P acum."]]
    for i in range(max(1, len(tab) - 6), len(tab)):
        d_, r = tab.index[i], tab.iloc[i]
        filas.append([f"{MESES[d_.month - 1].capitalize()} {d_.year}", usd(r["c"]), pc((r["c"] / tab.iloc[i - 1]["c"] - 1) * 100),
                      pc((r["s"] / tab.iloc[i - 1]["s"] - 1) * 100), pc((r["c"] / tab.iloc[0]["c"] - 1) * 100),
                      pc((r["s"] / tab.iloc[0]["s"] - 1) * 100)])
    if len(serie) >= 5:
        bloque4.append(tabla(filas, [3.2 * cm, 2.6 * cm, 2.2 * cm, 2.2 * cm, 2.4 * cm, 2.4 * cm]))
    story.append(KeepTogether(bloque4))

    filas = [["Puesto", "Acción", "Sector", "Suba 12 meses", "Puntaje", "Situación"]]
    fondos = []
    en_cart = set(cart["Acción"])
    nuevas = {o["Acción"] for o in ords if o["Orden"] == "COMPRAR"}
    for i, (t_, r) in enumerate(rk.head(15).iterrows(), 1):
        sit = "NUEVA" if t_ in nuevas else ("en cartera" if t_ in en_cart else "fuera (cartera llena)")
        filas.append([str(int(r["Puesto"])), lab(t_), r["Sector"], pc(r["Suba 12-1 %"], 0),
                      f"{r['Puntaje']:.2f}".replace(".", ","), col(VER, sit) if sit == "NUEVA" else sit])
        if t_ in en_cart:
            fondos.append((i, colors.HexColor("#E2EFDA") if t_ in nuevas else colors.HexColor("#EEF3FA")))
    story += [Paragraph("5. Ranking del mes (top 15)", H),
              Paragraph("Las que ya están en cartera no se cambian por otras mejor rankeadas: solo se venden si salen del top 30.", N),
              tabla(filas, [1.6 * cm, 4.2 * cm, 3.2 * cm, 2.2 * cm, 1.7 * cm, 4.1 * cm], fondos)]
    cer = ctx["cerradas"]
    if len(cer):
        filas = [["Acción", "Compra", "Venta", "Resultado", "Sector"]]
        for _, r in cer.tail(8).iloc[::-1].iterrows():
            filas.append([lab(r['Acción']), pd.Timestamp(r["Compra"]).strftime("%d/%m/%y"),
                          pd.Timestamp(r["Venta"]).strftime("%d/%m/%y"), pc(r["Resultado %"]), r["Sector"]])
        story += [KeepTogether([Paragraph("6. Últimas operaciones cerradas del sistema", H),
                  tabla(filas, [4.2 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm, 4.2 * cm]),
                  Paragraph(f"Desde el {pd.Timestamp(INICIO).strftime('%d/%m/%Y')}: {len(cer)} operaciones cerradas, "
                            f"{int((cer['Resultado %'] > 0).sum())} con ganancia.", NOTA)])]
    story += [Paragraph("Las reglas", H),
              b("10 acciones. Una acción se vende solo cuando sale del top 30 del ranking."),
              b("Cada compra nueva recibe el 10% de la cartera; el sobrante completa las posiciones más chicas."),
              b("Si una acción pasa del 20% de la cartera, se recorta a 12,5%."),
              b("Se opera una vez por mes, el día que llega este mail. Entre mails no se hace nada."),
              Spacer(1, 6),
              Paragraph("La “cartera del sistema” sigue las reglas desde el " + pd.Timestamp(INICIO).strftime("%d/%m/%Y") +
                        " sin aportes; tu cartera real puede tener otros pesos. Análisis estadístico con fines educativos; "
                        "no es una recomendación de inversión.", NOTA)]

    def pie(c, d):
        c.saveState(); c.setFont("Helvetica", 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1.1 * cm, "Momentum residual · resumen mensual")
        c.drawRightString(19 * cm, 1.1 * cm, f"Página {d.page}"); c.restoreState()

    SimpleDocTemplate(ruta, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.5 * cm, bottomMargin=1.6 * cm,
                      title=titulo).build(story, onFirstPage=pie, onLaterPages=pie)


def exportar_excel(ruta, ctx):
    with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
        def nombres(df, col="Acción"):
            if len(df) and col in df:
                df = df.copy()
                df.insert(df.columns.get_loc(col) + 1, "Empresa", [nombre(t) for t in df[col]])
                df.insert(df.columns.get_loc(col) + 2, "Código CEDEAR", [cedear(t) for t in df[col]])
            return df
        o = nombres(pd.DataFrame(ctx["ordenes"]))
        if len(o):
            o["% de la cartera"] = o["Monto"] / ctx["valor"] * 100
            o[f"Monto para USD {CAPITAL_REF:,.0f}"] = o["Monto"] * CAPITAL_REF / ctx["valor"]
            o = o.drop(columns=["Monto"])
        (o if len(o) else pd.DataFrame({"Sin órdenes este mes": []})).to_excel(xw, sheet_name="Órdenes", index=False)
        nombres(ctx["cartera"]).to_excel(xw, sheet_name="Cartera del sistema", index=False)
        rk = ctx["rk"].copy()
        rk["En cartera"] = ["Sí" if t in set(ctx["cartera"]["Acción"]) else "" for t in rk.index]
        rk.insert(0, "Empresa", [nombre(t) for t in rk.index])
        rk.insert(1, "Código CEDEAR", [cedear(t) for t in rk.index])
        rk.to_excel(xw, sheet_name="Ranking completo", index_label="Acción")
        (nombres(ctx["historial"]) if len(ctx["historial"]) else pd.DataFrame({"Sin historial": []})).to_excel(
            xw, sheet_name="Historial de órdenes", index=False)
        (nombres(ctx["cerradas"]) if len(ctx["cerradas"]) else pd.DataFrame({"Sin operaciones": []})).to_excel(
            xw, sheet_name="Operaciones cerradas", index=False)
        pd.DataFrame({"Cartera del sistema": ctx["serie"], "S&P 500": ctx["spy"]}).to_excel(xw, sheet_name="Evolución")
        for ws in xw.sheets.values():
            for c_ in ws.columns:
                ws.column_dimensions[c_[0].column_letter].width = 17
            for fila in ws.iter_rows(min_row=2):
                for cel in fila:
                    if isinstance(cel.value, float):
                        cel.number_format = "#,##0.00"


def texto_mail(ctx):
    hoy, ords, cart = ctx["mes_ref"], ctx["ordenes"], ctx["cartera"]
    L = [f"Momentum residual · {MESES[hoy.month - 1]} {hoy.year}",
         "ANTICIPO (no operar): así quedarían las órdenes si el mes cerrara hoy." if ctx["modo"] == "ANTICIPO"
         else "Operar al cierre de hoy. Primero las ventas, después las compras.", ""]
    if ords:
        L.append(f"ÓRDENES (monto para una cartera de {usd(CAPITAL_REF)} y % de la cartera):")
        for o in ords:
            L.append(f"  {o['Orden']:<9} {con_nombre(o['Acción'])}: {usd(o['Monto'] * CAPITAL_REF / ctx['valor'])} "
                     f"({pct(o['Monto'] / ctx['valor'] * 100, 1, False)} de la cartera) · {o['Motivo']}")
    else:
        L.append("Este mes no hay que hacer nada: las 10 siguen dentro del top 30.")
    faltan = cart[cart["Peso %"] < 100 / TOP - 0.3].sort_values("Peso %")
    L += ["", "Si aportás plata este mes, en este orden:"]
    L += [f"  {con_nombre(r['Acción'])}: hasta {pct(100 / TOP - r['Peso %'], 1, False)} de la cartera" for _, r in faltan.iterrows()] or \
         ["  repartilo en partes iguales entre las 10."]
    L += ["", "Cartera del sistema después de operar:"]
    L += [f"  {con_nombre(r['Acción'])}: {pct(r['Peso %'], 0, False)}" for _, r in cart.iterrows()]
    L += ["", "Adjuntos: resumen en PDF y detalle en Excel."]
    n = {k: sum(o["Orden"] == k for o in ords) for k in ("VENDER", "COMPRAR", "RECORTAR")}
    partes = [f"{n['VENDER']} venta" + ("s" if n["VENDER"] != 1 else ""), f"{n['COMPRAR']} compra" + ("s" if n["COMPRAR"] != 1 else "")]
    if n["RECORTAR"]:
        partes.append(f"{n['RECORTAR']} recorte" + ("s" if n["RECORTAR"] != 1 else ""))
    asunto = (f"Momentum · {MESES[hoy.month - 1].capitalize()} {hoy.year} · " +
              (", ".join(partes) if ords else "sin cambios"))
    if ords and all(o["Orden"] == "COMPRAR" for o in ords) and len(ords) == TOP:
        asunto = f"Momentum · {MESES[hoy.month - 1].capitalize()} {hoy.year} · compra inicial ({TOP} acciones)"
    if ctx["modo"] == "ANTICIPO":
        asunto = "ANTICIPO · " + asunto
    return asunto, "\n".join(L)


def enviar_mail(asunto, cuerpo, adjuntos):
    import smtplib
    from email.message import EmailMessage
    usuario = os.environ["GMAIL_USER"]
    clave = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    destinos = [d.strip() for d in os.environ.get("MAIL_TO", usuario).split(",") if d.strip()]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, usuario, ", ".join(destinos)
    msg.set_content(cuerpo)
    for ruta, tipo in adjuntos:
        with open(ruta, "rb") as fh:
            main_, sub_ = tipo.split("/")
            msg.add_attachment(fh.read(), filename=os.path.basename(ruta), maintype=main_, subtype=sub_)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(usuario, clave)
        s.send_message(msg)
    print("Mail enviado a:", ", ".join(destinos))


def main():
    hoy = hoy_ar()
    forzar = os.environ.get("FORZAR", "0") == "1" or "--forzar" in sys.argv
    primer = es_primer_dia_habil(hoy)
    if not primer and not forzar:
        print(f"{hoy}: no es el primer día hábil del mes. No se envía nada.")
        return
    modo = "ORDEN" if primer else "ANTICIPO"
    print(f"{hoy}: modo {modo}. Descargando precios...")
    px, vo = descargar()
    if modo == "ORDEN":        # si ya hay precio de hoy (corrida tarde), se usa el cierre anterior
        px, vo = px[px.index < pd.Timestamp(hoy)], vo[vo.index < pd.Timestamp(hoy)]
    motor = Motor(px, vo)
    print(f"Acciones con datos: {len(motor.acc)} · último cierre {motor.idx[-1].date()}")
    hold, caja, serie, spy, historial, cerradas, eventos = simular(motor)
    k = len(motor.idx) - 1
    ult = pd.Timestamp(motor.idx[-1])
    rk = motor.ranking(k)
    precios = px.iloc[k]
    hold2, caja2, ords, cer2 = aplicar_reglas(hold, caja, rk, precios, pd.Timestamp(hoy))
    valor = caja + sum(h["cant"] * precios[t] for t, h in hold.items())
    valor2 = caja2 + sum(h["cant"] * precios[t] for t, h in hold2.items())
    nuevas = {o["Acción"] for o in ords if o["Orden"] == "COMPRAR"}
    recort = {o["Acción"] for o in ords if o["Orden"] == "RECORTAR"}
    sumas = {o["Acción"] for o in ords if o["Orden"] == "SUMAR"}
    puesto = rk["Puesto"].to_dict()
    cart = pd.DataFrame([{"Acción": t, "Sector": SECTOR.get(t, "Otros"), "Desde": pd.Timestamp(h["compra"]),
                          "Peso %": h["cant"] * precios[t] / valor2 * 100,
                          "Resultado %": (h["cant"] * precios[t] / h["costo"] - 1) * 100 if t not in nuevas else np.nan,
                          "Puesto": puesto.get(t, np.nan),
                          "Estado": "NUEVA" if t in nuevas else ("recortada" if t in recort else ("se suma" if t in sumas else "se mantiene"))}
                         for t, h in hold2.items()]).sort_values("Peso %", ascending=False)
    orden = {"VENDER": 0, "RECORTAR": 1, "COMPRAR": 2, "SUMAR": 3}
    ords = sorted(ords, key=lambda o: orden[o["Orden"]])
    mes_ref = hoy if modo == "ORDEN" else (pd.Timestamp(hoy) + pd.offsets.MonthBegin(1)).date()
    ctx = dict(hoy=hoy, mes_ref=mes_ref, modo=modo, cierre=ult, serie=serie, spy=spy, cartera=cart, rk=rk, ordenes=ords, valor=valor,
               historial=historial, cerradas=cerradas)
    ruta_x = f"momentum_{hoy.isoformat()}.xlsx"
    ruta_p = f"momentum_{hoy.isoformat()}.pdf"
    exportar_excel(ruta_x, ctx)
    generar_pdf(ruta_p, ctx)
    asunto, cuerpo = texto_mail(ctx)
    print(asunto)
    print(cuerpo)
    if os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"):
        enviar_mail(asunto, cuerpo, [(ruta_p, "application/pdf"),
                                     (ruta_x, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
    else:
        print("(Sin credenciales de Gmail: no se envía el mail.)")
    try:
        from google.colab import files
        files.download(ruta_p)
        files.download(ruta_x)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
