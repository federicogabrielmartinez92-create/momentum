"""Prueba aparte: cuánto se opera por día en BYMA cada CEDEAR del universo (últimos 3 meses)."""
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

RAIZ = Path(__file__).resolve().parents[1]
u = pd.read_csv(RAIZ / "universo.csv", dtype=str)
u = u[u["incluida"] == "1"]
cod = dict(zip(u["ticker"], u["cedear"].fillna(u["ticker"])))
pm = json.loads((RAIZ / "panel_momentum.json").read_text(encoding="utf-8"))
cartera = [x["Acción"] for x in pm["cartera"]]
top30 = [x["Acción"] for x in pm["ranking"][:30]]
sims = {t: f"{c}.BA" for t, c in cod.items()}
raw = yf.download(sorted(set(sims.values())), period="3mo", auto_adjust=False, group_by="ticker", threads=True, progress=False)
out = {}
for t, s in sims.items():
    try:
        df = raw[s][["Close", "Volume"]].dropna()
    except KeyError:
        continue
    if not len(df):
        continue
    v = df["Close"] * df["Volume"]
    out[t] = {"cedear": cod[t], "mediana_ars": float(v.median()), "promedio_ars": float(v.mean()), "p25_ars": float(v.quantile(.25)),
              "dias_sin_operar": int((df["Volume"] == 0).sum()), "dias": int(len(df)), "precio": float(df["Close"].iloc[-1])}
ccl = None
try:
    a = yf.download(["GGAL.BA", "GGAL"], period="5d", auto_adjust=False, progress=False)["Close"].dropna()
    ccl = float(a["GGAL.BA"].iloc[-1] * 10 / a["GGAL"].iloc[-1])
except Exception:  # noqa: BLE001
    pass
Path("resultado_liquidez.json").write_text(json.dumps({"ccl_aprox": ccl, "cartera": cartera, "top30": top30, "datos": out},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
print(len(out), ccl)
