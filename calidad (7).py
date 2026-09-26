"""
CARTERA DE CALIDAD - mail mensual
=================================
Arma y mantiene una cartera concentrada de 10 empresas de calidad para el largo plazo (5-10 años),
entre las acciones con CEDEAR en BYMA, y manda cada mes qué comprar, vender, rotar o recortar.

Cómo elige (con los balances anuales de la SEC de EE.UU., últimos 5 años, igual que el backtest):
  1. Filtros mínimos (si no pasa uno, queda afuera):
       - Rentabilidad sobre el capital invertido (ROIC) promedio >= 12%  (bancos y aseguradoras: ROE)
       - Deuda neta / EBITDA <= 3
       - Que genere caja: promedio de flujo de caja libre (descontando pagos en acciones) y ganancia neta positivo
       - Ventas creciendo >= 5% anual
       - Cantidad de acciones creciendo <= 3% anual (poca dilución)
       - Más de USD 20 millones operados por día
  2. Puntaje de calidad (0 a 100) entre las que pasan: ROIC, crecimiento de ventas y de caja por acción,
     margen bruto, conversión de ganancias en caja, deuda, dilución y precio.
  3. Precio: rendimiento esperado a 10 años. Base = promedio de flujo de caja libre y ganancia neta (así no
     castiga a las que invierten fuerte para crecer, como en IA). Crecimiento estimado apoyado en las ventas
     (hasta 30% anual), que se va frenando del año 6 al 10 hasta 4%; al final se valúa a 25 veces esa caja
     (bancos: 15 veces).
  4. Tendencia: momentum residual (el mismo del momentum mensual), en percentil entre todas las acciones.
  5. Qué se compra: entre las 20 mejores en calidad, un ranking combinado de 50% calidad, 25% precio y
     25% tendencia. Quedan afuera las de precio extremo (menos de 5% anual esperado) y las del 10% de peor
     tendencia (castigadas por el mercado). Así la cartera siempre tiene 10 empresas de calidad.

Reglas de la cartera:
  * 10 empresas, 10% cada una al comprar. Máximo 3 del mismo sector (tecnología y semis cuentan juntas).
  * VENDER solo si la tesis se rompe (deja de pasar un filtro mínimo) o, en las revisiones trimestrales
    (feb, may, ago, nov), si cayó del puesto 20 de calidad: se reemplaza por la mejor del ranking combinado.
  * RECORTAR si una posición pasa del 25% (baja a 20%), o si el precio es extremo (rendimiento esperado a
    10 años menor a 5%) y pesa más de 12,5% (baja a 10%).
  * Nunca vende porque bajó el precio: si cae más de 25% contra el S&P, pide revisar la tesis a mano.
    No sugiere comprar más de una acción castigada: eso lo decide una persona.
  * La plata que no tiene destino (ventas sin reemplazo, esperando precio) queda estacionada en SPY.

Memoria: la cartera se guarda en cartera_calidad.json. GitHub lo actualiza solo después de cada revisión
oficial (primer día hábil desde el 15 de cada mes). Las corridas manuales son de CONSULTA y no lo tocan,
salvo que se marque "operar".

Variables de entorno (GitHub → Settings → Secrets and variables → Actions):
  GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_TO  (secretos, los mismos del momentum)
  CALIDAD_CAPITAL (variable opcional): tamaño de referencia de la cartera en USD (por defecto 10.000)
  CALIDAD_SEC_AGENTE (variable obligatoria): nombre y mail para identificarse ante la SEC, ej. "Juan Perez juan@mail.com"
  CALIDAD_EXCLUIR (variable opcional): acciones que no se quieren, separadas por coma
  CALIDAD_FUENTE (variable opcional): "sec" (por defecto, igual que el backtest) o "yahoo"
  OPERAR=1: guarda la corrida como oficial aunque no sea el día (sirve para arrancar la cartera hoy)
"""
import copy
import gzip
import bisect
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf

TOP = 10
OBJ = 0.10                 # peso de cada compra nueva
TOPE, RECORTE_A = 0.25, 0.20
EXTREMO_PESO, EXTREMO_A = 0.125, 0.10
BUFFER = 20                # en revisión trimestral, se puede rotar si cae de este puesto
MAX_SECTOR = 3
ROT_MAX = 2                # máximo de rotaciones por revisión
ROT_VENTAJA = 0.03         # la reemplazante debe rendir 3 puntos más (rendimiento esperado)
ER_MIN = 0.10             # rendimiento esperado anual a 10 años mínimo para comprar
EXTREMO_ER = 0.05          # por debajo de esto el precio es extremo
G_MAX, G_FINAL = 0.30, 0.04
MULT_SALIDA, MULT_SALIDA_FIN = 25, 15
MOM_CORTE = 0.10           # 10% de peor momentum residual: no se compra
PESOS_COMB = (0.50, 0.25, 0.25)   # ranking combinado: calidad, precio, tendencia
MESES_REG = 36
ALARMA_REL = -0.25         # caída contra el S&P desde la compra que obliga a revisar
VOL_MIN_USD = 20_000_000
COSTO = 0.005
MESES_REVISION = {2, 5, 8, 11}
DIA_REVISION = 15
KO_ROIC, KO_DEUDA, KO_VENTAS, KO_DILUCION = 0.12, 3.0, 0.05, 0.03
ESTADO = os.environ.get("CALIDAD_ESTADO") or "cartera_calidad.json"
TESIS_CSV = os.environ.get("CALIDAD_TESIS") or "tesis_calidad.csv"
CAPITAL_REF = float(os.environ.get("CALIDAD_CAPITAL") or 10_000)
# Bancos, aseguradoras y financieras con balance de banco: se miden por ROE, sin deuda ni flujo de caja.
FINANCIERAS = {"JPM", "BAC", "C", "GS", "MS", "WFC", "USB", "SCHW", "BK", "BRK-B", "AXP", "NU"}
MONEDAS_EXCLUIDAS = {"ARS", "TRY", "VES"}   # balances en moneda con inflación alta: crecimientos no comparables

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
    "NU": ("Nu Holdings, Nubank", "NU"),
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

SECTOR = {}
for _s, _ts in {
    "Semiconductores": "NVDA AMD AVGO INTC QCOM TXN MU ADI AMAT LRCX KLAC NXPI TSM ASML",
    "Tecnología": "AAPL MSFT CRM ADBE ORCL IBM CSCO SAP INTU NOW ACN HPQ DELL SHOP ZM DOCU TWLO PLTR SNOW SONY GLOB",
    "Comunicación": "GOOGL META NFLX DIS SNAP PINS ROKU SPOT T VZ TMUS CMCSA BIDU",
    "Consumo discrecional": "AMZN TSLA MELI BABA JD EBAY ETSY UBER ABNB NKE SBUX MCD HD LOW TGT BKNG EXPE MAR F GM TM HMC ARCO NIO",
    "Financiero": "V MA AXP JPM BAC C GS MS WFC USB SCHW BLK SPGI MCO BK BRK-B PYPL COIN XYZ NU",
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

# Quedan afuera siempre porque sus datos en la SEC no se pueden leer bien de forma automática:
#  - Ford y General Motors consolidan su financiera y la deuda no se capta (parecen tener más caja que deuda).
#  - JD, Alibaba, Baidu y NIO reportan en yuanes y cotizan como ADR (otra cantidad de acciones): la valuación sale mal.
DATOS_DUDOSOS = {"F", "GM", "JD", "BABA", "BIDU", "NIO"}
_EXCLUIR = {t.strip().upper() for t in (os.environ.get("CALIDAD_EXCLUIR") or "").split(",") if t.strip()} | DATOS_DUDOSOS
FUENTE = (os.environ.get("CALIDAD_FUENTE") or "sec").strip().lower()   # "sec" (igual que el backtest) o "yahoo"
TICKERS = sorted(t for t in CEDEARS if t not in _EXCLUIR)


def nombre(t):
    return CEDEARS.get(t, (t, t))[0]


def cedear(t):
    return CEDEARS.get(t, (t, t))[1]


def con_nombre(t):
    extra = f", CEDEAR {cedear(t)}" if cedear(t) != t else ""
    return f"{t} ({nombre(t)}{extra})"


def sector(t):
    return SECTOR.get(t, "Otros")


def grupo(t):
    """Para el límite por sector, tecnología y semiconductores cuentan como uno solo."""
    s = sector(t)
    return "Tecnología" if s in ("Tecnología", "Semiconductores") else s


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def hoy_ar():
    fijo = os.environ.get("HOY")          # solo para pruebas
    if fijo:
        return date.fromisoformat(fijo)
    return (pd.Timestamp.utcnow() - pd.Timedelta(hours=3)).date()


def es_dia_revision(d):
    """Primer día hábil desde el 15 del mes."""
    return d.weekday() < 5 and d.day >= DIA_REVISION and \
        all(date(d.year, d.month, k).weekday() >= 5 for k in range(DIA_REVISION, d.day))


# ============================================================================ datos
def descargar_precios(desde):
    lista = TICKERS + ["SPY"]
    datos = None
    for intento in range(3):
        try:
            datos = yf.download(lista, start=desde, interval="1d", auto_adjust=True, group_by="ticker",
                                threads=True, progress=False)
            break
        except Exception as e:          # noqa: BLE001
            print("Reintentando descarga de precios:", e)
            time.sleep(20)
    close, volume = {}, {}
    for t in lista:
        try:
            df = datos[t] if isinstance(datos.columns, pd.MultiIndex) else datos
            df = df[["Close", "Volume"]].dropna(subset=["Close"])
            if len(df):
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                close[t], volume[t] = df["Close"], df["Volume"]
        except (KeyError, TypeError):
            pass
    if "SPY" not in close:
        raise RuntimeError("No se pudieron bajar los precios del S&P (SPY).")
    idx = close["SPY"].index
    px = pd.DataFrame(close).reindex(idx).ffill()
    vo = pd.DataFrame(volume).reindex(idx)
    return px, vo


def descargar_fx(monedas):
    """Cotización de cada moneda contra el dólar (cuántos USD vale 1 unidad)."""
    fx = {"USD": 1.0}
    pedir = sorted(m for m in monedas if m and m != "USD" and m not in MONEDAS_EXCLUIDAS)
    for m in pedir:
        try:
            s = yf.download(f"{m}USD=X", period="10d", interval="1d", auto_adjust=True, progress=False)["Close"]
            s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
            s = s.dropna()
            if len(s):
                fx[m] = float(s.iloc[-1])
        except Exception as e:          # noqa: BLE001
            print(f"Sin cotización {m}/USD:", e)
    return fx


def bajar_fundamentales(tickers):
    """Balances anuales e info de cada empresa. Devuelve {ticker: (resultados, balance, flujo, info)}."""
    out = {}
    for i, t in enumerate(tickers, 1):
        for intento in range(3):
            try:
                tk = yf.Ticker(t)
                inc, bal, cf = tk.income_stmt, tk.balance_sheet, tk.cashflow
                try:
                    info = tk.info or {}
                except Exception:       # noqa: BLE001
                    info = {}
                if not info.get("marketCap"):
                    try:
                        info["marketCap"] = float(tk.fast_info["market_cap"])
                    except Exception:   # noqa: BLE001
                        pass
                out[t] = (inc, bal, cf, info)
                break
            except Exception as e:      # noqa: BLE001
                if intento == 2:
                    print(f"  {t}: sin balances ({e})")
                time.sleep(3 * (intento + 1))
        if i % 20 == 0:
            print(f"  balances: {i}/{len(tickers)}")
        time.sleep(0.25)
    return out


# ============================================================================ datos de la SEC (mismo motor que el backtest)
FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"}
TAGS = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet", "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "RevenuesNetOfInterestExpense"],
    "gp": ["GrossProfit"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"],
    "ebit": ["OperatingIncomeLoss"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "ni": ["NetIncomeLossAvailableToCommonStockholdersBasic", "NetIncomeLoss", "ProfitLoss"],
    "sh": ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
           "WeightedAverageNumberOfSharesOutstandingBasic"],
    "ltd": ["LongTermDebt"],
    "ltd_nc": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
    "ltd_c": ["LongTermDebtCurrent", "DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "std": ["ShortTermBorrowings", "CommercialPaper"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"],
    "sti": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "eq": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet", "Depreciation"],
}
DURACION = {"rev", "gp", "cogs", "ebit", "pretax", "tax", "ni", "sh", "ocf", "capex", "sbc", "da"}
TODOS_TAGS = {t for ts in TAGS.values() for t in ts}


