"""
PRECÁLCULO DEL DASHBOARD (GitHub Actions, después del cierre de Nueva York)
==========================================================================
Hace los cálculos pesados de la app y los guarda en la carpeta precalculo/, así la app abre rápido aunque Streamlit la
haya "dormido": nivel de calidad de cada acción, momentum (cartera del sistema y backtest desde 2011) y reversión
(señales y backtest desde 2010). Si algo falla, la app lo calcula en vivo como antes. No manda mails ni toca carteras.
"""
import os
import sys
import traceback

import calculos as CALC


def main():
    inicio = os.environ.get("MOMENTUM_INICIO") or "2026-10-01"
    ok = True
    niveles = {}
    try:
        nv = CALC.niveles_calidad()
        CALC.guardar("niveles", nv)
        niveles = nv["niveles"]
        print(f"Niveles: {len(niveles)} acciones")
    except Exception:       # noqa: BLE001
        traceback.print_exc()
        ok = False
    try:
        d = CALC.datos_momentum(inicio)
        CALC.guardar("momentum", d, cierre=d["cierre"].strftime("%Y-%m-%d"), inicio=inicio)
        print("Momentum al cierre del", d["cierre"].date())
    except Exception:       # noqa: BLE001
        traceback.print_exc()
        ok = False
    try:
        d = CALC.datos_reversion(niveles)
        CALC.guardar("reversion", d, cierre=d["cierre"].strftime("%Y-%m-%d"))
        print("Reversión al cierre del", d["cierre"].date(), "·", len(d["ops"]), "operaciones")
    except Exception:       # noqa: BLE001
        traceback.print_exc()
        ok = False
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
