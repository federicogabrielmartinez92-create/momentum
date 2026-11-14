"""Prueba aparte (no toca la app): señal de capitulación (idea del indicador "Capitulation Finder").

Compra al cierre cuando se dan a la vez:
  - el cierre está 10% o más por debajo de su media de 50 días,
  - RSI de 14 días por debajo de 30,
  - (variante con volumen) el volumen del día en Nueva York es 1,5 veces o más su promedio de los 20 días previos.
Salidas (las mismas de reversión): "6m" = a los 6 meses (126 ruedas); "tp" = al cierre que llega a +20%, o a los 12 meses.
Cartera: 10 lugares de 10% del valor total; no se repite una acción que ya está; si hay más señales que lugares, primero
Premium y después Sólidas. La plata libre queda en el S&P (SPY). Costo 0,5% por operación.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import calculos as CALC  # noqa: E402

COSTO, LUGARES, INICIO = 0.005, 10, "2010-01-01"
DIST, RSI_MAX, VOL_X = 0.10, 30, 1.5


def universo(solo_ps):
    u = pd.read_csv(RAIZ / "universo.csv", dtype=str)
    tick = list(u.loc[u["incluida"] == "1", "ticker"])
    nv = (CALC.cargar("niveles") or {}).get("niveles", {})
    if solo_ps:
        tick = [t for t in tick if nv.get(t) in ("Premium", "Sólida")]
    return tick, nv


def descargar(tick):
    raw = yf.download(tick + ["SPY"], start="2008-06-01", interval="1d", auto_adjust=True, group_by="ticker",
                      threads=True, progress=False)
    ok = [t for t in tick + ["SPY"] if t in raw.columns.get_level_values(0)]
    P = {c: pd.DataFrame({t: raw[t][c] for t in ok}) for c in ["Close", "Volume"]}
    idx = P["Close"]["SPY"].dropna().index
    return {c: df.reindex(idx) for c, df in P.items()}


def rsi(cl, n=14):
    d = cl.diff()
    sube = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    baja = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + sube / baja)


def senales(P, tick, con_volumen):
    cl, vol = P["Close"][tick], P["Volume"][tick]
    s = (cl <= cl.rolling(50).mean() * (1 - DIST)) & (rsi(cl) < RSI_MAX)
    if con_volumen:
        s &= vol >= VOL_X * vol.rolling(20).mean().shift(1)
    return s.fillna(False).values


def simular(P, tick, nv, sen, regla):
    Cl = P["Close"][tick].values
    spy = P["Close"]["SPY"].values
    idx = P["Close"].index
    prio = np.array([{"Premium": 0, "Sólida": 1}.get(nv.get(t), 2) for t in tick])
    orden = sorted(range(len(tick)), key=lambda j: (prio[j], tick[j]))
    i0 = int(np.searchsorted(idx, pd.Timestamp(INICIO)))
    caja, pos, vals, ops, perdidas = 10000.0, {}, [], [], 0
    for i in range(i0, len(idx)):
        if i > i0:
            caja *= spy[i] / spy[i - 1]
        for j in list(pos):
            cant, p_in, i_in = pos[j]
            if np.isnan(Cl[i, j]):
                continue
            dias = i - i_in
            sale = dias >= 126 if regla == "6m" else (Cl[i, j] / p_in - 1 >= 0.20 or dias >= 252)
            if sale:
                caja += cant * Cl[i, j] * (1 - COSTO)
                ops.append({"Ticker": tick[j], "Entrada": idx[i_in].date().isoformat(), "Salida": idx[i].date().isoformat(),
                            "ret": (Cl[i, j] * (1 - COSTO)) / (p_in / (1 - COSTO)) * 100 - 100, "ruedas": dias,
                            "spy": (spy[i] / spy[i_in] - 1) * 100})
                del pos[j]
        abiertas_v = sum(c * np.nan_to_num(Cl[i, j]) for j, (c, *_r) in pos.items())
        for j in orden:
            if not sen[i, j] or j in pos or np.isnan(Cl[i, j]):
                continue
            if len(pos) >= LUGARES:
                perdidas += 1
                continue
            monto = min((caja + abiertas_v) / LUGARES, caja)
            if monto <= 1:
                break
            pos[j] = (monto * (1 - COSTO) / Cl[i, j], Cl[i, j], i)
            caja -= monto
        vals.append(caja + sum(c * np.nan_to_num(Cl[i, j]) for j, (c, *_r) in pos.items()))
    return pd.Series(vals, index=idx[i0:]), pd.DataFrame(ops), len(pos), perdidas


def stats(s):
    y = (s.index[-1] - s.index[0]).days / 365.25
    an = pd.concat([s.iloc[[0]], s.resample("YE").last()]).pct_change().iloc[1:] * 100
    an.index = an.index.year
    an = an[~an.index.duplicated(keep="last")]
    return {"anual": ((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1) * 100, "caida": float((s / s.cummax() - 1).min() * 100),
            "por_anio": {int(k): round(float(v), 1) for k, v in an.items()}}


def main():
    out = {}
    for grupo, solo in [("premium_solidas", True), ("todas", False)]:
        tick, nv = universo(solo)
        P = descargar(tick)
        tick = [t for t in tick if t in P["Close"]]
        spy = P["Close"]["SPY"]
        spy = spy[spy.index >= INICIO]
        out.setdefault("spy", stats(spy))
        out[grupo] = {"acciones": len(tick)}
        for vol in (True, False):
            sen = senales(P, tick, vol)
            for regla in ("6m", "tp"):
                s, ops, abiertas, perdidas = simular(P, tick, nv, sen, regla)
                r = stats(s)
                r.update(abiertas=abiertas, senales_sin_lugar=perdidas, operaciones=int(len(ops)))
                if len(ops):
                    r.update(ganadoras=float((ops["ret"] > 0).mean() * 100), ret_prom=float(ops["ret"].mean()),
                             ret_mediana=float(ops["ret"].median()), ruedas_prom=float(ops["ruedas"].mean()),
                             mejor=float(ops["ret"].max()), peor=float(ops["ret"].min()),
                             le_gana_spy=float(((ops["ret"] - ops["spy"]) > 0).mean() * 100),
                             por_anio_ops={int(k): int(v) for k, v in pd.to_datetime(ops["Entrada"]).dt.year.value_counts().sort_index().items()})
                out[grupo][f"{'vol' if vol else 'sinvol'}_{regla}"] = r
                print(grupo, vol, regla, round(r["anual"], 1), round(r["caida"], 1), r["operaciones"], flush=True)
    rev = CALC.cargar("reversion")                      # la reversión actual de la app, para comparar
    if rev:
        out["reversion_app"] = {k: stats(v) for k, v in rev["carteras"].items()}
    Path("resultado_capitulacion.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
