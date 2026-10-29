"""Compara el backtest de reversión con la lista vieja (139) y con el universo ampliado. Solo imprime; no guarda nada."""
import ast, os, sys, types, warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
sys.path.insert(0, os.getcwd())
fuente = open("dashboard/app.py", encoding="utf-8").read()
arbol = ast.parse(fuente)
nombres = {"evaluar_rev", "_salidas", "simular_cartera_rev", "datos_reversion", "stats_reglas"}
const = {"INICIO_REV", "FILTROS_TXT", "REGLAS_REV", "VERSION_REV"}
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
def correr(etiqueta, lista):
    import importlib, screener
    screener = importlib.reload(screener)
    screener.LISTA_TICKERS = lista
    ns = {"pd": pd, "np": np, "yf": yf, "SCR": screener, "st": types.SimpleNamespace()}
    exec("\n\n".join(partes), ns)
    d = ns["datos_reversion"](ns["VERSION_REV"], tuple(ns["REGLAS_REV"]))
    ops = d["ops"]
    print(f"\n===== {etiqueta}: {len(lista)} acciones =====")
    print(f"Operaciones (señales de compra) desde {ops['Entrada'].min().date() if len(ops) else '-'}: {len(ops)}")
    print("Por año:", ops.groupby(ops["Entrada"].dt.year).size().to_dict() if len(ops) else {})
    print(ns["stats_reglas"](ops).to_string())
    for reg, s in d["carteras"].items():
        s = s.dropna()
        if len(s) > 20:
            anios = (s.index[-1] - s.index[0]).days / 365.25
            print(f"Cartera de 10 lugares, {reg}: {((s.iloc[-1] / s.iloc[0]) ** (1 / anios) - 1) * 100:.1f}% anual, peor caída {((s / s.cummax() - 1).min()) * 100:.1f}%")
    spy = d["spy"]; anios = (spy.index[-1] - spy.index[0]).days / 365.25
    print(f"S&P mismo período: {((spy.iloc[-1] / spy.iloc[0]) ** (1 / anios) - 1) * 100:.1f}% anual")
nueva = sorted(U.cedears())
arch = U.ARCHIVO
U.ARCHIVO, U._cache = "/no/existe.csv", None
import screener as S0
import importlib; S0 = importlib.reload(S0)
vieja = list(S0.LISTA_TICKERS)
U.ARCHIVO, U._cache = arch, None
correr("LISTA VIEJA", vieja)
correr("UNIVERSO AMPLIADO", nueva)