# ============================================================================ SEC
def _get_sec(url, agente):
    h = {"User-Agent": agente, "Accept-Encoding": "gzip, deflate"}
    for intento in range(4):
        try:
            r = requests.get(url, headers=h, timeout=60)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                return r.json()
            print(f"  SEC respondió {r.status_code}; reintento...")
        except Exception as e:      # noqa: BLE001
            print("  error de conexión con la SEC:", e)
        time.sleep(2 + 3 * intento)
    return None


def bajar_sec(tickers, agente, cache="edgar_cache"):
    """{ticker: {tag: [(inicio, fin, valor, publicado, dias), ...]}} solo con balances anuales."""
    os.makedirs(cache, exist_ok=True)
    mapa = _get_sec("https://www.sec.gov/files/company_tickers.json", agente)
    if not mapa:
        raise RuntimeError("No se pudo bajar el listado de la SEC. Revisá el nombre y mail de identificación (CALIDAD_SEC_AGENTE) y la conexión.")
    cik = {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in mapa.values()}
    out = {}
    for i, t in enumerate(tickers, 1):
        ruta = os.path.join(cache, f"{t}.json.gz")
        datos = None
        if os.path.exists(ruta):
            with gzip.open(ruta, "rt") as fh:
                datos = json.load(fh)
        elif t in cik:
            js = _get_sec(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik[t]:010d}.json", agente)
            time.sleep(0.15)
            datos = {}
            if js:
                for tax in ("us-gaap",):
                    for tag, obj in js.get("facts", {}).get(tax, {}).items():
                        if tag not in TODOS_TAGS:
                            continue
                        for unidad, filas in obj.get("units", {}).items():
                            if unidad not in ("USD", "shares"):
                                continue
                            r = [(a.get("start"), a["end"], a["val"], a["filed"]) for a in filas if a.get("form") in FORMS]
                            if r:
                                datos[tag] = r
            with gzip.open(ruta, "wt") as fh:
                json.dump(datos, fh)
        if datos:
            proc = {}
            for tag, filas in datos.items():
                fx = []
                for s, e, v, f in filas:
                    dias = (pd.Timestamp(e) - pd.Timestamp(s)).days if s else None
                    fx.append((s, e, float(v), f, dias))
                proc[tag] = fx
            out[t] = proc
        if i % 20 == 0:
            print(f"  SEC: {i}/{len(tickers)}")
    return out


class Balances:
    """Arma, para una empresa y una fecha, los estados contables anuales tal como se conocían ese día."""

    def __init__(self, t, facts, splits):
        self.t, self.f = t, facts
        self.splits = splits                    # Serie fecha -> ratio (solo días con split)
        pub = set()
        for tag in TAGS["rev"] + TAGS["ni"]:
            for s, e, v, f, d in facts.get(tag, []):
                if d and 330 <= d <= 400:
                    pub.add(f)
        self.pub = sorted(pub)
        self._cache = {}

    def factor_split(self, publicado):
        if not len(self.splits):
            return 1.0
        s = self.splits[pd.to_datetime(self.splits.index) > pd.Timestamp(publicado)]
        return float(np.prod(s.values)) if len(s) else 1.0

    def _serie(self, clave, hasta):
        """{fin_de_ejercicio: valor} combinando los tags por prioridad, con el último dato publicado hasta 'hasta'."""
        dur = clave in DURACION
        res = {}
        for tag in TAGS[clave]:
            mejor = {}
            for s, e, v, f, d in self.f.get(tag, []):
                if f > hasta:
                    continue
                if dur and not (d and 330 <= d <= 400):
                    continue
                if not dur and s:
                    continue
                if clave == "sh":
                    v = v * self.factor_split(f)
                if e not in mejor or f > mejor[e][0]:
                    mejor[e] = (f, v)
            for e, (f, v) in mejor.items():
                res.setdefault(e, v)
        return res

    def estados(self, fecha):
        hasta = fecha.strftime("%Y-%m-%d")
        k = bisect.bisect_right(self.pub, hasta)
        if k == 0:
            return None
        clave = self.pub[k - 1]
        if clave in self._cache:
            return self._cache[clave]
        S = {c: self._serie(c, hasta) for c in TAGS}
        fines = sorted(set(S["rev"]) | set(S["ni"]))
        # un mismo ejercicio con fechas de cierre levemente distintas (años de 52/53 semanas, cambio de etiqueta)
        limpio = []
        for e in fines:
            if limpio and (pd.Timestamp(e) - pd.Timestamp(limpio[-1])).days < 60:
                limpio[-1] = e if e in S["rev"] else limpio[-1]
            else:
                limpio.append(e)
        fines = [e for e in limpio if e in S["rev"]][-5:] if any(e in S["rev"] for e in limpio) else limpio[-5:]
        if len(fines) < 3:
            self._cache[clave] = None
            return None
        cols = [pd.Timestamp(e) for e in fines]
        g = lambda c, e: S[c].get(e, np.nan)

        def instante(c, e):
            if e in S[c]:
                return S[c][e]
            # balances con fecha levemente distinta al cierre (hasta 10 días)
            et = pd.Timestamp(e)
            cerca = [x for x in S[c] if abs((pd.Timestamp(x) - et).days) <= 10]
            return S[c][cerca[0]] if cerca else np.nan

        inc, bal, cf = {}, {}, {}
        for e, col in zip(fines, cols):
            rev = g("rev", e)
            gp = g("gp", e)
            if pd.isna(gp) and pd.notna(g("cogs", e)) and pd.notna(rev):
                gp = rev - g("cogs", e)
            ebit, da = g("ebit", e), g("da", e)
            inc[col] = {"Total Revenue": rev, "Gross Profit": gp, "EBIT": ebit,
                        "EBITDA": ebit + (0 if pd.isna(da) else da) if pd.notna(ebit) else np.nan,
                        "Pretax Income": g("pretax", e), "Tax Provision": g("tax", e),
                        "Net Income Common Stockholders": g("ni", e), "Diluted Average Shares": g("sh", e)}
            ltd = instante("ltd", e)
            if pd.isna(ltd):
                nc, cu = instante("ltd_nc", e), instante("ltd_c", e)
                ltd = (0 if pd.isna(nc) else nc) + (0 if pd.isna(cu) else cu)
            std = instante("std", e)
            cash, sti = instante("cash", e), instante("sti", e)
            bal[col] = {"Total Debt": ltd + (0 if pd.isna(std) else std),
                        "Cash Cash Equivalents And Short Term Investments": (0 if pd.isna(cash) else cash) + (0 if pd.isna(sti) else sti),
                        "Stockholders Equity": instante("eq", e)}
            ocf, capex = g("ocf", e), g("capex", e)
            cf[col] = {"Free Cash Flow": ocf - (0 if pd.isna(capex) else capex) if pd.notna(ocf) else np.nan,
                       "Operating Cash Flow": ocf, "Capital Expenditure": -capex if pd.notna(capex) else np.nan,
                       "Stock Based Compensation": g("sbc", e), "Depreciation And Amortization": da}
        res = (pd.DataFrame(inc), pd.DataFrame(bal), pd.DataFrame(cf))
        self._cache[clave] = res
        return res


# ============================================================================ precios


def descargar_todo(tickers, desde="2006-01-01"):
    """Precios sin ajustar por dividendos (Close, para valor de mercado y volumen), ajustados (Adj Close, para
    rendimientos y tendencia) y splits. Es la misma descarga que usa el backtest."""
    lista = tickers + ["SPY", "BIL"]
    datos = None
    for intento in range(3):
        try:
            datos = yf.download(lista, start=desde, interval="1d", auto_adjust=False, actions=True,
                                group_by="ticker", threads=True, progress=False)
            break
        except Exception as e:      # noqa: BLE001
            print("Reintentando precios:", e)
            time.sleep(20)
    close, adj, vol, spl = {}, {}, {}, {}
    for t in lista:
        try:
            df = datos[t].dropna(subset=["Close"])
        except (KeyError, TypeError):
            continue
        if not len(df):
            continue
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        close[t], adj[t], vol[t] = df["Close"], df["Adj Close"], df["Volume"]
        s = df["Stock Splits"] if "Stock Splits" in df else pd.Series(dtype=float)
        spl[t] = s[s > 0]
    idx = adj["SPY"].index
    return (pd.DataFrame(close).reindex(idx).ffill(), pd.DataFrame(adj).reindex(idx).ffill(),
            pd.DataFrame(vol).reindex(idx), spl)


def metricas_sec(univ, B, close, d, cache):
    """Métricas de cada empresa con los balances publicados hasta la fecha d y el valor de mercado de ese día."""
    mets, con_datos = [], 0
    for t in univ:
        est = B[t].estados(d)
        if est is None:
            mets.append({"Acción": t, "tipo": "empresa", "moneda": "USD", "mcap": None, "error": "sin balances"})
            continue
        clave = (t, id(est))
        if clave not in cache:
            try:
                m0 = calcular_metricas(t, est[0], est[1], est[2], {"financialCurrency": "USD"})
            except Exception as e:      # noqa: BLE001
                m0 = {"Acción": t, "tipo": "empresa", "moneda": "USD", "mcap": None, "error": f"error ({e})"}
            sh = est[0].loc["Diluted Average Shares"].dropna() if "Diluted Average Shares" in est[0].index else pd.Series(dtype=float)
            m0["_acciones"] = float(sh.iloc[-1]) if len(sh) else np.nan
            cache[clave] = m0
        m = dict(cache[clave])
        if not m.get("error"):
            con_datos += 1
        px_d = close[t].loc[:d].dropna()
        precio = float(px_d.iloc[-1]) if len(px_d) and px_d.index[-1] >= d - pd.Timedelta(days=10) else np.nan
        m["mcap"] = m.pop("_acciones", np.nan) * precio if pd.notna(precio) else None
        if m["mcap"] is not None and pd.isna(m["mcap"]):
            m["mcap"] = None
        mets.append(m)
    return mets, con_datos


def ranking_desde(mets, close, adj, dvol, d):
    """Filtros, precio, tendencia y ranking combinado a la fecha d."""
    _, mom_pct = momentum_residual(adj.loc[:d])
    liq = dvol.loc[:d].iloc[-1]
    ev = []
    for m in mets:
        t = m["Acción"]
        pr = close[t].loc[:d].dropna()
        ev.append(evaluar(m, float(pr.iloc[-1]) if len(pr) else np.nan, liq.get(t, np.nan), {"USD": 1.0}, mom_pct.get(t, np.nan)))
    return armar_ranking(ev)


# ============================================================================ métricas
def _fila(df, *nombres):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for n in nombres:
        if n in df.index:
            s = df.loc[n]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[0]
            s = pd.to_numeric(s, errors="coerce")
            s.index = pd.to_datetime(s.index)
            if s.notna().any():
                return s.sort_index()
    return None


def _alinear(s, cols):
    if s is None:
        return pd.Series(np.nan, index=cols, dtype=float)
    s = s[~s.index.duplicated()].sort_index()
    return s.reindex(cols, method="nearest", tolerance=pd.Timedelta(days=45))


