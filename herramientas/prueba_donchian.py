"""Prueba aparte (no toca la app): canal de Donchian + EMA 50 en diario.

Entrada: la media del canal de Donchian (punto medio entre el máximo y el mínimo de los N días previos) está por debajo de la
EMA de 50 y el cierre la cruza hacia arriba (ayer cerraba debajo de la media, hoy arriba). Se compra al cierre.
Salidas probadas:
  min10  - el precio toca el mínimo de los 10 días previos (se vende a ese nivel, o a la apertura si abrió por debajo).
  fijo10 - al comprar se fija el cierre de 10 ruedas antes de la entrada; se vende cuando el precio toca ese valor
           (si está debajo de la compra funciona como stop, si está arriba como objetivo).
  cierre10 - se vende al cierre el día que el cierre queda por debajo del cierre de 10 ruedas atrás.
Cartera: 10 lugares de 10% del valor total; si hay más señales que lugares, primero Premium y después Sólidas.
La plata libre queda en el S&P (SPY). Costos 0,5% por operación (entrada y salida).
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


def universo(solo_ps=True):
    u = pd.read_csv(RAIZ / "universo.csv", dtype=str)
    tick = list(u.loc[u["incluida"] == "1", "ticker"])
    nv = (CALC.cargar("niveles") or {}).get("niveles", {})
    if solo_ps:
        tick = [t for t in tick if nv.get(t) in ("Premium", "Sólida")]
    return tick, nv


def descargar(tick):
    raw = yf.download(tick + ["SPY"], start="2008-06-01", interval="1d", auto_adjust=True, group_by="ticker",
                      threads=True, progress=False)
    campos = {}
    for c in ["Open", "High", "Low", "Close"]:
        campos[c] = pd.DataFrame({t: raw[t][c] for t in tick + ["SPY"] if t in raw.columns.get_level_values(0)})
    idx = campos["Close"]["SPY"].dropna().index
    return {c: df.reindex(idx) for c, df in campos.items()}


def simular(P, tick, nv, n_don, salida):
    O, H, L, Cl = (P[c][tick].values for c in ["Open", "High", "Low", "Close"])
    spy = P["Close"]["SPY"].values
    idx = P["Close"].index
    hi = pd.DataFrame(H).rolling(n_don).max().shift(1).values
    lo = pd.DataFrame(L).rolling(n_don).min().shift(1).values
    mid = (hi + lo) / 2
    ema = pd.DataFrame(Cl).ewm(span=50, adjust=False, min_periods=50).mean().values
    min10 = pd.DataFrame(L).rolling(10).min().shift(1).values
    senal = np.zeros_like(Cl, dtype=bool)
    senal[1:] = (mid[1:] < ema[1:]) & (Cl[:-1] <= mid[:-1]) & (Cl[1:] > mid[1:])
    prio = np.array([{"Premium": 0, "Sólida": 1}.get(nv.get(t), 2) for t in tick])
    orden = sorted(range(len(tick)), key=lambda j: (prio[j], tick[j]))
    i0 = int(np.searchsorted(idx, pd.Timestamp(INICIO)))
    caja, pos, vals, ops = 10000.0, {}, [], []
    for i in range(i0, len(idx)):
        if i > i0:
            caja *= spy[i] / spy[i - 1]
        for j in list(pos):                          # salidas
            cant, p_in, i_in, nivel = pos[j]
            if np.isnan(Cl[i, j]):
                continue
            px = None
            if salida == "min10":
                lv = min10[i, j]
                if not np.isnan(lv) and L[i, j] <= lv:
                    px = min(O[i, j], lv) if not np.isnan(O[i, j]) else lv
            elif salida == "fijo10":
                if nivel < p_in and L[i, j] <= nivel:
                    px = min(O[i, j], nivel) if not np.isnan(O[i, j]) else nivel
                elif nivel >= p_in and H[i, j] >= nivel:
                    px = max(O[i, j], nivel) if not np.isnan(O[i, j]) else nivel
            elif salida == "cierre10":
                if Cl[i, j] < Cl[i - 10, j]:
                    px = Cl[i, j]
            if px is not None:
                caja += cant * px * (1 - COSTO)
                ops.append({"Ticker": tick[j], "Entrada": idx[i_in].date().isoformat(), "Salida": idx[i].date().isoformat(),
                            "ret": (px * (1 - COSTO)) / (p_in / (1 - COSTO)) * 100 - 100, "ruedas": i - i_in,
                            "spy": (spy[i] / spy[i_in] - 1) * 100})
                del pos[j]
        abiertas_v = sum(c * np.nan_to_num(Cl[i, j]) for j, (c, *_r) in pos.items())
        for j in orden:                              # entradas
            if len(pos) >= LUGARES:
                break
            if j in pos or not senal[i, j] or np.isnan(Cl[i, j]):
                continue
            monto = min((caja + abiertas_v) / LUGARES, caja)
            if monto <= 1:
                break
            nivel = Cl[i - 10, j]
            if salida == "fijo10" and np.isnan(nivel):
                continue
            pos[j] = (monto * (1 - COSTO) / Cl[i, j], Cl[i, j], i, nivel)
            caja -= monto
        vals.append(caja + sum(c * (Cl[i, j] if not np.isnan(Cl[i, j]) else 0) for j, (c, *_r) in pos.items()))
    serie = pd.Series(vals, index=idx[i0:])
    return serie, pd.DataFrame(ops), len(pos)


def stats(s):
    y = (s.index[-1] - s.index[0]).days / 365.25
    an = s.resample("YE").last()
    an = pd.concat([s.iloc[[0]], an]).pct_change().iloc[1:] * 100
    an.index = an.index.year
    an = an[~an.index.duplicated(keep="last")]
    return {"anual": ((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1) * 100, "caida": float((s / s.cummax() - 1).min() * 100),
            "final": float(s.iloc[-1] / s.iloc[0] * 10000), "por_anio": {int(k): round(float(v), 1) for k, v in an.items()},
            "vol": float(s.pct_change().std() * np.sqrt(252) * 100)}


def main():
    out = {}
    for grupo, solo in [("premium_solidas", True), ("todas", False)]:
        tick, nv = universo(solo)
        P = descargar(tick)
        tick = [t for t in tick if t in P["Close"]]
        spy = P["Close"]["SPY"]
        spy = spy[spy.index >= INICIO]
        out.setdefault("spy", stats(spy / spy.iloc[0] * 10000))
        out[grupo] = {"acciones": len(tick)}
        for n in (20, 50):
            for sal in ("min10", "fijo10", "cierre10"):
                s, ops, abiertas = simular(P, tick, nv, n, sal)
                r = stats(s)
                if len(ops):
                    r.update(operaciones=len(ops), abiertas=abiertas, ganadoras=float((ops["ret"] > 0).mean() * 100),
                             ret_prom=float(ops["ret"].mean()), ret_mediana=float(ops["ret"].median()),
                             ruedas_prom=float(ops["ruedas"].mean()), mejor=float(ops["ret"].max()), peor=float(ops["ret"].min()),
                             le_gana_spy=float(((ops["ret"] - ops["spy"]) > 0).mean() * 100),
                             ganancia_prom=float(ops.loc[ops["ret"] > 0, "ret"].mean()),
                             perdida_prom=float(ops.loc[ops["ret"] <= 0, "ret"].mean()))
                out[grupo][f"don{n}_{sal}"] = r
                print(grupo, n, sal, round(r["anual"], 1), round(r["caida"], 1), r.get("operaciones"), flush=True)
    Path("resultado_donchian.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
