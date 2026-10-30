"""
Cálculos pesados del dashboard (momentum y reversión con su backtest desde 2010-2011, y el nivel de calidad de cada
acción), sin Streamlit, para poder hacerlos de madrugada en GitHub Actions (precalculo.py) y guardarlos en la carpeta
precalculo/. La app usa lo guardado si es del último cierre y solo calcula en vivo si falta.
"""
import hashlib
import io
import json
import threading
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import calidad as C
import momentum as M
import screener as SCR

RAIZ = Path(__file__).resolve().parent
CARPETA = RAIZ / "precalculo"
INICIO_BACKTEST_MOM = "2011-01-03"


_CANDADO_MOM = threading.Lock()      # momentum.py usa una variable global para la fecha de inicio: un cálculo por vez


def datos_momentum(inicio_real):
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


def simular_cartera_rev(ops, reg, px, spy, liquidez_spy, niveles=None):
    """Cartera de 10 lugares: cada señal entra con 1/10 del valor total si hay lugar libre; sale según la regla.
    Si el mismo día hay más señales que lugares, entran primero las Premium, después las Sólidas y al final las Especulativas."""
    niveles = niveles or {}
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
        for oid in sorted(entradas.get(i, []), key=lambda o: (PRIORIDAD_NIVEL.get(niveles.get(ops.loc[o, "Ticker"]), 3),
                                                              ops.loc[o, "Ticker"])):
            if len(pos) >= LUGARES_REV:
                break
            j = cols[ops.loc[oid, "Ticker"]]
            monto = min((caja + abiertas_v) / LUGARES_REV, caja)
            if monto > 1 and P[i, j] > 0:
                pos[oid] = (j, monto * (1 - C.COSTO) / P[i, j])
                caja -= monto
        vals.append(caja + sum(cant * P[i, j] for j, cant in pos.values()))
    return pd.Series(vals, index=idx)


VERSION_REV = "6"     # subir cuando cambie el cálculo, para no usar datos guardados de una versión anterior
PRIORIDAD_NIVEL = {"Premium": 0, "Sólida": 1, "Especulativa": 2}


def niveles_calidad():
    """Nivel de calidad (Premium / Sólida / Especulativa) y P/E de cada acción, igual que el mail del screener.
    Se pide a Yahoo una vez por semana (el nivel casi no cambia). Si Yahoo falla con muchas acciones, no se guarda."""
    from concurrent.futures import ThreadPoolExecutor
    import time as _t

    def info(t):
        for intento in range(2):
            try:
                i = yf.Ticker(t).info or {}
                if i:
                    return t, {"market_cap": i.get("marketCap"), "roe": i.get("returnOnEquity"),
                               "margen": i.get("profitMargins"), "pe_trailing": i.get("trailingPE"),
                               "pe_forward": i.get("forwardPE")}
            except Exception:   # noqa: BLE001
                pass
            if intento == 0:
                _t.sleep(2)
        return t, {}

    tick = list(SCR.LISTA_TICKERS)
    with ThreadPoolExecutor(max_workers=6) as ex:
        fund = dict(ex.map(info, tick))
    if sum(1 for f in fund.values() if f.get("market_cap")) < 0.8 * len(tick):
        raise RuntimeError("Yahoo no devolvió datos de suficientes acciones")
    return {"niveles": {t: v["Nivel"] for t, v in SCR.clasificar_niveles(fund).items()}, "fund": fund}


def datos_reversion(niveles=None):
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
                    "Días en rango": u["Días en rango"], "Fallan": len(falla), "Falta": ", ".join(falla),
                    **{"ok_" + f: bool(e[f]) for f in act}})
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
    carteras = {reg: simular_cartera_rev(ops, reg, px, spy, True, niveles) for reg in REGLAS_REV}
    spy_c = spy[spy.index >= (ops["Entrada"].min() if len(ops) else spy.index[0])]
    return dict(ops=ops, hoy=pd.DataFrame(hoy), carteras=carteras, spy=spy_c, cierre=spy.index[-1],
                mercado=(bool(spy_ok.iloc[-1]), float(spy.iloc[-1]), float(media.iloc[-1])))

# ============================================================================ guardar y leer (texto JSON, para git)
def _cod(o):
    if isinstance(o, pd.DataFrame):
        df = o.copy()
        df.columns = [str(x) for x in df.columns]
        for c in df.columns:        # columnas de fechas (date de Python) -> fecha, para que vuelvan como fecha y no como texto
            if df[c].dtype == object:
                v = df[c].dropna()
                if len(v) and all(isinstance(x, date) for x in v):
                    df[c] = pd.to_datetime(df[c])
        return {"__df__": df.to_json(orient="table", date_format="iso", double_precision=8, default_handler=str)}
    if isinstance(o, pd.Series):
        return {"__s__": {"i": [x.isoformat() if isinstance(x, pd.Timestamp) else x for x in o.index],
                          "dt": bool(isinstance(o.index, pd.DatetimeIndex)), "v": [_cod(x) for x in o.tolist()],
                          "n": None if o.name is None else str(o.name)}}
    if isinstance(o, pd.Timestamp):
        return {"__ts__": o.isoformat()}
    if isinstance(o, date):
        return {"__d__": o.isoformat()}
    if isinstance(o, dict):
        return {str(k): _cod(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_cod(x) for x in o]
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, float) and np.isnan(o):
        return None
    return o


def _dec(o):
    if isinstance(o, dict):
        if "__df__" in o:
            return pd.read_json(io.StringIO(o["__df__"]), orient="table")
        if "__s__" in o:
            x = o["__s__"]
            idx = pd.to_datetime(x["i"]) if x["dt"] else x["i"]
            return pd.Series([_dec(v) for v in x["v"]], index=idx, name=x["n"], dtype=float if all(
                isinstance(v, (int, float)) or v is None for v in x["v"]) else object)
        if "__ts__" in o:
            return pd.Timestamp(o["__ts__"])
        if "__d__" in o:
            return date.fromisoformat(o["__d__"])
        return {k: _dec(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_dec(x) for x in o]
    return o


def huella_universo():
    f = RAIZ / "universo.csv"
    return hashlib.md5(f.read_bytes()).hexdigest()[:12] if f.exists() else ""


def guardar(nombre, datos, **meta):
    CARPETA.mkdir(exist_ok=True)
    meta.update(version=VERSION_REV, universo=huella_universo(), creado=pd.Timestamp.now(tz="UTC").isoformat())
    (CARPETA / f"{nombre}.json").write_text(json.dumps({"meta": meta, "datos": _cod(datos)}, ensure_ascii=False),
                                            encoding="utf-8")


def cargar(nombre, cierre_minimo=None, **meta_esperada):
    """Lo guardado, si coincide con la versión, el universo y lo pedido, y si su cierre es >= cierre_minimo. Si no, None."""
    f = CARPETA / f"{nombre}.json"
    if not f.exists():
        return None
    try:
        x = json.loads(f.read_text(encoding="utf-8"))
        m = x["meta"]
        if m.get("version") != VERSION_REV or m.get("universo") != huella_universo():
            return None
        if any(m.get(k) != v for k, v in meta_esperada.items()):
            return None
        if cierre_minimo and str(m.get("cierre", ""))[:10] < str(cierre_minimo)[:10]:
            return None
        return _dec(x["datos"])
    except Exception:       # noqa: BLE001
        return None