def _cagr(a, b, anios):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a <= 0 or b <= 0 or anios <= 0.5:
        return np.nan
    return (b / a) ** (1 / anios) - 1


def _cagr_suave(s):
    """Crecimiento anual usando el promedio de los 2 primeros y los 2 últimos años (menos ruido)."""
    s = s.dropna()
    if len(s) < 2:
        return np.nan
    if len(s) >= 4:
        a, b = s.iloc[:2].mean(), s.iloc[-2:].mean()
        anios = ((s.index[-2:].mean() - s.index[:2].mean()).days) / 365.25
    else:
        a, b = s.iloc[0], s.iloc[-1]
        anios = (s.index[-1] - s.index[0]).days / 365.25
    return _cagr(a, b, anios)


def _extremos(s):
    s = s.dropna()
    if len(s) < 2:
        return np.nan
    return _cagr(s.iloc[0], s.iloc[-1], (s.index[-1] - s.index[0]).days / 365.25)


def calcular_metricas(t, inc, bal, cf, info):
    m = {"Acción": t, "tipo": "financiera" if t in FINANCIERAS else "empresa",
         "moneda": (info or {}).get("financialCurrency") or "USD", "mcap": (info or {}).get("marketCap"),
         "error": None}
    rev = _fila(inc, "Total Revenue", "Operating Revenue")
    if rev is None:
        m["error"] = "sin balances"
        return m
    cols = rev.dropna().index[-5:]
    if len(cols) < 3:
        m["error"] = "menos de 3 años de balances"
        return m
    rev = rev.reindex(cols)
    A = lambda df, *n: _alinear(_fila(df, *n), cols)
    anios = (cols[-1] - cols[0]).days / 365.25
    m["anios"] = len(cols)
    m["ultimo_balance"] = cols[-1].strftime("%Y-%m")
    m["ventas_cagr"] = _cagr(rev.iloc[0], rev.iloc[-1], anios)
    m["ventas_ult"] = rev.iloc[-1] / rev.iloc[-2] - 1 if rev.iloc[-2] > 0 else np.nan
    acc = A(inc, "Diluted Average Shares", "Basic Average Shares")
    if acc.isna().all():
        acc = A(bal, "Ordinary Shares Number", "Share Issued")
    m["dilucion"] = _extremos(acc)
    ni = A(inc, "Net Income Common Stockholders", "Net Income", "Net Income From Continuing Operation Net Minority Interest")
    eq = A(bal, "Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest")
    if m["tipo"] == "financiera":
        roe = (ni / eq.where(eq > 0)).clip(-1, 1)
        m["rent_serie"] = roe
        m["crec_accion"] = _cagr_suave(ni / acc)
        m["caja_base"] = ni.iloc[-2:].mean()            # ganancias (en financieras no se usa flujo de caja)
        m["mb_prom"] = m["mb_ult"] = m["mb_var"] = m["deuda_ebitda"] = m["conversion"] = np.nan
    else:
        ebit = A(inc, "EBIT", "Operating Income")
        tasa = A(inc, "Tax Rate For Calcs")
        if tasa.isna().all():
            tasa = A(inc, "Tax Provision") / A(inc, "Pretax Income")
        tasa = tasa.where((tasa >= 0) & (tasa <= 0.35)).fillna(0.21)
        deuda = A(bal, "Total Debt").fillna(0)
        caja = A(bal, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents").fillna(0)
        ic = deuda + eq - caja
        ic_prom = ((ic + ic.shift(1)) / 2).fillna(ic)
        nopat = ebit * (1 - tasa)
        roic = (nopat / ic_prom.where(ic_prom > 0)).clip(-1, 1)
        negativo = (ic_prom <= 0) & nopat.notna()      # capital invertido negativo (más caja que deuda y patrimonio)
        roic[negativo] = np.where(nopat[negativo] > 0, 1.0, -1.0)
        roic[nopat.isna() | ic_prom.isna()] = np.nan   # año sin datos de balance: no se inventa
        m["rent_serie"] = roic
        gp = A(inc, "Gross Profit")
        mb = gp / rev
        m["mb_prom"], m["mb_ult"] = mb.mean(), mb.dropna().iloc[-1] if mb.notna().any() else np.nan
        mbv = mb.dropna()
        m["mb_var"] = mbv.iloc[-1] - mbv.iloc[0] if len(mbv) >= 2 else np.nan
        ebitda = A(inc, "EBITDA", "Normalized EBITDA")
        if ebitda.isna().all():
            ebitda = ebit + A(cf, "Depreciation And Amortization", "Depreciation Amortization Depletion").fillna(0)
        fcf = A(cf, "Free Cash Flow")
        if fcf.isna().all():
            fcf = A(cf, "Operating Cash Flow") + A(cf, "Capital Expenditure").fillna(0)
        sbc = A(cf, "Stock Based Compensation").fillna(0)
        fcfa = fcf - sbc
        m["crec_accion"] = _cagr_suave(fcfa / acc)
        m["fcf_base"] = fcfa.iloc[-2:].mean()
        m["ni_base"] = ni.iloc[-2:].mean()
        m["caja_base"] = np.nanmean([m["fcf_base"], m["ni_base"]]) if pd.notna(m["fcf_base"]) or pd.notna(m["ni_base"]) else np.nan
        nd, eb = deuda.iloc[-1] - caja.iloc[-1], ebitda.iloc[-1]
        m["deuda_ebitda"] = (nd / eb) if pd.notna(eb) and eb > 0 else (0.0 if nd <= 0 else np.inf)
        m["conversion"] = fcfa.sum() / ni.sum() if ni.sum() > 0 and fcfa.notna().sum() >= 2 else np.nan
    r = m["rent_serie"].dropna()
    m["rent_prom"] = r.mean() if len(r) else np.nan
    m["rent_ult"] = r.iloc[-1] if len(r) else np.nan
    m["rent_baja2"] = bool(len(r) >= 3 and r.iloc[-1] < r.iloc[-2] < r.iloc[-3] and r.iloc[-1] < r.iloc[-3] - 0.02)
    m["rent_ini"] = r.iloc[0] if len(r) else np.nan
    return m


CHECKS = ["Rentab. ≥15% sin caer", "Margen bruto estable", "Ventas ≥8%/año", "Caja por acción ≥10%/año",
          "Deuda < 2x EBITDA", "Conversión en caja ≥80%", "Sin dilución", "Precio razonable (≥10% a 10 años)"]


_EXP = np.arange(1, 11)


def _flujos(g, mult):
    """Caja de los años 1 a 10 por cada 1 de caja actual (crece g, se frena a 4% del año 6 al 10) + venta final."""
    f, fl = 1.0, []
    for k in range(1, 11):
        gk = g if k <= 5 else g + (G_FINAL - g) * (k - 5) / 5
        f *= 1 + gk
        fl.append(f)
    fl[-1] += fl[-1] * mult
    return np.array(fl)


def tir_10(y, g, mult):
    """Rendimiento anual a 10 años comprando con caja/valor = y, creciendo g (se frena a 4% del año 6 al 10)
    y vendiendo al final a 'mult' veces la caja. Supone que la caja de cada año vuelve al accionista."""
    if pd.isna(y) or y <= 0:
        return np.nan
    fl, objetivo = _flujos(g, mult), 1.0 / y
    lo, hi = -0.9, 2.0
    for _ in range(60):
        r = (lo + hi) / 2
        lo, hi = (r, hi) if (fl / (1 + r) ** _EXP).sum() > objetivo else (lo, r)
    return (lo + hi) / 2


def caja_necesaria(obj, g, mult):
    """Caja/valor necesaria para que el rendimiento a 10 años sea 'obj'."""
    return 1.0 / (_flujos(g, mult) / (1 + obj) ** _EXP).sum()


def momentum_residual(px):
    """Puntaje de momentum residual (el mismo del momentum mensual) y su percentil (0 = peor, 1 = mejor)."""
    per = px.index.to_period("M")
    rm = px.groupby(per).last().pct_change().iloc[-MESES_REG:]
    x = rm["SPY"].values
    sc = {}
    for t in TICKERS:
        if t not in rm:
            continue
        y = rm[t].values
        ok = ~np.isnan(y) & ~np.isnan(x)
        if ok.sum() < 24 or np.isnan(y[-12:-1]).any():
            continue
        b, a = np.polyfit(x[ok], y[ok], 1)
        e = y - a - b * x
        sd = np.nanstd(e[ok], ddof=1)
        if sd > 0:
            sc[t] = np.nansum(e[-12:-1]) / sd
    s = pd.Series(sc, dtype=float)
    return s, s.rank(pct=True)


def evaluar(m, precio, liq, fx, mom_pct=np.nan):
    """Filtros mínimos, checklist y valuación."""
    fin = m["tipo"] == "financiera"
    ko = []
    if m.get("error"):
        ko.append(m["error"])
    elif m["moneda"] in MONEDAS_EXCLUIDAS:
        ko.append(f"balances en {m['moneda']} (inflación alta, no comparables)")
    else:
        rn = "ROE" if fin else "ROIC"
        if not (m["rent_prom"] >= KO_ROIC):
            ko.append(f"{rn} promedio {fmt_p(m['rent_prom'])} (mínimo 12%)")
        if not fin:
            if m["deuda_ebitda"] > KO_DEUDA:
                ko.append(f"deuda neta {fmt_x(m['deuda_ebitda'])} el EBITDA (máximo 3x)")
            if not (m["caja_base"] > 0):
                ko.append("no genera caja (flujo de caja y ganancia promedio negativos)")
        if not (m["ventas_cagr"] >= KO_VENTAS):
            ko.append(f"ventas {fmt_p(m['ventas_cagr'])} anual (mínimo 5%)")
        if m["dilucion"] > KO_DILUCION:
            ko.append(f"emite {fmt_p(m['dilucion'])} más de acciones por año (máximo 3%)")
    liquida = pd.notna(liq) and liq >= VOL_MIN_USD
    if not liquida:
        ko.append("poco volumen operado (menos de USD 20 M por día)")
    m["ko"] = ko
    m["ko_fundamental"] = [k for k in ko if not k.startswith("poco volumen")]
    m["liquida"] = liquida
    m["pasa"] = not ko
    # valuación
    fy = g = er = pc = np.nan
    tasa = fx.get(m["moneda"])
    if not m.get("error") and tasa and m.get("mcap") and m["mcap"] > 0 and pd.notna(m.get("caja_base")):
        fy = m["caja_base"] * tasa / m["mcap"]
        if fy > 0.25 or fy < -0.5:
            fy = np.nan                              # dato dudoso (valor de mercado o moneda mal informados)
    if pd.notna(fy):
        v, ca = m.get("ventas_cagr"), m.get("crec_accion")
        if pd.notna(v):       # apoyado en las ventas; la caja por acción suma o resta como mucho 3 puntos
            g = v + (float(np.clip(ca - v, -0.03, 0.03)) if pd.notna(ca) else 0.0)
        else:
            g = ca if pd.notna(ca) else 0.0
        g = float(np.clip(g, 0, G_MAX))
        mult = MULT_SALIDA_FIN if fin else MULT_SALIDA
        er = tir_10(fy, g, mult)
        if fy > 0 and pd.notna(precio):
            pc = precio * fy / caja_necesaria(ER_MIN, g, mult)
    castigada = bool(pd.notna(mom_pct) and mom_pct < MOM_CORTE)
    m.update(fcf_yield=fy, crec_estimado=g, rend_esperado=er, precio=precio, precio_compra=pc, mom_pct=mom_pct,
             castigada=castigada)
    m["barata"] = bool(pd.notna(er) and er >= ER_MIN)
    m["comprable"] = False          # se define en armar_ranking (ranking combinado dentro del top 20)
    m["precio_extremo"] = bool(pd.notna(er) and er < EXTREMO_ER)
    if m.get("error"):
        m["checks"] = [None] * len(CHECKS)
    else:
        m["checks"] = [
            bool(m["rent_prom"] >= 0.15 and not m["rent_baja2"]),
            None if fin or pd.isna(m["mb_var"]) else bool(m["mb_var"] >= -0.01),
            bool(m["ventas_cagr"] >= 0.08) if pd.notna(m["ventas_cagr"]) else False,
            bool(m["crec_accion"] >= 0.10) if pd.notna(m["crec_accion"]) else False,
            None if fin else bool(m["deuda_ebitda"] < 2),
            None if fin or pd.isna(m["conversion"]) else bool(m["conversion"] >= 0.8),
            bool(m["dilucion"] <= 0.005) if pd.notna(m["dilucion"]) else None,
            bool(pd.notna(er) and er >= ER_MIN),
        ]
    return m


def armar_ranking(metricas):
    """DataFrame con todas las acciones; las que pasan los filtros, ordenadas por puntaje de calidad."""
    df = pd.DataFrame(metricas).set_index("Acción")
    p = df[df["pasa"]].copy()
    if len(p):
        r = lambda s, asc=True: pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan).rank(pct=True, ascending=asc).fillna(0.5)
        mb = (r(p["mb_prom"]) + r(p["mb_var"])) / 2
        puntaje = (0.25 * r(p["rent_prom"]) + 0.15 * r(p["ventas_cagr"]) + 0.15 * r(p["crec_accion"]) + 0.10 * mb
                   + 0.10 * r(p["conversion"]) + 0.10 * r(p["deuda_ebitda"], asc=False) + 0.05 * r(p["dilucion"], asc=False)
                   + 0.10 * r(p["rend_esperado"]))
        p["Puntaje"] = (puntaje * 100).round(1)
        p = p.sort_values("Puntaje", ascending=False)
        p["Puesto"] = range(1, len(p) + 1)
        # ranking combinado entre las 20 mejores en calidad
        pool = p[p["Puesto"] <= BUFFER].copy()
        wq, wv, wm = PESOS_COMB
        rv = pd.to_numeric(pool["rend_esperado"], errors="coerce").rank(pct=True).fillna(0)
        rm_ = pd.to_numeric(pool["mom_pct"], errors="coerce").rank(pct=True).fillna(0.5)
        pool["Combinado"] = ((wq * pool["Puntaje"].rank(pct=True) + wv * rv + wm * rm_) * 100).round(1)
        pool["elegible"] = pool["rend_esperado"].notna() & ~pool["precio_extremo"].astype(bool) & ~pool["castigada"].astype(bool)
        pool = pool.sort_values("Combinado", ascending=False)
        orden = 0
        for t in pool.index:
            if pool.loc[t, "elegible"]:
                orden += 1
                pool.loc[t, "Orden"] = orden
        p["Combinado"] = pool["Combinado"]
        p["Orden"] = pool.get("Orden")
        p["comprable"] = p["Orden"].notna()
    resto = df[~df["pasa"]].copy()
    resto["Puntaje"], resto["Puesto"] = np.nan, np.nan
    out = pd.concat([p, resto])
    for k in ("Combinado", "Orden"):
        if k not in out:
            out[k] = np.nan
    out["comprable"] = out["comprable"].fillna(False).astype(bool)
    out["Sector"] = [sector(t) for t in out.index]
    out["Cumple"] = [sum(1 for c in cs if c) for cs in out["checks"]]
    out["Aplica"] = [sum(1 for c in cs if c is not None) for cs in out["checks"]]
    return out


