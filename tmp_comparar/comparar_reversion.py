"""Reversión: resultado de las operaciones según el nivel de la acción (Premium / Sólida / Especulativa). Solo imprime."""
import ast, os, sys, types, warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
sys.path.insert(0, os.getcwd())
fuente = open("dashboard/app.py", encoding="utf-8").read()
arbol = ast.parse(fuente)
nombres = {"evaluar_rev", "_salidas", "simular_cartera_rev", "datos_reversion"}
partes = []
for n in arbol.body:
    if isinstance(n, ast.FunctionDef) and n.name in nombres:
        n.decorator_list = []
        partes.append(ast.unparse(n))
    elif isinstance(n, ast.Assign) and not any(isinstance(x, (ast.Call, ast.Attribute)) for x in ast.walk(n.value)):
        objs = [x for t in n.targets for x in ast.walk(t) if isinstance(x, ast.Name)]
        usa = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
        if objs and all(x.id.isupper() and not x.id.startswith("_") for x in objs) and not (usa - {"True", "False", "None"}):
            partes.append(ast.unparse(n))
import universo as U
import calidad as C


def resumen(g, reg):
    r = g[f"ret_{reg}"]
    cerr = g[~g[f"abierta_{reg}"].astype(bool)]
    rc = cerr[f"ret_{reg}"]
    meses = cerr[f"ruedas_{reg}"] / 21
    return {"Operaciones": len(g), "Cerradas": len(cerr), "% con ganancia": (rc > 0).mean() * 100 if len(rc) else np.nan,
            "Promedio %": rc.mean(), "Mediana %": rc.median(), "Peor %": rc.min(), "Mejor %": rc.max(),
            "Le gana al S&P %": (rc > cerr[f"spy_{reg}"]).mean() * 100 if len(rc) else np.nan,
            "Ganancia por mes %": rc.sum() / meses.sum() if meses.sum() else np.nan}


def correr(etiqueta, lista):
    import importlib, screener
    screener = importlib.reload(screener)
    screener.LISTA_TICKERS = lista
    ns = {"pd": pd, "np": np, "yf": yf, "SCR": screener, "C": C, "st": types.SimpleNamespace()}
    exec("\n\n".join(partes), ns)
    d = ns["datos_reversion"](ns["VERSION_REV"], tuple(ns["REGLAS_REV"]))
    ops = d["ops"].copy()
    fund = screener.descargar_fundamentales(lista)
    niv = {t: v["Nivel"] for t, v in screener.clasificar_niveles(fund).items()}
    ops["Nivel"] = ops["Ticker"].map(niv).fillna("Sin datos")
    print(f"\n===== {etiqueta}: {len(lista)} acciones · niveles: " +
          ", ".join(f"{k} {v}" for k, v in pd.Series(niv).value_counts().items()) + " =====")
    for reg, nom in ns["REGLAS_REV"].items():
        filas = {n: resumen(g, reg) for n, g in ops.groupby("Nivel")}
        filas["TODAS"] = resumen(ops, reg)
        print(f"\n--- {nom} ---")
        print(pd.DataFrame(filas).T.round(1).to_string())
    print("\nOperaciones por nivel y año:")
    print(pd.crosstab(ops["Entrada"].dt.year, ops["Nivel"]).to_string())


nueva = sorted(U.cedears())
arch = U.ARCHIVO
U.ARCHIVO, U._cache = "/no/existe.csv", None
import importlib, screener as S0
S0 = importlib.reload(S0)
vieja = list(S0.LISTA_TICKERS)
U.ARCHIVO, U._cache = arch, None
correr("LISTA VIEJA", vieja)
correr("UNIVERSO AMPLIADO", nueva)
