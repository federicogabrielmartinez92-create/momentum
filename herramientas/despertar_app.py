"""Abre la app de Streamlit como si fuera un visitante, para que no se "duerma" y deje cargados los datos.
Si Streamlit la había dormido, toca el botón para despertarla. Lo corre GitHub Actions (despertar.yml) cada pocas horas."""
import os
import sys

from playwright.sync_api import sync_playwright

URL = (os.environ.get("APP_URL") or "https://estrategias-cedears.streamlit.app/").rstrip("/")
PAGINAS = ["", "/calidad", "/momentum", "/reversion", "/explorador"]

with sync_playwright() as pw:
    nav = pw.chromium.launch()
    pag = nav.new_page()
    pag.goto(URL, timeout=120_000)
    pag.wait_for_timeout(8_000)
    boton = pag.get_by_role("button", name="Yes, get this app back up!")
    if boton.count():
        print("La app estaba dormida: despertándola...")
        boton.first.click()
        pag.wait_for_timeout(120_000)
    if "share.streamlit.io" in pag.url or "login" in pag.url.lower():
        print("La app pide iniciar sesión (es privada): no se puede despertar así.")
        sys.exit(0)
    for p in PAGINAS:
        try:
            pag.goto(URL + p, timeout=180_000)
            pag.wait_for_timeout(20_000)        # tiempo para que la app termine de calcular y guarde en memoria
            print("Visitada:", URL + p)
        except Exception as e:      # noqa: BLE001
            print("No se pudo abrir", URL + p, e)
    nav.close()