# ============================================================================ cartera
def estado_nuevo():
    return {"version": 1, "capital": CAPITAL_REF, "inicio": None, "ultima_fecha": None, "ultima_oficial": None, "caja": CAPITAL_REF,
            "spy_ref": CAPITAL_REF, "posiciones": {}, "operaciones": [], "cerradas": [], "evolucion": []}


def cargar_estado():
    if os.path.exists(ESTADO):
        with open(ESTADO, encoding="utf-8") as fh:
            return json.load(fh)
    return estado_nuevo()


def guardar_estado(E):
    with open(ESTADO, "w", encoding="utf-8") as fh:
        json.dump(E, fh, ensure_ascii=False, indent=1, default=lambda o: None if pd.isna(o) else float(o))


def _px_al(px, t, d):
    s = px[t].loc[:pd.Timestamp(d)].dropna() if t in px else pd.Series(dtype=float)
    return s.iloc[-1] if len(s) else np.nan


def actualizar_valores(E, px):
    """Lleva cada posición (y la liquidez estacionada en SPY) del último registro a hoy."""
    E = copy.deepcopy(E)
    hoy_px = px.index[-1]
    if E["ultima_fecha"]:
        d0 = E["ultima_fecha"]
        f_spy = px["SPY"].iloc[-1] / _px_al(px, "SPY", d0)
        for t, p in E["posiciones"].items():
            a, b = _px_al(px, t, d0), (px[t].dropna().iloc[-1] if t in px and px[t].notna().any() else np.nan)
            if pd.notna(a) and pd.notna(b) and a > 0:
                p["valor"] *= b / a
        E["caja"] *= f_spy
        E["spy_ref"] *= f_spy
    E["ultima_fecha"] = hoy_px.strftime("%Y-%m-%d")
    return E


def rel_vs_spy(px, t, desde):
    a, b = _px_al(px, t, desde), px[t].dropna().iloc[-1] if t in px and px[t].notna().any() else np.nan
    sa, sb = _px_al(px, "SPY", desde), px["SPY"].iloc[-1]
    if any(pd.isna(x) for x in (a, b, sa)) or a <= 0:
        return np.nan, np.nan
    return b / a - 1, (b / a) / (sb / sa) - 1


def evaluar_tesis(t, pos, rk, px):
    """Devuelve dict con estado (ROTA / REVISAR / INTACTA / SIN DATOS), motivos y alarma de precio."""
    rend, rel = rel_vs_spy(px, t, pos["fecha_entrada"])
    alarma = pd.notna(rel) and rel <= ALARMA_REL
    out = {"rend": rend, "rel": rel, "alarma": alarma, "motivos": [], "estado": "INTACTA"}
    if t not in rk.index or isinstance(rk.loc[t, "error"], str):
        out["estado"] = "SIN DATOS"
        out["motivos"].append("no llegaron sus balances este mes: no se toma ninguna decisión")
        return out
    r = rk.loc[t]
    if r["ko_fundamental"]:
        out["estado"] = "ROTA"
        out["motivos"] += r["ko_fundamental"]
        return out
    ent = pos.get("tesis", {})
    rn = "ROE" if r["tipo"] == "financiera" else "ROIC"
    if r["rent_baja2"]:
        out["motivos"].append(f"el {rn} bajó 2 años seguidos ({fmt_p(r['rent_ini'])} → {fmt_p(r['rent_ult'])})")
    if pd.notna(ent.get("mb_ult")) and pd.notna(r["mb_ult"]) and r["mb_ult"] < ent["mb_ult"] - 0.03:
        out["motivos"].append(f"margen bruto cayó de {fmt_p(ent['mb_ult'])} a {fmt_p(r['mb_ult'])} desde la compra")
    if not r["liquida"]:
        out["motivos"].append("bajó mucho el volumen operado")
    out["solo_alarma"] = bool(alarma and not out["motivos"])
    if alarma:
        out["motivos"].append(f"cae {fmt_p(-rel)} contra el S&P desde la compra")
    if out["motivos"]:
        out["estado"] = "REVISAR"
    return out


def _snapshot(r, fecha):
    return {k: (None if pd.isna(r.get(k)) else float(r.get(k))) if not isinstance(r.get(k), str) else r.get(k)
            for k in ("rent_prom", "rent_ult", "mb_ult", "ventas_cagr", "crec_accion", "deuda_ebitda", "dilucion",
                      "rend_esperado", "Puntaje", "Puesto")} | {"fecha": fecha, "tipo": r.get("tipo")}


def aplicar_reglas(E, rk, px, hoy, revision):
    """Aplica las reglas del mes sobre el estado ya actualizado a hoy. Devuelve (estado, órdenes, cerradas, tesis)."""
    E = copy.deepcopy(E)
    P = E["posiciones"]
    fecha = hoy.isoformat()
    ords, cerradas = [], []
    total = lambda: E["caja"] + sum(p["valor"] for p in P.values())
    for t, p in P.items():      # posiciones cargadas a mano (por ejemplo, desde el backtest): se toma la foto de hoy
        if not p.get("tesis") and t in rk.index and not isinstance(rk.loc[t, "error"], str):
            p["tesis"] = _snapshot(rk.loc[t], fecha)
    tesis = {t: evaluar_tesis(t, p, rk, px) for t, p in P.items()}

    def vender(t, motivo, tipo="VENDER"):
        p = P.pop(t)
        v = p["valor"]
        E["caja"] += v * (1 - COSTO)
        res = v * (1 - COSTO) / p["costo"] - 1
        ords.append({"Orden": tipo, "Acción": t, "Monto": v, "Resultado": res, "Motivo": motivo})
        cerradas.append({"Acción": t, "Sector": sector(t), "Compra": p["fecha_entrada"], "Venta": fecha,
                         "Invertido": p["costo"], "Cobrado": v * (1 - COSTO), "Resultado": res, "Motivo": motivo})

    def comprar(t, monto, motivo, tipo="COMPRAR"):
        r = rk.loc[t]
        P[t] = {"valor": monto * (1 - COSTO), "costo": monto, "fecha_entrada": fecha, "tesis": _snapshot(r, fecha)}
        E["caja"] -= monto
        ords.append({"Orden": tipo, "Acción": t, "Monto": monto, "Resultado": np.nan, "Motivo": motivo})

    def cabe(t, sin=None):
        return sum(1 for x in P if grupo(x) == grupo(t) and x != sin) < MAX_SECTOR

    # 1. Tesis rota → vender
    for t in list(P):
        if tesis[t]["estado"] == "ROTA":
            vender(t, "Tesis rota: " + "; ".join(tesis[t]["motivos"]))
    # 2. Rotación por mejor oportunidad (solo en revisiones trimestrales)
    candidatas = [t for t in rk[rk["comprable"]].sort_values("Orden").index if t not in P]
    desc = lambda c: (f"orden {int(rk.loc[c, 'Orden'])} del ranking combinado (puesto {int(rk.loc[c, 'Puesto'])} de calidad, "
                      f"rendimiento esperado {fmt_p(rk.loc[c, 'rend_esperado'])})")
    if revision:
        debiles = [t for t in P if tesis[t]["estado"] in ("INTACTA", "REVISAR") and pd.notna(rk.loc[t, "Puesto"])
                   and rk.loc[t, "Puesto"] > BUFFER]
        debiles.sort(key=lambda t: -rk.loc[t, "Puesto"])
        for t in debiles[:ROT_MAX]:
            for c in candidatas:
                if cabe(c, sin=t):
                    v = P[t]["valor"]
                    vender(t, f"Rotación: cayó al puesto {int(rk.loc[t, 'Puesto'])} de calidad (fuera del top {BUFFER}); "
                              f"entra {c}", "ROTAR (vender)")
                    comprar(c, v * (1 - COSTO), f"Reemplaza a {t}: {desc(c)}", "ROTAR (comprar)")
                    candidatas.remove(c)
                    break
    # 3. Recortes
    for t in list(P):
        tot, v = total(), P[t]["valor"]
        w = v / tot
        destino = None
        if w > TOPE:
            destino, motivo = RECORTE_A, f"Pesa {fmt_p(w, 0)} de la cartera (tope 25%): baja a 20%"
        elif t in rk.index and rk.loc[t, "precio_extremo"] and w > EXTREMO_PESO:
            destino, motivo = EXTREMO_A, (f"Precio extremo (rendimiento esperado a 10 años de {fmt_p(rk.loc[t, 'rend_esperado'])}) "
                                          f"y pesa {fmt_p(w, 0)}: baja a 10%")
        if destino:
            vend = v - tot * destino
            P[t]["valor"] -= vend
            P[t]["costo"] *= (1 - vend / v)
            E["caja"] += vend * (1 - COSTO)
            ords.append({"Orden": "RECORTAR", "Acción": t, "Monto": vend, "Resultado": np.nan, "Motivo": motivo})
    # 4. Completar las 10
    tot = total()
    inicial = len(P) == 0
    nuevas = []
    for c in candidatas:
        if len(P) + len(nuevas) >= TOP:
            break
        if sum(1 for x in list(P) + nuevas if grupo(x) == grupo(c)) < MAX_SECTOR:
            nuevas.append(c)
    if nuevas:
        m_cada = min(tot * OBJ, E["caja"] / len(nuevas))
        for c in nuevas:
            m = min(m_cada, E["caja"])
            if m <= 1:
                break
            comprar(c, m, ("Compra inicial: " if inicial else "Lugar libre: ") + desc(c))
    # 5. Sobrante: completar hacia el 10% las posiciones con la tesis intacta que el mercado no está castigando
    obj = tot * OBJ
    sumas = {}
    castig = lambda t: bool(t in rk.index and rk.loc[t, "castigada"])
    while E["caja"] > 1:
        ok = [t for t in P if tesis.get(t, {"estado": "INTACTA"})["estado"] == "INTACTA" and not castig(t)
              and P[t]["valor"] < obj - 0.015 * tot]
        if not ok:
            break
        ok.sort(key=lambda t: P[t]["valor"])
        t = ok[0]
        m = min(obj - P[t]["valor"], E["caja"])
        if m < 0.01 * tot:          # órdenes de menos de 1% de la cartera no valen la pena
            break
        P[t]["valor"] += m * (1 - COSTO)
        P[t]["costo"] += m
        E["caja"] -= m
        sumas[t] = sumas.get(t, 0) + m
    for t, m in sumas.items():
        ords.append({"Orden": "SUMAR", "Acción": t, "Monto": m, "Resultado": np.nan,
                     "Motivo": "Posición chica: se completa hacia el 10%"})
    orden = {"VENDER": 0, "ROTAR (vender)": 1, "RECORTAR": 2, "ROTAR (comprar)": 3, "COMPRAR": 4, "REFORZAR": 5, "SUMAR": 6}
    ords.sort(key=lambda o: orden[o["Orden"]])
    return E, ords, cerradas, tesis


