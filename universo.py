"""
UNIVERSO DE ACCIONES CON CEDEAR (compartido por calidad, momentum y el screener)
==============================================================================
Una sola lista para los tres programas y el dashboard, en universo.csv.

  * cedears_byma.csv  → el listado de CEDEARs de BYMA (código BYMA, ratio y símbolo en EE.UU.).
                        Cuando BYMA sume un CEDEAR nuevo, se agrega una línea acá.
  * universo.csv      → lo genera `python universo.py actualizar` (GitHub Actions, una vez por mes):
                        para cada CEDEAR mira en Yahoo si cotiza en EE.UU. y qué es (acción o ETF), el
                        sector, el volumen y la web de la empresa (para el logo); y en la SEC si presenta
                        balances (10-K de EE.UU., 20-F/40-F de extranjeras). Para las extranjeras estima
                        cuántas acciones ordinarias representa cada ADR.

Quedan afuera: ETF, acciones de Brasil que cotizan solo en B3, papeles sin cotización vigente en EE.UU.
(dados de baja) y extranjeras que solo cotizan fuera de bolsa. El filtro de volumen (USD 20 M por día) NO
se aplica acá: lo aplica cada estrategia en cada fecha, igual que en sus backtests.

Si universo.csv no existe, los programas usan su lista fija de siempre (139 acciones).
"""
import csv
import os
import re
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
ARCHIVO = os.path.join(AQUI, "universo.csv")
LISTADO = os.path.join(AQUI, "cedears_byma.csv")
CAMPOS = ["ticker", "nombre", "cedear", "ratio_cedear", "incluida", "motivo", "tipo", "sector", "industria", "pais",
          "bolsa", "volumen_usd", "formulario", "cik", "adr_ratio", "financiera", "dominio", "valor_mercado"]

# Sectores de Yahoo -> los de la app (tecnología y semiconductores van separados, como siempre)
SECTORES = {"Technology": "Tecnología", "Communication Services": "Comunicación",
            "Consumer Cyclical": "Consumo discrecional", "Consumer Defensive": "Consumo básico",
            "Financial Services": "Financiero", "Healthcare": "Salud", "Energy": "Energía",
            "Basic Materials": "Materiales y minería", "Industrials": "Industria", "Utilities": "Servicios públicos",
            "Real Estate": "Inmobiliario"}
INDUSTRIAS_SEMIS = {"Semiconductors", "Semiconductor Equipment & Materials"}
# Bancos, aseguradoras y casas de bolsa: se miden por ROE (sin deuda ni flujo de caja), como JPM o GS en la app.
INDUSTRIAS_FINANCIERAS = ("Banks", "Insurance", "Capital Markets", "Financial Conglomerates")
# Red de seguridad por si Yahoo no informa el tipo: ETF conocidos del listado (algunos, como GLD o USO, presentan
# 10-K en la SEC y podrían confundirse con empresas).
ETF_CONOCIDOS = set("ACWI ARKK BBAX BBCA BIB CIBR COPX CORN DIA EEM EFA ESGU ETHA EWJ EWY EWZ FXI GDX GLD GSG IBB IBIT "
                    "ICLN IEMG IEUR IJH ILF ITA IVE IVW IWM PSQ QQQ RSP SH SLV SMH SOYB SPHQ SPXL SPY TQQQ URA USO VEA "
                    "VIG VXX XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY XME".split())


# ============================================================================ lectura (la usan los programas)
_cache = None


def cargar():
    """Filas de universo.csv incluidas en el universo ([] si el archivo no existe)."""
    global _cache
    if _cache is None:
        _cache = []
        if os.path.exists(ARCHIVO):
            with open(ARCHIVO, encoding="utf-8") as fh:
                _cache = [r for r in csv.DictReader(fh) if r.get("incluida") == "1"]
    return _cache


