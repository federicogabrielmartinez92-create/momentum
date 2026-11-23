"""Prueba aparte: cuánto varían hoy las carteras de calidad y momentum (precio de ahora contra el cierre anterior)."""
import json, sys
from pathlib import Path
import pandas as pd
import yfinance as yf
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import calculos as CALC  # noqa: E402

E = json.loads((RAIZ / "cartera_calidad.json").read_text(encoding="utf-8"))
mom = CALC.cargar("momentum", None, inicio="2026-10-01")
cart = mom["real"]["cart"]
tick = sorted(set(E["posiciones"]) | set(cart["Acción"]) | {"SPY"})
px = yf.download(tick, period="1mo", auto_adjust=True, progress=False, threads=False)["Close"].ffill()
ult, ant = px.iloc[-1], px.iloc[-2]
var = (ult / ant - 1) * 100
# calidad: valores al 16/11 llevados al cierre anterior
base = px[px.index <= pd.Timestamp(E["ultima_fecha"])].iloc[-1]
vc = {t: p["valor"] * ant[t] / base[t] for t, p in E["posiciones"].items()}
vc["SPY"] = E["caja"] * ant["SPY"] / base["SPY"]
tc = sum(vc.values())
# momentum: pesos al cierre del precálculo llevados al cierre anterior
basem = px[px.index <= pd.Timestamp(mom["cierre"])].iloc[-1]
vm = {t: w * ant[t] / basem[t] for t, w in zip(cart["Acción"], cart["Peso %"])}
resto = 100 - float(cart["Peso %"].sum())
tm = sum(vm.values()) + resto
out = {"fecha_precio": str(px.index[-1].date()), "anterior": str(px.index[-2].date()), "spy": float(var["SPY"]),
       "calidad": {"total": sum(vc[t] * var[t] for t in vc) / tc,
                   "acciones": {t: {"peso": vc[t] / tc * 100, "var": float(var[t])} for t in vc}},
       "momentum": {"total": sum(vm[t] * var[t] for t in vm) / tm,
                    "acciones": {t: {"peso": vm[t] / tm * 100, "var": float(var[t])} for t in vm}}}
Path("resultado_variacion_hoy.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))