# ============================================================================ formatos
def fmt_p(v, dec=1):
    if v is None or pd.isna(v):
        return "—"
    if np.isinf(v):
        return "∞"
    return f"{v * 100:.{dec}f}%".replace(".", ",")


def fmt_x(v):
    if v is None or pd.isna(v):
        return "—"
    if np.isinf(v):
        return "EBITDA negativo"
    return f"{v:.1f}x".replace(".", ",")


def usd(v):
    return "USD " + f"{v:,.0f}".replace(",", ".")


def usd2(v):
    if v is None or pd.isna(v):
        return "—"
    return "USD " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fecha_larga(d):
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def leer_tesis_csv():
    if not os.path.exists(TESIS_CSV):
        return {}
    try:
        df = pd.read_csv(TESIS_CSV)
        df.columns = [c.strip().lower() for c in df.columns]
        return {str(r["ticker"]).strip().upper(): str(r.get("tesis", "")).strip() for _, r in df.iterrows()
                if str(r.get("tesis", "")).strip() not in ("", "nan")}
    except Exception as e:      # noqa: BLE001
        print("No se pudo leer", TESIS_CSV, e)
        return {}


# ============================================================================ salidas
def generar_pdf(ruta, ctx):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    cart, rk, ords, tes = ctx["cartera"], ctx["rk"], ctx["ordenes"], ctx["tesis"]
    AZUL = colors.HexColor("#1F3864"); GRIS = colors.HexColor("#F2F2F2"); CAJA = colors.HexColor("#EEF3FA")
    VER, ROJ, NAR, GRI, AZ2 = "#1e7b3a", "#b3261e", "#b76e00", "#555555", "#1f5fa8"
    ss = getSampleStyleSheet()
    T = ParagraphStyle("t", parent=ss["Title"], textColor=AZUL, fontSize=18, leading=22, alignment=0, spaceAfter=0)
    S = ParagraphStyle("s", parent=ss["Normal"], textColor=colors.grey, fontSize=9, spaceAfter=8)
    H = ParagraphStyle("h", parent=ss["Heading2"], textColor=AZUL, fontSize=12.5, spaceBefore=10, spaceAfter=5)
    N = ParagraphStyle("n", parent=ss["Normal"], fontSize=9.5, leading=13, spaceAfter=4)
    B = ParagraphStyle("b", parent=N, leftIndent=12, bulletIndent=0, spaceAfter=2)
    C = ParagraphStyle("c", parent=N, fontSize=8, leading=10, spaceAfter=0)
    CB = ParagraphStyle("cb", parent=C, fontName="Helvetica-Bold", textColor=colors.white)
    K1 = ParagraphStyle("k1", parent=N, fontSize=8, textColor=colors.grey, alignment=1, spaceAfter=0)
    K2 = ParagraphStyle("k2", parent=N, fontSize=14, leading=17, fontName="Helvetica-Bold", alignment=1, spaceAfter=0)
    NOTA = ParagraphStyle("nota", parent=N, fontSize=7.5, leading=9.5, textColor=colors.grey)
    col = lambda c, s_: f"<font color='{c}'>{s_}</font>"
    b = lambda t_: Paragraph(t_, B, bulletText="•")
    esc = lambda s_: str(s_).replace("&", "&amp;")
    pc = lambda v, d=1: "—" if v is None or pd.isna(v) else col(VER if v >= 0 else ROJ, ("+" if v >= 0 else "") + fmt_p(v, d))
    capital = ctx["valor"]
    base = ctx["valor_antes"] or capital

    def lab(t_):
        extra = f" · CEDEAR <b>{cedear(t_)}</b>" if cedear(t_) != t_ else ""
        return f"<b>{t_}</b><br/><font size='6.5' color='#555555'>{nombre(t_)}{extra}</font>"

    def tabla(data, widths, fondos=None):
        rows = [[Paragraph(str(v), CB if i == 0 else C) for v in r] for i, r in enumerate(data)]
        t_ = Table(rows, colWidths=widths, repeatRows=1)
        st = [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
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

    # gráficos
    fig, ax = plt.subplots(figsize=(8.2, 2.3), dpi=150)
    if len(cart):
        etiquetas = list(cart["Acción"]) + (["SPY*"] if ctx["caja_w"] > 0.005 else [])
        pesos = list(cart["Peso"] * 100) + ([ctx["caja_w"] * 100] if ctx["caja_w"] > 0.005 else [])
        colores = [ROJ if w > TOPE * 100 else AZ2 for w in pesos[:len(cart)]] + ["#9e9e9e"] * (len(pesos) - len(cart))
        ax.bar(etiquetas, pesos, color=colores)
        ax.axhline(OBJ * 100, color="#2e7d32", lw=1, ls="--")
        ax.axhline(TOPE * 100, color="#c0392b", lw=1, ls=":")
        ax.text(len(pesos) - 0.5, OBJ * 100 + 0.4, "objetivo 10%", fontsize=7, color="#2e7d32", ha="right")
        ax.text(len(pesos) - 0.5, TOPE * 100 + 0.4, "tope 25%", fontsize=7, color="#c0392b", ha="right")
        ax.set_ylim(0, max(28, max(pesos) + 3))
    ax.set_ylabel("% de la cartera", fontsize=8)
    ax.tick_params(labelsize=7.5)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig("cal_pesos.png"); plt.close(fig)
    evo = ctx["evolucion"]
    if len(evo) >= 3:
        fig, ax = plt.subplots(figsize=(8.2, 2.6), dpi=150)
        ax.plot(evo.index, evo["cartera"], color=AZ2, lw=2, marker="o", ms=3, label="Cartera de calidad")
        ax.plot(evo.index, evo["spy"], color="#8a8a8a", lw=1.5, marker="o", ms=2, label="Mismo dinero en el S&P 500")
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usd(v)))
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, fontsize=8, loc="upper left")
        ax.tick_params(labelsize=7); ax.grid(axis="y", color="#eeeeee")
        fig.tight_layout(); fig.savefig("cal_evo.png"); plt.close(fig)

    hoy, modo = ctx["hoy"], ctx["modo"]
    titulo = f"Cartera de calidad · {MESES[hoy.month - 1].capitalize()} {hoy.year}" + (" (consulta)" if modo == "CONSULTA" else "")
    sub = (f"{fecha_larga(hoy).capitalize()} · precios al cierre del {ctx['cierre'].strftime('%d/%m/%Y')}"
           + (" · revisión trimestral (se evalúan rotaciones)" if ctx["revision"] else "") + " · "
           + ("operar en los próximos días (desde mañana)" if modo == "OFICIAL" else
              f"<b>{col(NAR, 'CONSULTA: no queda registrado. Muestra qué haría el sistema si la revisión fuera hoy.')}</b>"))
    E = ctx["estado"]
    ini = E.get("inicio")
    gan = gan_s = np.nan
    if len(evo) >= 1 and ini:
        gan = capital / E.get("capital", CAPITAL_REF) - 1
        gan_s = ctx["spy_ref"] / E.get("capital", CAPITAL_REF) - 1
    story = [Paragraph(titulo, T), Paragraph(sub, S),
             kpis([("Cartera del sistema", usd(capital)),
                   ("Desde el inicio" if ini else "Inicio", pc(gan) if ini else "hoy"),
                   ("S&amp;P mismo período", pc(gan_s) if ini else "—"),
                   ("Empresas", str(len(cart))),
                   ("Órdenes", str(len(ords)))])]
    if ctx["correccion"] is not None and ctx["correccion"] <= -0.10:
        story += [Spacer(1, 6), Paragraph(
            f"<b>{col(ROJ, 'Mercado en corrección:')}</b> el S&amp;P está {fmt_p(-ctx['correccion'], 0)} debajo de su máximo del "
            "último año. Es momento de comprar, no de vender: los aportes y la liquidez van a las posiciones por debajo del 10% "
            "y a las de la lista de espera que ya estén cerca de su precio de compra.", N)]
    story += [Spacer(1, 6), Paragraph("1. Qué hacer" + (" (consulta)" if modo == "CONSULTA" else ""), H),
              Paragraph(f"Montos para una cartera de <b>{usd(base)}</b>. Para cada cliente usá la columna <b>% de la cartera</b>. "
                        "Primero las ventas, después las compras. No hace falta operar el mismo día: son decisiones de largo plazo.", N)]
    COLA = {"VENDER": ROJ, "ROTAR (vender)": ROJ, "RECORTAR": NAR, "ROTAR (comprar)": VER, "COMPRAR": VER,
            "REFORZAR": AZ2, "SUMAR": AZ2}
    if ords:
        filas = [["#", "Orden", "Acción", "% cartera", "Monto", "Result.", "Motivo"]]
        for i, o in enumerate(ords, 1):
            filas.append([str(i), f"<b>{col(COLA[o['Orden']], o['Orden'])}</b>", lab(o["Acción"]),
                          fmt_p(o["Monto"] / base), usd(o["Monto"]), pc(o["Resultado"]), esc(o["Motivo"])])
        story.append(tabla(filas, [0.5 * cm, 2.1 * cm, 3.1 * cm, 1.4 * cm, 1.7 * cm, 1.4 * cm, 6.8 * cm]))
    else:
        story.append(Paragraph(f"<b>{col(VER, 'Este mes no hay que hacer nada.')}</b> Ninguna tesis se rompió, ninguna posición "
                               "pasa del 25% y no hay lugares libres. En una cartera de largo plazo, esto es lo normal.", N))
    story.append(Paragraph("Precios de referencia en dólares, de Nueva York. El CEDEAR sigue ese precio por el contado con liqui "
                           "dividido el ratio. Costos estimados: 0,5% por operación.", NOTA))
    revisar = [(t, x) for t, x in tes.items() if x["estado"] in ("REVISAR", "SIN DATOS")]
    story.append(Paragraph("2. Para revisar a mano (el sistema no vende por esto)", H))
    if revisar:
        for t, x in revisar:
            if x.get("solo_alarma"):
                txt = f"<b>{t}</b> ({nombre(t)}): {col(NAR, esc('; '.join(x['motivos'])))}. Los balances siguen bien, pero el mercado " \
                      "la está castigando: revisar si la historia del negocio sigue en pie. El sistema no sugiere comprar más; " \
                      "reforzar o vender es una decisión del equipo."
            elif x["estado"] == "SIN DATOS":
                txt = f"<b>{t}</b> ({nombre(t)}): {esc('; '.join(x['motivos']))}."
            else:
                txt = f"<b>{t}</b> ({nombre(t)}): {col(NAR, esc('; '.join(x['motivos'])))}. Revisar la tesis: si se confirma el " \
                      "deterioro, vender aunque todavía pase los filtros."
            story.append(b(txt))
    else:
        story.append(Paragraph("Nada: todas las posiciones tienen la tesis intacta y ninguna cae más de 25% contra el S&amp;P.", N))

    faltan = cart[cart["Peso"] < OBJ - 0.003].copy()
    castig = lambda t: bool(t in rk.index and rk.loc[t, "castigada"])
    faltan = faltan.loc[np.array([tes.get(t, {"estado": "INTACTA"})["estado"] == "INTACTA" and not castig(t)
                                  for t in faltan["Acción"]], dtype=bool)]
    faltan = faltan.sort_values("Peso")
    story.append(Paragraph("3. Si entra plata (aportes o clientes nuevos)", H))
    if len(faltan):
        partes = [f"<b>{r['Acción']}</b> hasta {fmt_p(OBJ - r['Peso'])} de la cartera" for _, r in faltan.iterrows()]
        story.append(Paragraph("<b>Aportes:</b> en este orden hasta que se termine: " + " · ".join(partes) +
                               ". Si todas llegan al 10%, repartí el resto en partes iguales.", N))
    else:
        story.append(Paragraph("<b>Aportes:</b> todas están cerca del 10%: repartilo en partes iguales entre las posiciones.", N))
    story.append(Paragraph("<b>Clientes nuevos:</b> que entren en 3 tramos (un tercio ahora, otro en un mes y el último al mes "
                           "siguiente o antes si el mercado cae 10%), comprando la cartera de la sección 4 en partes iguales.", N))

    # cartera
    filas = [["Acción", "Sector", "Desde", "Peso", "Result.", "vs S&amp;P", "Puesto", "Rend. 10 años", "Tesis"]]
    fondos = []
    ETQ = {"INTACTA": col(VER, "✓ intacta"), "REVISAR": col(NAR, "⚠ revisar"), "SIN DATOS": col(GRI, "sin datos"),
           "NUEVA": col(VER, "NUEVA")}
    for i, (_, r) in enumerate(cart.iterrows(), 1):
        filas.append([lab(r["Acción"]), r["Sector"], pd.Timestamp(r["Desde"]).strftime("%d/%m/%y"), fmt_p(r["Peso"]),
                      pc(r["Resultado"]), pc(r["vs S&P"]), "—" if pd.isna(r["Puesto"]) else str(int(r["Puesto"])),
                      fmt_p(r["Rend. esperado"]), ETQ.get(r["Tesis"], r["Tesis"])])
        if r["Tesis"] == "NUEVA":
            fondos.append((i, colors.HexColor("#E2EFDA")))
    bloque = [Paragraph("4. Cartera del sistema después de operar", H)]
    if len(cart):
        bloque += [tabla(filas, [3.3 * cm, 2.5 * cm, 1.4 * cm, 1.2 * cm, 1.5 * cm, 1.5 * cm, 1.2 * cm, 1.5 * cm, 2.9 * cm], fondos)]
    else:
        bloque += [Paragraph("Sin posiciones: ninguna empresa cumple hoy calidad y precio a la vez.", N)]
    if ctx["caja_w"] > 0.005:
        bloque.append(Paragraph(f"* {fmt_p(ctx['caja_w'])} de la cartera queda estacionado en SPY (S&amp;P 500) hasta que "
                                "aparezca una empresa de calidad a buen precio.", NOTA))
    bloque.append(Image("cal_pesos.png", width=16.5 * cm, height=4.6 * cm))
    story += [PageBreak()] + bloque
    b5 = [Paragraph("5. Cómo viene", H)]
    if len(evo) >= 3:
        b5.append(Image("cal_evo.png", width=17 * cm, height=5.4 * cm))
    else:
        b5.append(Paragraph("La cartera recién arranca: el gráfico contra el S&amp;P aparece a partir del tercer mes.", N))
    story.append(KeepTogether(b5))

    # ranking
    pasan = rk[rk["pasa"]]
    en_cart = set(cart["Acción"])
    filas = [["#", "Acción", "Sector", "Punt.", "ROIC", "Ventas", "Deuda", "Rend. 10 años", "Tend.", "Crit.", "Situación"]]
    fondos = []

    def tend(r):
        if pd.isna(r["mom_pct"]):
            return "—"
        return col(ROJ, "castig.") if r["castigada"] else f"{r['mom_pct'] * 100:.0f}"

    for i, (t_, r) in enumerate(pasan.head(20).iterrows(), 1):
        if t_ in en_cart:
            sit, fondos = col(AZ2, "en cartera"), fondos + [(i, CAJA)]
        elif r["comprable"]:
            sit = col(VER, f"comprable (orden {int(r['Orden'])})")
        elif r["castigada"]:
            sit = col(NAR, "tendencia muy débil")
        elif r["precio_extremo"]:
            sit = col(NAR, "precio extremo")
        elif r["Puesto"] > BUFFER:
            sit = f"fuera del top {BUFFER}"
        else:
            sit = "sin dato de precio"
        rn = fmt_p(r["rent_prom"], 0) + (" ROE" if r["tipo"] == "financiera" else "")
        filas.append([str(int(r["Puesto"])), lab(t_), r["Sector"], f"{r['Puntaje']:.0f}", rn, fmt_p(r["ventas_cagr"], 0),
                      "—" if r["tipo"] == "financiera" else fmt_x(r["deuda_ebitda"]),
                      fmt_p(r["rend_esperado"]), tend(r), f"{r['Cumple']}/{r['Aplica']}", sit])
    ko_cnt = {}
    for k in rk.loc[~rk["pasa"], "ko"]:
        for x in k:
            clave = ("ROIC/ROE bajo" if x.startswith(("ROIC", "ROE")) else "mucha deuda" if x.startswith("deuda") else
                     "no genera caja" if x.startswith("no genera") else "ventas que no crecen" if x.startswith("ventas") else
                     "mucha dilución" if x.startswith("emite") else "poco volumen" if x.startswith("poco") else "sin datos")
            ko_cnt[clave] = ko_cnt.get(clave, 0) + 1
    embudo = ", ".join(f"{k}: {v}" for k, v in sorted(ko_cnt.items(), key=lambda z: -z[1]))
    story += [PageBreak(), Paragraph("6. Ranking de calidad (top 20)", H),
              Paragraph(f"De {len(rk)} acciones con CEDEAR, <b>{len(pasan)}</b> pasan los filtros mínimos. De las {BUFFER} mejores "
                        f"en calidad, <b>{int(pasan['comprable'].sum())}</b> son comprables (sin precio extremo ni tendencia en el 10% "
                        f"más bajo); se compran en el orden del ranking combinado: 50% calidad, 25% precio y 25% tendencia. "
                        f"Quedaron afuera por: {embudo}.", N),
              tabla(filas, [0.6 * cm, 2.9 * cm, 2.4 * cm, 1.0 * cm, 1.3 * cm, 1.2 * cm, 1.1 * cm, 1.4 * cm, 1.4 * cm, 1.1 * cm, 2.6 * cm], fondos),
              Paragraph("ROIC: rentabilidad sobre el capital invertido, promedio (bancos: ROE). Ventas: crecimiento anual. "
                        "Deuda: deuda neta sobre EBITDA. Rend. 10 años: rendimiento anual esperado comprando hoy y vendiendo en 10 años, "
                        "con base en el promedio de flujo de caja y ganancia, y el crecimiento de las ventas frenándose con los años. "
                        "Tend.: percentil de momentum residual entre las acciones con CEDEAR (100 = mejor); “castig.” = 10% más "
                        "bajo, no se compra hasta que se recupere. Crit.: criterios de referencia que cumple (detalle en el Excel).", NOTA)]
    espera = pasan[(~pasan["comprable"]) & (pasan["Puesto"] <= BUFFER) & ~pasan.index.isin(list(en_cart))]
    if len(espera):
        filas = [["Acción", "Puesto", "Precio hoy", "Precio de compra", "Tiene que bajar", "Rend. 10 años", "Qué espera"]]
        for t_, r in espera.iterrows():
            baja = 1 - r["precio_compra"] / r["precio"] if r["precio"] else np.nan
            motivo = []
            if r["precio_extremo"] or pd.isna(r["rend_esperado"]):
                motivo.append("que baje el precio")
            if r["castigada"]:
                motivo.append("que la tendencia se recupere")
            filas.append([lab(t_), str(int(r["Puesto"])), usd2(r["precio"]), usd2(r["precio_compra"]),
                          fmt_p(baja, 0) if pd.notna(baja) and baja > 0 else "—", fmt_p(r["rend_esperado"]),
                          " y ".join(motivo).capitalize()])
        story.append(KeepTogether([Paragraph("7. Lista de espera", H),
                                   Paragraph(f"Están entre las {BUFFER} mejores en calidad pero hoy no se pueden comprar. Precio de compra = "
                                             "precio al que rendiría 10% anual a 10 años (referencia).", N),
                                   tabla(filas, [3.3 * cm, 1.3 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.0 * cm, 3.9 * cm])]))

    # tesis
    manual = ctx["tesis_manual"]
    filas = [["Acción", "Rentab. compra → hoy", "Margen bruto compra → hoy", "Ventas crec.", "Deuda", "Dilución", "Estado"]]
    for _, r in cart.iterrows():
        t_ = r["Acción"]
        pos = ctx["posiciones"].get(t_, {})
        ent = pos.get("tesis", {})
        a = rk.loc[t_] if t_ in rk.index else None
        g = lambda k: np.nan if a is None else a.get(k)
        filas.append([lab(t_), f"{fmt_p(ent.get('rent_prom'), 0)} → {fmt_p(g('rent_prom'), 0)}",
                      f"{fmt_p(ent.get('mb_ult'), 0)} → {fmt_p(g('mb_ult'), 0)}", fmt_p(g("ventas_cagr"), 0),
                      "—" if a is None or a["tipo"] == "financiera" else fmt_x(g("deuda_ebitda")), fmt_p(g("dilucion"), 1),
                      ETQ.get(r["Tesis"], r["Tesis"])])
    bl = [Paragraph("8. Tesis de cada posición", H),
          Paragraph("Qué se compró y cómo está hoy. <b>Se vende</b> si deja de cumplir un filtro mínimo: ROIC promedio menor a 12%, "
                    "deuda mayor a 3 veces el EBITDA, que no genere caja, ventas creciendo menos de 5% o dilución mayor a 3% anual. "
                    "<b>Se revisa a mano</b> si el ROIC baja 2 años seguidos, si el margen bruto cae más de 3 puntos desde la compra o si la "
                    "acción cae más de 25% contra el S&amp;P (el mercado puede estar viendo algo que los balances todavía no muestran).", N)]
    if len(cart):
        bl.append(tabla(filas, [3.3 * cm, 2.6 * cm, 3.0 * cm, 1.7 * cm, 1.9 * cm, 1.6 * cm, 2.9 * cm]))
    story.append(KeepTogether(bl))
    if manual and any(t_ in manual for t_ in cart["Acción"]):
        story.append(Paragraph("Tesis escrita por el equipo (archivo tesis_calidad.csv):", N))
        for t_ in cart["Acción"]:
            if t_ in manual:
                story.append(b(f"<b>{t_}</b>: {manual[t_]}"))
    elif len(cart):
        story.append(Paragraph("Tip: la ventaja competitiva y la gerencia no se pueden medir con números. Escriban la tesis de cada "
                               "empresa en el archivo tesis_calidad.csv del repositorio (columnas Ticker,Tesis) y va a aparecer acá "
                               "todos los meses.", NOTA))
    cer = ctx["cerradas"]
    if len(cer):
        filas = [["Acción", "Compra", "Venta", "Resultado", "Motivo"]]
        for _, r in cer.tail(8).iloc[::-1].iterrows():
            filas.append([lab(r["Acción"]), pd.Timestamp(r["Compra"]).strftime("%d/%m/%y"), pd.Timestamp(r["Venta"]).strftime("%d/%m/%y"),
                          pc(r["Resultado"]), r["Motivo"]])
        story.append(KeepTogether([Paragraph("9. Últimas ventas del sistema", H),
                                   tabla(filas, [3.3 * cm, 1.7 * cm, 1.7 * cm, 1.7 * cm, 8.6 * cm])]))
    story += [Paragraph("Las reglas", H),
              b("10 empresas, 10% cada una al comprar. Máximo 3 del mismo sector (tecnología y semiconductores cuentan juntas)."),
              b(f"Se compra entre las {BUFFER} mejores en calidad, en el orden del ranking combinado (50% calidad, 25% precio, 25% tendencia). "
                "Quedan afuera las de precio extremo (menos de 5% anual esperado a 10 años) y las del 10% de peor tendencia."),
              b("Se vende si la tesis se rompe. En febrero, mayo, agosto y noviembre, además, se cambia la empresa que cayó del "
                "puesto 20 de calidad por la mejor del ranking combinado (máximo 2 cambios)."),
              b("Se recorta si una posición pasa del 25% (baja a 20%) o si el precio es extremo (menos de 5% anual esperado a 10 años) "
                "y pesa más de 12,5% (baja a 10%)."),
              b("Nunca se vende solo porque bajó el precio, pero tampoco se compra más de una castigada: si cae más de 25% contra el "
                "S&amp;P, lo revisa el equipo. Las ganadoras se dejan correr."),
              Spacer(1, 6),
              Paragraph("Datos: balances anuales de la SEC de EE.UU. (últimos 5 años), con el mismo programa que el backtest; "
                        "quedan afuera las extranjeras que no presentan balances con normas de EE.UU. y seis empresas con datos poco confiables "
                        "(Ford, GM, JD, Alibaba, Baidu y NIO). "
                        "El flujo de caja se calcula descontando los pagos en "
                        "acciones a empleados. La “cartera del sistema” sigue las reglas sin aportes; cada cliente puede tener otros pesos. "
                        "Análisis cuantitativo con fines educativos: no reemplaza el análisis de cada empresa ni es una recomendación "
                        "de inversión.", NOTA)]

    def pie(c, d):
        c.saveState(); c.setFont("Helvetica", 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1.1 * cm, "Cartera de calidad · resumen mensual")
        c.drawRightString(19 * cm, 1.1 * cm, f"Página {d.page}"); c.restoreState()

    SimpleDocTemplate(ruta, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.5 * cm, bottomMargin=1.6 * cm,
                      title=titulo).build(story, onFirstPage=pie, onLaterPages=pie)


