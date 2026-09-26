"""
BACKTEST DE LA CARTERA DE CALIDAD (reglas actuales, al pie de la letra)
=====================================================================
Simula mes a mes la cartera de calidad desde que hay datos suficientes (2012 aprox.) hasta hoy, usando
EXACTAMENTE las funciones de calidad.py (filtros, puntaje, precio, tendencia, compras, ventas, rotaciones y
recortes). Los balances salen de la base oficial de la SEC (EDGAR), con la fecha en que cada balance se
publicó: en cada mes el sistema solo "ve" lo que ya se sabía en ese momento.

Cómo correrlo en Google Colab:
  1. Subí calidad.py y este archivo al panel de archivos de Colab (el ícono de carpeta, a la izquierda).
  2. Cambiá SEC_USER_AGENT abajo por tu nombre y tu mail (la SEC exige identificarse para bajar datos).
  3. En una celda:   !pip install -q yfinance openpyxl
     y en otra:      !python backtest_calidad.py
  Tarda 10-20 minutos la primera vez (baja los balances de la SEC). Queda guardado en la carpeta
  edgar_cache, así que si lo volvés a correr en la misma sesión es mucho más rápido.
  Al terminar descarga el Excel, el gráfico y cartera_calidad.json: la cartera tal como terminó el backtest,
  para subir a GitHub y que el mail mensual continúe desde ahí con exactamente las mismas reglas y datos.

Limitaciones (importantes para leer el resultado):
  * Solo entran las empresas que presentan balances en la SEC con normas contables de EE.UU. (las extranjeras
    que reportan con normas internacionales, como TSMC o Novartis, quedan afuera del backtest).
  * La lista de acciones es la de hoy (sesgo de supervivencia). Por eso se compara también contra el
    promedio de TODAS las acciones de la lista: ganarle a ese promedio es lo que muestra si el método suma.
  * Los datos de la SEC se procesan automáticamente; alguna empresa puede tener datos incompletos.
"""
import json
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd
import requests
import yfinance as yf

SEC_USER_AGENT = "Nombre Apellido tu_mail@dominio.com"   # <-- poné tu nombre y tu mail
CAPITAL = 10_000
CACHE = "edgar_cache"
INICIO_MIN = "2011-01-01"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ".")
import importlib  # noqa: E402
import calidad as C  # noqa: E402
C = importlib.reload(C)   # en Colab, siempre usar la última versión de calidad.py que se subió

