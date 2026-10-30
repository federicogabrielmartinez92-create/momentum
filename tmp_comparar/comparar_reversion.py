"""Calidad: cartera armada de cero el 1 de enero de cada año (2019-2025) y llevada con las reglas hasta hoy. Solo imprime."""
import json, os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.getcwd())
os.environ["BT_ESTADO_SALIDA"] = "/tmp/estado_bt.json"
import pandas as pd
import backtest_calidad as B
res = []
for anio in range(2019, 2026):
    B.INICIO_MIN = f"{anio}-01-01"
    B.main()
    h = json.load(open("historial_calidad.json", encoding="utf-8"))
    ev = pd.DataFrame(h["evolucion"])
    f0, f1 = pd.Timestamp(ev["fecha"].iloc[0]), pd.Timestamp(ev["fecha"].iloc[-1])
    anios = (f1 - f0).days / 365.25
    c, s, l = (ev[k].iloc[-1] / ev[k].iloc[0] for k in ("cartera", "spy", "lista"))
    serie = ev.set_index("fecha")["cartera"]
    dd = (serie / serie.cummax() - 1).min()
    res.append({"Desde": anio, "Primera compra": h["inicio"], "Hasta": h["fin"], "Años": round(anios, 1),
                "Cartera total %": round((c - 1) * 100, 1), "S&P total %": round((s - 1) * 100, 1),
                "Lista total %": round((l - 1) * 100, 1), "Cartera anual %": round((c ** (1 / anios) - 1) * 100, 1),
                "S&P anual %": round((s ** (1 / anios) - 1) * 100, 1), "Peor caída mensual %": round(dd * 100, 1)})
    print("RESULTADO", res[-1], flush=True)
print("\n\nTABLA FINAL")
print(pd.DataFrame(res).to_string(index=False))