def exportar_excel(ruta, ctx):
    rk = ctx["rk"]
    with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
        def nombres(df, c="Acción"):
            if len(df) and c in df:
                df = df.copy()
                df.insert(df.columns.get_loc(c) + 1, "Empresa", [nombre(t) for t in df[c]])
                df.insert(df.columns.get_loc(c) + 2, "Código CEDEAR", [cedear(t) for t in df[c]])
            return df
        o = pd.DataFrame(ctx["ordenes"])
        if len(o):
            o["% de la cartera"] = o["Monto"] / (ctx["valor_antes"] or ctx["valor"]) * 100
            o["Resultado"] = o["Resultado"] * 100
            o = o.rename(columns={"Resultado": "Resultado %", "Monto": "Monto USD"})
            o = nombres(o)
        (o if len(o) else pd.DataFrame({"Sin órdenes este mes": []})).to_excel(xw, sheet_name="Órdenes", index=False)
        c = ctx["cartera"].copy()
        for k in ("Peso", "Resultado", "vs S&P", "Rend. esperado"):
            c[k] = c[k] * 100
        nombres(c).to_excel(xw, sheet_name="Cartera", index=False)
        cols = {"Puesto": "Puesto", "Puntaje": "Puntaje", "Sector": "Sector", "tipo": "Tipo", "rent_prom": "ROIC/ROE promedio %",
                "rent_ult": "ROIC/ROE último %", "mb_prom": "Margen bruto %", "mb_var": "Margen bruto variación pts",
                "ventas_cagr": "Ventas crec. anual %", "crec_accion": "Caja por acción crec. anual %",
                "deuda_ebitda": "Deuda neta / EBITDA", "conversion": "Conversión en caja %", "dilucion": "Dilución anual %",
                "fcf_yield": "Caja (prom. flujo y ganancia) / valor %", "crec_estimado": "Crecimiento estimado %",
                "rend_esperado": "Rend. esperado 10 años %", "mom_pct": "Tendencia (percentil 0-100)", "castigada": "Castigada por el mercado",
                "precio": "Precio USD", "precio_compra": "Precio para 10% anual USD", "comprable": "Comprable", "Combinado": "Ranking combinado", "Orden": "Orden de compra", "ultimo_balance": "Último balance",
                "moneda": "Moneda balances"}
        x = rk.reindex(columns=list(cols)).rename(columns=cols).copy()
        for k in cols.values():
            if k.endswith("%") or k.endswith("pts"):
                x[k] = pd.to_numeric(x[k], errors="coerce") * 100
        x["Comprable"] = ["Sí" if v else "" for v in x["Comprable"]]
        x["Castigada por el mercado"] = ["Sí" if v is True or v == 1 else "" for v in x["Castigada por el mercado"]]
        x["Tendencia (percentil 0-100)"] = pd.to_numeric(x["Tendencia (percentil 0-100)"], errors="coerce") * 100
        for i, nm in enumerate(CHECKS):
            x[nm] = [("✓" if cs[i] else "✗") if cs[i] is not None else "n/a" for cs in rk["checks"]]
        x["Queda afuera por"] = ["; ".join(k) for k in rk["ko"]]
        x["En cartera"] = ["Sí" if t in set(ctx["cartera"]["Acción"]) else "" for t in x.index]
        x.insert(0, "Empresa", [nombre(t) for t in x.index])
        x.insert(1, "Código CEDEAR", [cedear(t) for t in x.index])
        x = x.replace([np.inf, -np.inf], np.nan)
        x.to_excel(xw, sheet_name="Ranking completo", index_label="Acción")
        filas = []
        for t, p in ctx["posiciones"].items():
            ent = p.get("tesis", {})
            a = rk.loc[t] if t in rk.index else {}
            fila = {"Acción": t, "Compra": p["fecha_entrada"], "Estado": ctx["tesis"].get(t, {}).get("estado", "NUEVA"),
                    "Motivos": "; ".join(ctx["tesis"].get(t, {}).get("motivos", []))}
            for k, nm in (("rent_prom", "ROIC/ROE"), ("mb_ult", "Margen bruto"), ("ventas_cagr", "Ventas crec."),
                          ("crec_accion", "Caja/acción crec."), ("dilucion", "Dilución"), ("rend_esperado", "Rend. esperado")):
                fila[f"{nm} compra %"] = None if ent.get(k) is None else ent[k] * 100
                v = a.get(k) if len(a) else None
                fila[f"{nm} hoy %"] = None if v is None or pd.isna(v) else v * 100
            fila["Tesis escrita"] = ctx["tesis_manual"].get(t, "")
            filas.append(fila)
        nombres(pd.DataFrame(filas) if filas else pd.DataFrame({"Acción": []})).to_excel(xw, sheet_name="Tesis", index=False)
        h = pd.DataFrame(ctx["estado"].get("operaciones", []))
        if len(h) and "Resultado" in h:
            h["Resultado"] = pd.to_numeric(h["Resultado"], errors="coerce") * 100
            h = h.rename(columns={"Resultado": "Resultado %", "Monto": "Monto USD"})
        cer = ctx["cerradas"].copy()
        if len(cer):
            cer["Resultado"] = cer["Resultado"] * 100
            cer = cer.rename(columns={"Resultado": "Resultado %"})
        (nombres(h) if len(h) else pd.DataFrame({"Sin historial": []})).to_excel(xw, sheet_name="Historial de órdenes", index=False)
        (nombres(cer) if len(cer) else pd.DataFrame({"Sin ventas": []})).to_excel(
            xw, sheet_name="Ventas", index=False)
        ev = ctx["evolucion"].rename(columns={"cartera": "Cartera de calidad", "spy": "S&P 500"})
        (ev if len(ev) else pd.DataFrame({"Sin historia todavía": []})).to_excel(xw, sheet_name="Evolución")
        for ws in xw.sheets.values():
            for c_ in ws.columns:
                ws.column_dimensions[c_[0].column_letter].width = 16
            for fila in ws.iter_rows(min_row=2):
                for cel in fila:
                    if isinstance(cel.value, float):
                        cel.number_format = "#,##0.00"