# ============================================================================ simulación
def main():
    if "tu_mail" in SEC_USER_AGENT:
        print("AVISO: cambiá SEC_USER_AGENT por tu nombre y tu mail (la SEC puede rechazar el pedido si no).")
    tickers = list(C.TICKERS)
    print(f"Bajando precios de {len(tickers)} acciones...")
    close, adj, vol, spl = C.descargar_todo(tickers)
    print("Bajando balances de la SEC (la primera vez tarda)...")
    sec = C.bajar_sec(tickers, SEC_USER_AGENT, CACHE)
    univ = [t for t in tickers if t in sec and t in adj.columns]
    sin = sorted(set(tickers) - set(univ))
    print(f"Empresas con balances en la SEC: {len(univ)} de {len(tickers)}. Sin datos: {', '.join(sin)}")
    C.TICKERS = univ                                    # el momentum residual se calcula sobre este universo
    B = {t: C.Balances(t, sec[t], spl.get(t, pd.Series(dtype=float))) for t in univ}
    dvol = (close[univ] * vol[univ]).rolling(30, min_periods=10).mean()

    idx = adj.index
    fechas = []
    for per, g in pd.Series(idx, index=idx).groupby(idx.to_period("M")):
        g = g[g.dt.day >= C.DIA_REVISION]
        if len(g):
            fechas.append(pd.Timestamp(g.iloc[0]))
    fechas = [d for d in fechas if d >= pd.Timestamp(INICIO_MIN)]

    metricas_cache = {}
    E = C.estado_nuevo()
    E["caja"] = E["spy_ref"] = CAPITAL
    registro, operaciones, cerradas, carteras, cobertura = [], [], [], [], []
    diario = []
    ultimo = None
    arrancado = False
    for n, d in enumerate(fechas):
        mets, con_datos = C.metricas_sec(univ, B, close, d, metricas_cache)
        if not arrancado:
            if con_datos < 0.5 * len(univ):
                continue
            arrancado = True
            print(f"Arranca la simulación: {d.date()} ({con_datos} empresas con 3 años de balances)")
        pxd = adj.loc[:d]
        rk = C.ranking_desde(mets, close, adj, dvol, d)
        # valor diario desde la revisión anterior
        if ultimo is not None:
            tramo = adj.loc[ultimo[0]:d].iloc[1:]
            for dia, fila in tramo.iterrows():
                v = ultimo[1] * fila["SPY"] / ultimo[3]["SPY"]
                for t, val in ultimo[2].items():
                    if pd.notna(fila.get(t)) and pd.notna(ultimo[3].get(t)) and ultimo[3][t] > 0:
                        v += val * fila[t] / ultimo[3][t]
                    else:
                        v += val
                diario.append((dia, v))
        E = C.actualizar_valores(E, pxd)
        total_antes = E["caja"] + sum(p["valor"] for p in E["posiciones"].values())
        revision = d.month in C.MESES_REVISION
        E, ords, cer, tes = C.aplicar_reglas(E, rk, pxd, d.date(), revision)
        total = E["caja"] + sum(p["valor"] for p in E["posiciones"].values())
        for o in ords:
            operaciones.append({"Fecha": d.date(), **o, "Peso": o["Monto"] / total_antes})
        cerradas += cer
        for t, p in E["posiciones"].items():
            carteras.append({"Fecha": d.date(), "Acción": t, "Peso %": p["valor"] / total * 100,
                             "Puesto calidad": rk.loc[t, "Puesto"] if t in rk.index else np.nan})
        if E["caja"] / total > 0.005:
            carteras.append({"Fecha": d.date(), "Acción": "SPY (liquidez)", "Peso %": E["caja"] / total * 100, "Puesto calidad": np.nan})
        pasan = int(rk["pasa"].sum())
        cobertura.append({"Fecha": d.date(), "Empresas con balances": con_datos, "Pasan filtros": pasan,
                          "Comprables": int(rk["comprable"].sum()), "Operaciones": len(ords)})
        registro.append({"Fecha": d, "Valor": total})
        ultimo = (d, E["caja"], {t: p["valor"] for t, p in E["posiciones"].items()}, adj.loc[d])
        if n % 12 == 0:
            print(f"  {d.date()}: cartera USD {total:,.0f} · {len(E['posiciones'])} empresas · {pasan} pasan filtros")
    if not registro:
        raise RuntimeError("No hubo meses con datos suficientes para simular.")
    # tramo final hasta el último día
    tramo = adj.loc[ultimo[0]:].iloc[1:]
    for dia, fila in tramo.iterrows():
        v = ultimo[1] * fila["SPY"] / ultimo[3]["SPY"]
        for t, val in ultimo[2].items():
            v += val * fila[t] / ultimo[3][t] if pd.notna(fila.get(t)) and ultimo[3].get(t, 0) > 0 else val
        diario.append((dia, v))
    ini = registro[0]["Fecha"]
    serie = pd.concat([pd.Series({ini: CAPITAL}), pd.Series(dict(diario))]).sort_index()
    serie = serie[~serie.index.duplicated(keep="last")]
    spy = CAPITAL * adj["SPY"].loc[ini:] / adj["SPY"].loc[ini]
    # promedio de todas las acciones de la lista (igual peso, rebalanceo mensual)
    r = adj[univ].loc[ini:].pct_change()
    mes = r.index.to_period("M")
    pesos = pd.DataFrame(np.nan, index=r.index, columns=univ)
    for per, g in r.groupby(mes):
        vivos = adj[univ].loc[:g.index[0]].iloc[-1].notna()
        pesos.loc[g.index[0]] = vivos / vivos.sum()
    pesos = pesos.ffill()
    # rendimiento diario del promedio: dentro de cada mes, peso inicial x crecimiento acumulado
    val_mes = []
    nivel = CAPITAL
    for per, g in r.groupby(mes):
        w0 = pesos.loc[g.index[0]].fillna(0)
        acum = (1 + g.fillna(0)).cumprod()
        v = nivel * (acum * w0).sum(axis=1)
        val_mes.append(v)
        nivel = v.iloc[-1]
    ew = pd.concat(val_mes)
    ew.iloc[0] = CAPITAL
    bil = adj["BIL"].loc[ini:] if "BIL" in adj else None
    series = {"Cartera de calidad": serie, "S&P 500 (SPY)": spy.reindex(serie.index).ffill(),
              "Promedio de la lista (igual peso)": ew.reindex(serie.index).ffill()}

    def stats(s, desde=None, hasta=None):
        s = s.loc[desde:hasta].dropna()
        if len(s) < 30:
            return {}
        ret = s.pct_change().dropna()
        anios = (s.index[-1] - s.index[0]).days / 365.25
        cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / anios) - 1
        rf = 0.0
        if bil is not None:
            b = bil.loc[s.index[0]:s.index[-1]].dropna()
            if len(b) > 30:
                rf = (b.iloc[-1] / b.iloc[0]) ** (1 / anios) - 1
        vol_ = ret.std() * np.sqrt(252)
        dd = (s / s.cummax() - 1).min()
        return {"Anual %": cagr * 100, "Volatilidad %": vol_ * 100, "Sharpe": (cagr - rf) / vol_ if vol_ else np.nan,
                "Peor caída %": dd * 100, "USD 10.000 →": CAPITAL * s.iloc[-1] / s.iloc[0]}

    periodos = [("Todo", None, None), ("2012-2014", "2012-01-01", "2014-12-31"), ("2015-2019", "2015-01-01", "2019-12-31"),
                ("2020-2022", "2020-01-01", "2022-12-31"), ("2023-hoy", "2023-01-01", None)]
    filas = []
    for nom, s in series.items():
        for p, a, b in periodos:
            st = stats(s, a, b)
            if st:
                filas.append({"Cartera": nom, "Período": p, **st})
    resumen = pd.DataFrame(filas)
    anual = pd.DataFrame({k: v.resample("YE").last() for k, v in series.items()})
    anual = pd.concat([pd.DataFrame({k: [v.iloc[0]] for k, v in series.items()}, index=[serie.index[0]]), anual])
    anual = (anual.pct_change().dropna() * 100).round(1)
    anual.index = anual.index.year
    anual.index.name = "Año"
    anual["Gana al S&P"] = np.where(anual["Cartera de calidad"] > anual["S&P 500 (SPY)"], "Sí", "")
    cer = pd.DataFrame(cerradas)
    ops = pd.DataFrame(operaciones)
    anios_tot = (serie.index[-1] - serie.index[0]).days / 365.25
    extra = {
        "Período simulado": f"{serie.index[0].date()} a {serie.index[-1].date()} ({anios_tot:.1f} años)",
        "Empresas en el backtest": f"{len(univ)} de {len(tickers)} (con balances en la SEC)",
        "Operaciones por año (compras + ventas)": f"{len(ops) / anios_tot:.1f}" if len(ops) else "0",
        "Ventas con ganancia": (f"{(cer['Resultado'] > 0).mean() * 100:.0f}% de {len(cer)}" if len(cer) else "—"),
        "Tiempo promedio por posición vendida": (f"{((pd.to_datetime(cer['Venta']) - pd.to_datetime(cer['Compra'])).dt.days.mean() / 365.25):.1f} años"
                                                 if len(cer) else "—"),
    }
    # estado final: la cartera sigue desde acá en el mail mensual (escalada a USD 10.000)
    Ef = C.actualizar_valores(E, adj)
    tot = Ef["caja"] + sum(p["valor"] for p in Ef["posiciones"].values())
    f = CAPITAL / tot
    for p in Ef["posiciones"].values():
        p["valor"] *= f
        p["costo"] *= f
    Ef["caja"] *= f
    Ef.update(capital=float(CAPITAL), spy_ref=float(CAPITAL), inicio=Ef["ultima_fecha"],
              ultima_oficial=registro[-1]["Fecha"].strftime("%Y-%m-%d"), operaciones=[], cerradas=[],
              evolucion=[{"fecha": Ef["ultima_fecha"], "cartera": float(CAPITAL), "spy": float(CAPITAL)}],
              origen=f"backtest {serie.index[0].date()} a {serie.index[-1].date()}")
    C.ESTADO = "cartera_calidad.json"
    C.guardar_estado(Ef)
    # historial para el dashboard (mismos datos que el Excel)
    nan0 = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else v
    mens = pd.DataFrame(series).resample("ME").last()
    mens.index = [min(i, serie.index[-1]) for i in mens.index]
    evol = [{"fecha": serie.index[0].strftime("%Y-%m-%d"), "cartera": float(CAPITAL), "spy": float(CAPITAL), "lista": float(CAPITAL)}]
    evol += [{"fecha": i.strftime("%Y-%m-%d"), "cartera": float(r.iloc[0]), "spy": float(r.iloc[1]), "lista": float(r.iloc[2])}
             for i, r in mens.iterrows()]
    hist = {"origen": f"backtest {serie.index[0].date()} a {serie.index[-1].date()}", "inicio": str(serie.index[0].date()),
            "fin": str(serie.index[-1].date()), "datos": extra,
            "resumen": [{k: nan0(v) for k, v in r.items()} for r in resumen.to_dict("records")],
            "anual": [{"Año": int(a), "Cartera": float(r["Cartera de calidad"]), "SPY": float(r["S&P 500 (SPY)"]),
                       "Lista": float(r["Promedio de la lista (igual peso)"])} for a, r in anual.iterrows()],
            "evolucion": evol,
            "operaciones": [{"Fecha": str(o["Fecha"]), "Orden": o["Orden"], "Acción": o["Acción"], "Peso": float(o["Peso"]),
                             "Resultado": nan0(float(o["Resultado"])) if o["Resultado"] is not None else None, "Motivo": o["Motivo"],
                             "Origen": "Backtest"} for o in operaciones],
            "ventas": [{"Acción": c_["Acción"], "Compra": str(c_["Compra"]), "Venta": str(c_["Venta"]), "Resultado": float(c_["Resultado"]),
                        "Motivo": c_["Motivo"], "Origen": "Backtest"} for c_ in cerradas]}
    with open("historial_calidad.json", "w", encoding="utf-8") as fh:
        json.dump(hist, fh, ensure_ascii=False, indent=1)
    print("\nCartera final guardada en cartera_calidad.json (para subir a GitHub):")
    for t, p in sorted(Ef["posiciones"].items(), key=lambda x: -x[1]["valor"]):
        print(f"  {t:6} {p['valor'] / CAPITAL * 100:5.1f}%  (en cartera desde {p['fecha_entrada']})")
    if Ef["caja"] > 1:
        print(f"  SPY    {Ef['caja'] / CAPITAL * 100:5.1f}%  (liquidez)")
    # salidas
    hoy = date.today().isoformat()
    ruta = f"backtest_calidad_{hoy}.xlsx"
    with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
        pd.DataFrame({"Dato": list(extra), "Valor": list(extra.values())}).to_excel(xw, sheet_name="Datos", index=False)
        resumen.round(2).to_excel(xw, sheet_name="Resumen", index=False)
        anual.to_excel(xw, sheet_name="Año por año")
        m = pd.DataFrame(series).resample("ME").last()
        m.index = m.index.date
        m.round(0).to_excel(xw, sheet_name="Evolución USD 10.000")
        if len(ops):
            o = ops.copy()
            o.insert(2, "Empresa", [C.nombre(t) for t in o["Acción"]])
            o["Resultado %"] = o.pop("Resultado") * 100
            o.to_excel(xw, sheet_name="Operaciones", index=False)
        if len(cer):
            c2 = cer.copy()
            c2.insert(1, "Empresa", [C.nombre(t) for t in c2["Acción"]])
            c2["Resultado"] = c2["Resultado"] * 100
            c2.rename(columns={"Resultado": "Resultado %"}).to_excel(xw, sheet_name="Ventas", index=False)
        cart = pd.DataFrame(carteras)
        if len(cart):
            piv = cart.pivot_table(index="Fecha", columns="Acción", values="Peso %", aggfunc="sum").round(1)
            piv.to_excel(xw, sheet_name="Cartera mes a mes")
        pd.DataFrame(cobertura).to_excel(xw, sheet_name="Cobertura de datos", index=False)
        for ws in xw.sheets.values():
            for c_ in ws.columns:
                ws.column_dimensions[c_[0].column_letter].width = 16
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 4.5), dpi=130)
        colores = {"Cartera de calidad": "#1f5fa8", "S&P 500 (SPY)": "#8a8a8a", "Promedio de la lista (igual peso)": "#e0a030"}
        for k, s in series.items():
            ax.plot(s.index, s.values, label=k, color=colores[k], lw=2 if k.startswith("Cartera") else 1.3)
        ax.set_yscale("log")
        ax.set_title("USD 10.000 siguiendo la cartera de calidad al pie de la letra (escala logarítmica)")
        ax.legend(frameon=False)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(f"backtest_calidad_{hoy}.png")
    except Exception as e:      # noqa: BLE001
        print("Sin gráfico:", e)
    pd.set_option("display.width", 200)
    print("\n" + "\n".join(f"{k}: {v}" for k, v in extra.items()))
    print("\nRESUMEN\n", resumen.round(1).to_string(index=False))
    print("\nAÑO POR AÑO (%)\n", anual.to_string())
    print(f"\nArchivos: {ruta} y backtest_calidad_{hoy}.png")
    try:
        from google.colab import files
        files.download(ruta)
        files.download(f"backtest_calidad_{hoy}.png")
        files.download("cartera_calidad.json")
        files.download("historial_calidad.json")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
