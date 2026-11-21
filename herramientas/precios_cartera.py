"""Prueba aparte: cierres diarios de las acciones de la cartera de calidad desde su arranque."""
import yfinance as yf
t = ["ABNB", "NVDA", "MU", "ADBE", "MA", "META", "DECK", "MELI", "YELP", "TS", "SPY"]
raw = yf.download(t, start="2026-10-12", auto_adjust=True, group_by="ticker", progress=False, threads=False)
import pandas as pd
px = pd.DataFrame({x: raw[x]["Close"] for x in t}).dropna(how="all")
px.index = px.index.strftime("%Y-%m-%d")
px.round(4).to_json("resultado_precios_cartera.json", orient="split")
print(px.tail(3))
