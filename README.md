# Screener CEDEARs + Momentum mensual

Dos programas que mandan mails automáticos con un PDF de resumen y un Excel con el detalle.

## 1. Screener diario (reversión) — `screener.py`
Corre de lunes a viernes a las 7:17 (hora Argentina). Estrategia: 139 acciones con CEDEAR en BYMA · caída 25-60% · beta histórico >= 1,3 · S&P sobre su media de 200 días · venta a los 6 meses.
- Agenda: `.github/workflows/screener.yml`
- `cartera.csv` (opcional): tus compras reales, formato `Ticker,Fecha,Precio`.

## 2. Momentum residual mensual — `momentum.py`
Corre los días 1 a 4 de cada mes y manda el mail solo el **primer día hábil**. Usa solo las 139 acciones con CEDEAR en BYMA y muestra el nombre completo de cada empresa (y el código del CEDEAR cuando es distinto: BA.C, BRKB, DISN). Dice qué vender, qué comprar, qué recortar y a qué acciones sumar si aportás plata.
- Agenda: `.github/workflows/momentum.yml`
- No necesita que registres operaciones: lleva una "cartera según el sistema" desde `MOMENTUM_INICIO`.
- Variables opcionales (Settings → Secrets and variables → Actions → pestaña **Variables**):
  - `MOMENTUM_CAPITAL`: tamaño aproximado de tu cartera de momentum en USD (por defecto 10000). Solo cambia los montos que muestra.
  - `MOMENTUM_INICIO`: desde cuándo se lleva la cartera del sistema (AAAA-MM-DD).
  - `MOMENTUM_EXCLUIR`: acciones que no querés o no podés operar, separadas por coma (por ejemplo `RIO, XOM`).
- Correrlo a mano: Actions → Momentum mensual → Run workflow. Si no es el primer día hábil, el mail llega marcado como **ANTICIPO** (no operar).

## Secretos (los mismos para los dos)
Settings → Secrets and variables → Actions → pestaña **Secrets**: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `MAIL_TO`.