def todas():
    """Todas las filas de universo.csv (incluidas o no), para el explorador."""
    if not os.path.exists(ARCHIVO):
        return []
    with open(ARCHIVO, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def cedears(con_balances=False):
    """{ticker en Yahoo: (nombre, código del CEDEAR)}. con_balances=True: solo las que presentan balances en la SEC."""
    return {r["ticker"]: (r["nombre"], r["cedear"]) for r in cargar() if not con_balances or r["formulario"]}


def sectores():
    return {r["ticker"]: r["sector"] for r in cargar() if r["sector"]}


def adr_ratios():
    out = {}
    for r in cargar():
        try:
            if r["adr_ratio"]:
                out[r["ticker"]] = float(r["adr_ratio"])
        except ValueError:
            pass
    return out


def financieras():
    return {r["ticker"] for r in cargar() if r["financiera"] == "1"}


def dominios():
    return {r["ticker"]: r["dominio"] for r in todas() if r.get("dominio")}


def aplicar(nombres_fijos, sector_fijo, adr_fijo=None, financieras_fijas=None, con_balances=False):
    """Para los programas: devuelve (CEDEARS, SECTOR, ADR_RATIO, FINANCIERAS) con el universo ampliado.
    Lo cargado a mano en cada programa manda (nombres, sectores, relaciones ADR confirmadas, financieras)."""
    u = cedears(con_balances)
    if not u:
        return nombres_fijos, sector_fijo, adr_fijo, financieras_fijas
    ced = {t: (nombres_fijos[t][0] if t in nombres_fijos else nom, cod) for t, (nom, cod) in u.items()}
    sec = dict(sectores())
    sec.update(sector_fijo)
    adr = None
    if adr_fijo is not None:
        adr = dict(adr_ratios())
        adr.update(adr_fijo)
    fin = None
    if financieras_fijas is not None:
        fin = set(financieras()) | set(financieras_fijas)
    return ced, sec, adr, fin


# ============================================================================ actualización (GitHub Actions)
MIN_ACCIONES = 100      # si quedan menos, algo falló en las descargas y no se reemplaza universo.csv
def _nombre_corto(n):
    n = (n or "").strip()
    n = re.sub(r",?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Co\.?|Company|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.B\. de C\.V\.|"
               r"S\.A\.|SA|AG|SE|Holdings?|Group|Ltda\.?|S\.p\.A\.|A/S|ASA|AB|Oyj|N\.V)\.?$", "", n)
    n = re.sub(r",?\s+(Inc\.?|Corp\.?|Ltd\.?|plc|Holdings?|Group)\.?$", "", n)
    return n.strip(" ,") or None


def _redondear_ratio(r):
    """Relación ADR estimada -> el valor 'redondo' más cercano si está a menos de 12%; si no, None (dudoso)."""
    if not r or r <= 0:
        return None
    candidatos = [1 / 10, 1 / 5, 1 / 4, 1 / 3, 1 / 2, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100]
    mejor = min(candidatos, key=lambda c: abs(r / c - 1))
    return round(mejor, 4) if abs(r / mejor - 1) <= 0.12 else None


def actualizar():
    import requests
    import pandas as pd
    import yfinance as yf

    agente = (os.environ.get("CALIDAD_SEC_AGENTE") or os.environ.get("SEC_USER_AGENT") or "").strip()
    if "@" not in agente:
        sys.exit("Falta CALIDAD_SEC_AGENTE (nombre y mail para identificarse ante la SEC).")

    def sec_get(url):
        for i in range(4):
            try:
                r = requests.get(url, headers={"User-Agent": agente, "Accept-Encoding": "gzip, deflate"}, timeout=60)
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 404:
                    return None
            except Exception as e:      # noqa: BLE001
                print("  SEC:", e)
            time.sleep(2 + 3 * i)
        return None

    with open(LISTADO, encoding="utf-8") as fh:
        listado = list(csv.DictReader(fh))
    previo = {r["cedear"]: r for r in todas()}
    print(f"CEDEARs en el listado de BYMA: {len(listado)}")

    # 1. precios de los últimos 6 meses de todos los candidatos, en una sola descarga
    cand = sorted({s for r in listado for s in r["eeuu"].split() if s})
    print(f"Bajando precios de {len(cand)} símbolos...")
    datos = yf.download(cand, period="6mo", interval="1d", auto_adjust=False, group_by="ticker", threads=True,
                        progress=False)
    hoy = pd.Timestamp.today().normalize()
    vigente, volumen, precio = {}, {}, {}
    for s in cand:
        try:
            df = datos[s].dropna(subset=["Close"])
        except (KeyError, TypeError):
            continue
        if len(df) >= 20:
            idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
            if (hoy - idx[-1]).days <= 10:
                vigente[s] = True
                volumen[s] = float((df["Close"] * df["Volume"]).tail(60).mean())
                precio[s] = float(df["Close"].iloc[-1])

    tick = sec_get("https://www.sec.gov/files/company_tickers_exchange.json")
    if not tick:
        sys.exit("No se pudo bajar el listado de la SEC.")
    cik_de = {r[2].upper().replace(".", "-"): int(r[0]) for r in tick["data"]}

    filas = []
    for i, r in enumerate(listado, 1):
        cod = r["codigo"]
        f = {k: "" for k in CAMPOS}
        f.update(cedear=cod, ratio_cedear=r["ratio"], incluida="0")
        if not r["eeuu"]:
            f["motivo"] = r["nota"] or "no cotiza en EE.UU."
            filas.append(f)
            continue
        s = next((x for x in r["eeuu"].split() if x in vigente), None)
        if not s:
            f.update(ticker=r["eeuu"].split()[0], motivo="sin cotización vigente en EE.UU. (dado de baja o mal mapeado)")
            filas.append(f)
            continue
        f.update(ticker=s, volumen_usd=round(volumen[s]))
        info = {}
        for intento in range(3):
            try:
                info = yf.Ticker(s).get_info() or {}
                break
            except Exception:       # noqa: BLE001
                time.sleep(3 * (intento + 1))
        if not info and cod in previo:          # Yahoo no respondió: se conserva lo de la vez anterior
            p = previo[cod]
            info = {"quoteType": p["tipo"], "longName": p["nombre"], "industry": p["industria"], "country": p["pais"],
                    "exchange": p["bolsa"], "_sector": p["sector"], "website": p["dominio"]}
        f["tipo"] = info.get("quoteType", "")
        f["nombre"] = _nombre_corto(info.get("shortName") or info.get("longName")) or s
        if info.get("longName") and len(info["longName"]) < 60:
            f["nombre"] = _nombre_corto(info["longName"]) or f["nombre"]
        f["industria"] = info.get("industry", "")
        f["sector"] = info.get("_sector") or ("Semiconductores" if f["industria"] in INDUSTRIAS_SEMIS
                                              else SECTORES.get(info.get("sector", ""), ""))
        f["pais"] = info.get("country", "")
        f["bolsa"] = info.get("exchange", "")
        web = (info.get("website") or "").lower()
        f["dominio"] = re.sub(r"^(https?://)?(www\.)?", "", web).split("/")[0]
        f["valor_mercado"] = round(info["marketCap"]) if isinstance(info.get("marketCap"), (int, float)) else ""
        f["financiera"] = "1" if (info.get("sector") == "Financial Services" and
                                  any(f["industria"].startswith(x) or x in f["industria"] for x in INDUSTRIAS_FINANCIERAS)) else "0"
        if f["tipo"] in ("ETF", "MUTUALFUND", "INDEX", "CRYPTOCURRENCY") or s in ETF_CONOCIDOS or cod in ETF_CONOCIDOS:
            f["motivo"] = "ETF (no es una empresa)"
            filas.append(f)
            continue
        if f["bolsa"] in ("PNK", "OQB", "OQX", "OTC"):
            f["motivo"] = "cotiza fuera de bolsa en EE.UU. (sin balances en la SEC)"
            filas.append(f)
            continue
        cik = cik_de.get(s.upper())
        if cik:
            f["cik"] = cik
            sub = sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json") or {}
            forms = [x.split("/")[0] for x in sub.get("filings", {}).get("recent", {}).get("form", [])]
            f["formulario"] = next((x for x in forms if x in ("10-K", "20-F", "40-F")), "")
            time.sleep(0.12)
            if f["formulario"] in ("20-F", "40-F"):
                # relación ADR = acciones ordinarias (SEC) x precio del ADR / valor de mercado (Yahoo)
                facts = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json") or {}
                acc = None
                for v in facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", []):
                    if acc is None or v.get("end", "") >= acc[0]:
                        acc = (v.get("end", ""), float(v["val"]))
                mcap = info.get("marketCap")
                if acc and mcap and precio.get(s):
                    rr = _redondear_ratio(acc[1] * precio[s] / mcap)
                    f["adr_ratio"] = "" if rr is None else rr
                time.sleep(0.12)
        f["incluida"] = "1"
        f["motivo"] = "" if f["formulario"] else "sin balances en la SEC: entra en momentum y screener, no en calidad"
        filas.append(f)
        if i % 25 == 0:
            print(f"  {i}/{len(listado)}")
        time.sleep(0.2)

    # una sola fila por ticker (algunas empresas tienen dos CEDEARs, por ejemplo IVW o VALE/VALE3)
    vistos, unicas = set(), []
    for f in filas:
        if f["incluida"] == "1" and f["ticker"] in vistos:
            f["incluida"], f["motivo"] = "0", "repetida (otro CEDEAR del mismo papel)"
        vistos.add(f["ticker"]) if f["incluida"] == "1" else None
        unicas.append(f)
    if sum(1 for f in unicas if f["incluida"] == "1") < MIN_ACCIONES:
        sys.exit(f"Quedaron menos de {MIN_ACCIONES} acciones: algo falló en las descargas. No se reemplaza universo.csv.")
    with open(ARCHIVO, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(unicas)
    inc = [f for f in unicas if f["incluida"] == "1"]
    print(f"\nUniverso: {len(inc)} acciones de {len(unicas)} CEDEARs")
    print(f"  con balances en la SEC: {sum(1 for f in inc if f['formulario'])} "
          f"(10-K: {sum(1 for f in inc if f['formulario'] == '10-K')}, extranjeras: {sum(1 for f in inc if f['formulario'] in ('20-F', '40-F'))})")
    print(f"  con más de USD 20 M diarios hoy: {sum(1 for f in inc if float(f['volumen_usd'] or 0) >= 20e6)}")
    ext_sin = [f["ticker"] for f in inc if f["formulario"] in ("20-F", "40-F") and not f["adr_ratio"]]
    if ext_sin:
        print(f"  extranjeras sin relación ADR estimada (quedan fuera de calidad salvo que se carguen a mano): {', '.join(ext_sin)}")
    from collections import Counter
    for m, n in Counter(f["motivo"] for f in unicas if f["incluida"] != "1").most_common():
        print(f"  afuera · {m}: {n}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "actualizar":
        actualizar()
    else:
        print(__doc__)
        u = cargar()
        print(f"universo.csv: {len(u)} acciones incluidas" if u else "No hay universo.csv: los programas usan su lista fija.")