def texto_mail(ctx):
    hoy, ords, cart = ctx["hoy"], ctx["ordenes"], ctx["cartera"]
    L = [f"Cartera de calidad · {MESES[hoy.month - 1]} {hoy.year}",
         "CONSULTA (no queda registrado): así quedaría si la revisión fuera hoy." if ctx["modo"] == "CONSULTA"
         else "Revisión mensual. Operar en los próximos días; primero las ventas, después las compras.", ""]
    if ctx["correccion"] is not None and ctx["correccion"] <= -0.10:
        L += [f"MERCADO EN CORRECCIÓN: el S&P está {fmt_p(-ctx['correccion'], 0)} debajo de su máximo. Momento de comprar, no de vender.", ""]
    if ords:
        base = ctx["valor_antes"] or ctx["valor"]
        L.append(f"ÓRDENES (% de la cartera; montos para una cartera de {usd(base)}):")
        for o in ords:
            L.append(f"  {o['Orden']:<15} {con_nombre(o['Acción'])}: {fmt_p(o['Monto'] / base)} ({usd(o['Monto'])}) · {o['Motivo']}")
    else:
        L.append("Este mes no hay que hacer nada.")
    rev = [(t, x) for t, x in ctx["tesis"].items() if x["estado"] in ("REVISAR", "SIN DATOS")]
    if rev:
        L += ["", "PARA REVISAR A MANO:"]
        L += [f"  {con_nombre(t)}: {'; '.join(x['motivos'])}" for t, x in rev]
    L += ["", "Cartera del sistema después de operar:"]
    L += [f"  {con_nombre(r['Acción'])}: {fmt_p(r['Peso'], 0)}" for _, r in cart.iterrows()]
    if ctx["caja_w"] > 0.005:
        L.append(f"  Liquidez estacionada en SPY: {fmt_p(ctx['caja_w'], 0)}")
    L += ["", "Adjuntos: resumen en PDF y detalle en Excel (ranking completo con todos los criterios)."]
    n = {k: sum(o["Orden"].startswith(k) for o in ords) for k in ("VENDER", "ROTAR (vender)", "COMPRAR", "RECORTAR", "REFORZAR")}
    partes = []
    if n["VENDER"]:
        partes.append(f"{n['VENDER']} venta" + ("s" if n["VENDER"] > 1 else ""))
    if n["ROTAR (vender)"]:
        partes.append(f"{n['ROTAR (vender)']} cambio" + ("s" if n["ROTAR (vender)"] > 1 else ""))
    if n["COMPRAR"]:
        partes.append(f"{n['COMPRAR']} compra" + ("s" if n["COMPRAR"] > 1 else ""))
    if n["RECORTAR"]:
        partes.append(f"{n['RECORTAR']} recorte" + ("s" if n["RECORTAR"] > 1 else ""))
    if n["REFORZAR"]:
        partes.append(f"{n['REFORZAR']} refuerzo" + ("s" if n["REFORZAR"] > 1 else ""))
    asunto = f"Calidad · {MESES[hoy.month - 1].capitalize()} {hoy.year} · " + (", ".join(partes) if partes else "sin cambios")
    if not ctx["posiciones_antes"] and ords:
        asunto = f"Calidad · {MESES[hoy.month - 1].capitalize()} {hoy.year} · compra inicial ({len(cart)} empresas)"
    if rev:
        asunto += f" · {len(rev)} para revisar"
    if ctx["modo"] == "CONSULTA":
        asunto = "CONSULTA · " + asunto
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


