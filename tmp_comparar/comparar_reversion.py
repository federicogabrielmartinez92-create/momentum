"""Calidad y momentum armados de cero el 01/10/2025, llevados con sus reglas hasta hoy. Solo imprime."""
import json, os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.getcwd())
os.environ["BT_ESTADO_SALIDA"] = "/tmp/estado_bt.json"
import pandas as pd

print("\n######## MOMENTUM desde 2025-10-01")
os.environ["MOMENTUM_INICIO"] = "2025-10-01"
import momentum as M
M.INICIO = "2025-10-01"
px, vo = M.descargar()
motor = M.Motor(px, vo)
hold, caja, serie, spy, hist, cer, _ = M.simular(motor)
print("Primera operación:", serie.index[0].date(), "· último cierre:", serie.index[-1].date())
print(f"Cartera: {(serie.iloc[-1] / serie.iloc[0] - 1) * 100:.1f}%  ·  S&P: {(spy.iloc[-1] / spy.iloc[0] - 1) * 100:.1f}%  ·  "
      f"peor caída {((serie / serie.cummax() - 1).min()) * 100:.1f}%")
print("Mensual:", {d.strftime('%Y-%m'): round(v, 1) for d, v in (serie.resample('ME').last().pct_change().dropna() * 100).items()})
print("Operaciones:", len(hist))
print(hist[["Mail", "Orden", "Acción", "Motivo"]].to_string(index=False) if len(hist) else "")
if len(cer):
    print("Vendidas:", cer[["Acción", "Compra", "Venta", "Resultado %"]].round(1).to_string(index=False))
k = len(motor.idx) - 1
print("Cartera hoy:", {t: round((h['cant'] * px.iloc[k][t] / h['costo'] - 1) * 100, 1) for t, h in hold.items()})

print("\n######## CALIDAD desde 2025-10-01")
import backtest_calidad as B
B.INICIO_MIN = "2025-10-01"
B.main()
h = json.load(open("historial_calidad.json", encoding="utf-8"))
ev = pd.DataFrame(h["evolucion"])
c, s, l = (ev[x].iloc[-1] / ev[x].iloc[0] for x in ("cartera", "spy", "lista"))
print(f"RESULTADO CALIDAD desde {h['inicio']} a {h['fin']}: cartera {(c-1)*100:.1f}% · S&P {(s-1)*100:.1f}% · lista {(l-1)*100:.1f}%")
print("Evolución mensual:", [(e["fecha"], round(e["cartera"]), round(e["spy"])) for e in h["evolucion"]])
print("Operaciones:", [(o["Fecha"], o["Orden"], o["Acción"]) for o in h["operaciones"]])
print("Ventas:", [(v["Acción"], v["Compra"], v["Venta"], round(v["Resultado"] * 100, 1)) for v in h["ventas"]])
print("Cartera final:", json.load(open("/tmp/estado_bt.json"))["posiciones"].keys())