# ============================================================================ principal
def guardar_panel(ctx, rk, ruta="panel_calidad.json"):
    """Resumen de la última revisión para el dashboard (órdenes, tesis y ranking)."""
    num = lambda v: None if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))) else float(v)
    base = ctx.get("valor_antes") or ctx["valor"]
    pasan = rk[rk["pasa"]]
    rank = []
    for t, r in pasan.head(30).iterrows():
        rank.append({"Acción": t, "Puesto": int(r["Puesto"]), "Puntaje": num(r["Puntaje"]), "Orden": num(r.get("Orden")),
                     "Sector": r["Sector"], "tipo": r["tipo"], "Rentabilidad": num(r["rent_prom"]), "Ventas": num(r["ventas_cagr"]),
                     "Deuda": num(r["deuda_ebitda"]), "Rend10": num(r["rend_esperado"]), "Tendencia": num(r["mom_pct"]),
                     "comprable": bool(r["comprable"]), "castigada": bool(r["castigada"]), "precio_extremo": bool(r["precio_extremo"]),
                     "Precio": num(r["precio"]), "PrecioCompra": num(r["precio_compra"])})
    panel = {"fecha": ctx["hoy"].isoformat(), "modo": ctx["modo"], "revision_trimestral": bool(ctx["revision"]),
             "cierre": pd.Timestamp(ctx["cierre"]).strftime("%Y-%m-%d"), "correccion": num(ctx["correccion"]),
             "ordenes": [{"Orden": o["Orden"], "Acción": o["Acción"], "Peso": num(o["Monto"] / base), "Resultado": num(o["Resultado"]),
                          "Motivo": o["Motivo"]} for o in ctx["ordenes"]],
             "tesis": {t: {"estado": x["estado"], "motivos": x["motivos"], "rel": num(x["rel"])} for t, x in ctx["tesis"].items()},
             "ranking": rank, "total": int(len(rk)), "pasan": int(len(pasan)), "comprables": int(pasan["comprable"].sum())}
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(panel, fh, ensure_ascii=False, indent=1)


def ranking_sec_hoy(desde, hoy):
    """Ranking de hoy con los balances de la SEC: el mismo motor y el mismo universo que el backtest."""
    global TICKERS
    agente = os.environ.get("CALIDAD_SEC_AGENTE", "").strip()
    if not agente:
        raise RuntimeError("Falta la variable CALIDAD_SEC_AGENTE (nombre y mail para identificarse ante la SEC). "
                           "Cargala en GitHub → Settings → Secrets and variables → Actions → Variables.")
    print("Descargando precios...")
    close, adj, vol, spl = descargar_todo(TICKERS, "2006-01-01")   # igual que el backtest (incluye todos los splits)
    corte = pd.Timestamp(hoy)
    close, adj, vol = close[close.index <= corte], adj[adj.index <= corte], vol[vol.index <= corte]
    print("Descargando balances de la SEC...")
    sec = bajar_sec(TICKERS, agente)
    univ = [t for t in TICKERS if t in sec and t in adj.columns]
    print(f"Empresas con balances en la SEC: {len(univ)} de {len(TICKERS)}")
    if len(univ) < 0.6 * len(TICKERS):
        raise RuntimeError(f"La SEC devolvió datos de solo {len(univ)} empresas: no se toman decisiones. Probar más tarde.")
    TICKERS = univ                                    # igual que el backtest: el universo son las que tienen balances en la SEC
    B = {t: Balances(t, sec[t], spl.get(t, pd.Series(dtype=float))) for t in univ}
    dvol = (close[univ] * vol[univ]).rolling(30, min_periods=10).mean()
    d = adj.index[-1]
    mets, con_datos = metricas_sec(univ, B, close, d, {})
    print(f"Con 3 años de balances: {con_datos}")
    return adj, ranking_desde(mets, close, adj, dvol, d)


def ranking_yahoo_hoy(desde, hoy):
    """Versión anterior, con los balances de Yahoo (se usa solo si CALIDAD_FUENTE=yahoo)."""
    print("Descargando precios...")
    px, vo = descargar_precios(desde.strftime("%Y-%m-%d"))
    px, vo = px[px.index <= pd.Timestamp(hoy)], vo[vo.index <= pd.Timestamp(hoy)]
    liq = (px * vo).rolling(30, min_periods=10).mean().iloc[-1]
    print("Descargando balances (tarda unos minutos)...")
    fund = bajar_fundamentales(TICKERS)
    met = {}
    for t in TICKERS:
        inc, bal, cf, info = fund.get(t, (None, None, None, {}))
        try:
            met[t] = calcular_metricas(t, inc, bal, cf, info)
        except Exception as e:          # noqa: BLE001
            met[t] = {"Acción": t, "tipo": "empresa", "moneda": "USD", "mcap": None, "error": f"error al calcular ({e})"}
    con_datos = sum(1 for m in met.values() if not m.get("error"))
    print(f"Empresas con balances: {con_datos}/{len(TICKERS)}")
    if con_datos < 0.6 * len(TICKERS):
        raise RuntimeError(f"Yahoo devolvió balances de solo {con_datos} empresas: no se toman decisiones. Probar más tarde.")
    fx = descargar_fx({m["moneda"] for m in met.values()})
    precio_hoy = px.iloc[-1]
    _, mom_pct = momentum_residual(px)
    ev = [evaluar(met[t], precio_hoy.get(t, np.nan), liq.get(t, np.nan), fx, mom_pct.get(t, np.nan)) for t in TICKERS]
    rk = armar_ranking(ev)
    return px, rk


def main():
    hoy = hoy_ar()
    evento = os.environ.get("EVENTO", "")
    operar = os.environ.get("OPERAR", "0") == "1" or "--operar" in sys.argv
    E0 = cargar_estado()
    dia = es_dia_revision(hoy)
    if evento == "schedule" and not dia:
        print(f"{hoy}: no es el día de revisión (primer día hábil desde el {DIA_REVISION}). No se hace nada.")
        return
    ya = E0.get("ultima_oficial") and E0["ultima_oficial"][:7] == hoy.isoformat()[:7]
    oficial = operar or (evento == "schedule" and dia and not ya)
    modo = "OFICIAL" if oficial else "CONSULTA"
    revision = hoy.month in MESES_REVISION
    print(f"{hoy}: modo {modo}{' · revisión trimestral' if revision else ''}.")

    entradas = [p["fecha_entrada"] for p in E0["posiciones"].values()] + ([E0["ultima_fecha"]] if E0["ultima_fecha"] else [])
    desde = min([pd.Timestamp(hoy) - pd.Timedelta(days=4 * 365 + 30)] + [pd.Timestamp(d) - pd.Timedelta(days=10) for d in entradas])
    if FUENTE == "sec":
        px, rk = ranking_sec_hoy(desde, hoy)
    else:
        px, rk = ranking_yahoo_hoy(desde, hoy)

    E1 = actualizar_valores(E0, px)
    valor_antes = E1["caja"] + sum(p["valor"] for p in E1["posiciones"].values())
    E2, ords, cer, tesis = aplicar_reglas(E1, rk, px, hoy, revision)
    valor = E2["caja"] + sum(p["valor"] for p in E2["posiciones"].values())
    if not E2.get("inicio") and E2["posiciones"]:
        E2["inicio"] = hoy.isoformat()
    E2["operaciones"] = E2.get("operaciones", []) + [{"Fecha": hoy.isoformat(), "Peso": o["Monto"] / valor_antes if valor_antes else None,
                                                      **{k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in o.items()}}
                                                     for o in ords]
    E2["cerradas"] = E2.get("cerradas", []) + cer
    if E2["posiciones"]:
        E2["evolucion"] = E2.get("evolucion", []) + [{"fecha": hoy.isoformat(), "cartera": valor, "spy": E2["spy_ref"]}]
    E2["ultima_oficial"] = hoy.isoformat()
    if oficial:
        guardar_estado(E2)
        print("Cartera guardada en", ESTADO)

    nuevas = {o["Acción"] for o in ords if o["Orden"] in ("COMPRAR", "ROTAR (comprar)")}
    filas = []
    for t, p in E2["posiciones"].items():
        x = tesis.get(t)
        r = rk.loc[t] if t in rk.index else {}
        filas.append({"Acción": t, "Sector": sector(t), "Desde": p["fecha_entrada"], "Peso": p["valor"] / valor,
                      "Resultado": np.nan if t in nuevas else p["valor"] / p["costo"] - 1,
                      "vs S&P": np.nan if t in nuevas or x is None else x["rel"],
                      "Puesto": r.get("Puesto", np.nan) if len(r) else np.nan,
                      "Rend. esperado": r.get("rend_esperado", np.nan) if len(r) else np.nan,
                      "Tesis": "NUEVA" if t in nuevas else (x["estado"] if x else "NUEVA")})
    cart = pd.DataFrame(filas, columns=["Acción", "Sector", "Desde", "Peso", "Resultado", "vs S&P", "Puesto", "Rend. esperado", "Tesis"])
    cart = cart.sort_values("Peso", ascending=False)
    evo = pd.DataFrame(E2["evolucion"] if E2["posiciones"] else [], columns=["fecha", "cartera", "spy"])
    if len(evo):
        evo = evo.drop_duplicates("fecha", keep="last")
        evo.index = pd.to_datetime(evo.pop("fecha"))
    spy = px["SPY"]
    correccion = float(spy.iloc[-1] / spy.iloc[-252:].max() - 1) if len(spy) >= 30 else None
    ctx = dict(hoy=hoy, modo=modo, revision=revision, cierre=px.index[-1], cartera=cart, rk=rk, ordenes=ords, tesis=tesis,
               valor=valor, caja_w=E2["caja"] / valor if valor else 0, estado=E2, spy_ref=E2["spy_ref"],
               evolucion=evo, correccion=correccion, posiciones=E2["posiciones"], posiciones_antes=E0["posiciones"],
               cerradas=pd.DataFrame(E2["cerradas"]), tesis_manual=leer_tesis_csv(), valor_antes=valor_antes)
    guardar_panel(ctx, rk)
    ruta_x, ruta_p = f"calidad_{hoy.isoformat()}.xlsx", f"calidad_{hoy.isoformat()}.pdf"
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
