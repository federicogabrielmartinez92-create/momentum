# Streamlimits: Screener CEDEARs + Momentum mensual + Cartera de calidad

Tres programas que mandan mails automáticos con un PDF de resumen y un Excel con el detalle.

## 0. Universo: todas las acciones con CEDEAR — `universo.py`
Los tres programas y el dashboard usan **una sola lista**, `universo.csv`: todas las acciones con CEDEAR en BYMA que cotizan en
EE.UU. (más de 300). Calidad usa las que presentan balances en la SEC; momentum y el screener, todas. El filtro de USD 20 M
por día lo sigue aplicando cada estrategia en cada fecha.
- `cedears_byma.csv`: el listado de CEDEARs de BYMA (código, ratio y símbolo en EE.UU.). Cuando BYMA sume uno, se agrega una línea.
- `universo.csv` lo arma solo el workflow **Universo de CEDEARs** (Actions), el día 27 de cada mes: mira en Yahoo y en la SEC qué
  es cada CEDEAR (acción o ETF, sector, volumen, web para el logo, si presenta balances) y, para las extranjeras, cuántas
  acciones representa cada ADR. Quedan afuera los ETF, las acciones que cotizan solo en Brasil, las dadas de baja y las que
  cotizan fuera de bolsa. En el registro de la corrida se ve el resumen.
- Si `universo.csv` no está, todo funciona como antes, con la lista fija de 139.
- Para correr el backtest en Colab, subir también `universo.py` y `universo.csv`.

**Después de cambiar el universo (o las reglas), en este orden:** Actions → *Universo de CEDEARs* → Run workflow;
después *Backtest de calidad* → Run workflow (rehace la historia desde 2011 del dashboard, tarda un rato; no toca la cartera
real); y por último *Explorador del dashboard* → Run workflow.

## 1. Screener diario (reversión) — `screener.py`
Corre de lunes a viernes de madrugada (hora Argentina). Estrategia: todas las acciones con CEDEAR del universo · caída 25-60% · beta histórico >= 1,3 · S&P sobre su media de 200 días · venta a los 6 meses.
- Agenda: `.github/workflows/screener.yml`
- `cartera.csv` (opcional): tus compras reales, formato `Ticker,Fecha,Precio`.

## 2. Momentum residual mensual — `momentum.py`
Corre los días 1 a 4 de cada mes y manda el mail solo el **primer día hábil**. Usa todas las acciones con CEDEAR del universo (`universo.csv`) y muestra el nombre completo de cada empresa (y el código del CEDEAR cuando es distinto: BA.C, BRKB, DISN). Dice qué vender, qué comprar, qué recortar y a qué acciones sumar si aportás plata.
- Agenda: `.github/workflows/momentum.yml`
- No necesita que registres operaciones: lleva una "cartera según el sistema" desde `MOMENTUM_INICIO`.
- Variables opcionales (Settings → Secrets and variables → Actions → pestaña **Variables**):
  - `MOMENTUM_CAPITAL`: tamaño aproximado de tu cartera de momentum en USD (por defecto 10000). Solo cambia los montos que muestra.
  - `MOMENTUM_INICIO`: desde cuándo se lleva la cartera del sistema (AAAA-MM-DD).
  - `MOMENTUM_EXCLUIR`: acciones que no querés o no podés operar, separadas por coma (por ejemplo `RIO, XOM`).
- Correrlo a mano: Actions → Momentum mensual → Run workflow. Si no es el primer día hábil, el mail llega marcado como **ANTICIPO** (no operar).

## 3. Cartera de calidad (largo plazo, 10 empresas) — `calidad.py`
Arma y mantiene una cartera concentrada de 10 empresas de calidad entre las acciones con CEDEAR (incluye Nu), para invertir a 5-10 años. Corre los días 15 a 18 de cada mes a las 19:23 (hora Argentina, después del cierre de Nueva York) y actúa solo el **primer día hábil desde el 15**; se opera al día siguiente.
- **Qué mira** (balances anuales de la SEC de EE.UU., últimos 5 años, con el mismo programa que el backtest): rentabilidad sobre el capital invertido (ROIC; en bancos, ROE), margen bruto, crecimiento de ventas y de caja por acción, deuda, conversión de ganancias en caja, dilución, precio y tendencia.
- **Precio:** rendimiento esperado a 10 años, con base en el promedio de flujo de caja y ganancia neta (para no castigar a las que invierten fuerte en IA) y el crecimiento de las ventas frenándose con los años.
- **Tendencia:** momentum residual (el mismo del momentum mensual).
- **Qué compra:** entre las 20 mejores en calidad, en el orden de un ranking combinado (50% calidad, 25% precio, 25% tendencia). Quedan afuera las de precio extremo (menos de 5% anual esperado) y las del 10% de peor tendencia. Así siempre hay 10 empresas de calidad en cartera.
- **Vende** solo si la tesis se rompe. Para comprar se pide ROIC de 12% y ventas creciendo 5%; para seguir en cartera alcanza con 10% y 3% (zona de tolerancia: entre medio no se vende ni se suma). En febrero, mayo, agosto y noviembre, además, cambia la que cayó del puesto 20 de calidad o quedó en la zona de tolerancia por la mejor del ranking combinado; la que entra recibe como mucho el 10%. **Nunca vende porque bajó el precio, pero tampoco sugiere comprar más**: si cae más de 25% contra el S&P, la marca para que la revise el equipo.
- **Recorta** si una posición pasa del 25% o si el precio es extremo (menos de 5% anual esperado).
- **Memoria:** la cartera queda guardada en `cartera_calidad.json`, que GitHub actualiza solo después de cada revisión oficial. No hay que tocarlo.
- `tesis_calidad.csv` (opcional): la tesis escrita de cada empresa (ventaja competitiva, gerencia), formato `Ticker,Tesis`. Aparece en el PDF todos los meses.
- Correrlo a mano: Actions → Cartera de calidad → Run workflow.
  - Sin tildar nada = **CONSULTA**: manda el mail pero no guarda nada.
  - Tildando **operar** = queda como revisión oficial. Sirve para arrancar la cartera el día que quieran, sin esperar al 15.
- Variable **obligatoria**: `CALIDAD_SEC_AGENTE`, con tu nombre y mail (por ejemplo `Juan Perez juan@mail.com`); la SEC pide identificarse para bajar balances.
- Las extranjeras que presentan con normas internacionales (TSMC, ASML, SAP, Novartis, etc.) se valúan en dólares con la cotización de su moneda; entran las que tienen la relación ADR cargada a mano (`ADR_RATIO` en calidad.py, que manda) o estimada por `universo.py`. Quedan afuera de calidad algunas empresas cuyos datos no se leen bien de forma automática (Ford y GM por su financiera; las chinas que reportan en yuanes y cotizan como ADR: JD, Alibaba, Baidu, NIO, PDD, NetEase, Trip.com, XPeng, Weibo y JOYY), igual que en el backtest.
- Variables opcionales: `CALIDAD_CAPITAL` (tamaño de referencia en USD, por defecto 10000) y `CALIDAD_EXCLUIR` (acciones que el equipo no quiere, separadas por coma; por ejemplo, si no cree en la tesis de una empresa).
- **Backtest:** `backtest_calidad.py` simula estas mismas reglas mes a mes desde 2011 con los balances históricos de la SEC, usando las mismas funciones que el mail. Se corre en Google Colab (instrucciones al principio del archivo) y al final deja `cartera_calidad.json` con la cartera como terminó, para que el mail continúe desde ahí.
- Si el paso "Guardar la memoria de la cartera" falla por permisos: Settings → Actions → General → Workflow permissions → **Read and write permissions**.

## 4. Dashboard (web privada) — `dashboard/app.py`
Una web con dos secciones, cada una con las pestañas Resumen (qué hacer, aportes, alertas), Cartera, Evolución (desde 2011, con año por año), Operaciones (historial completo con filtros y ventas con su resultado), Ranking y Cómo funciona. **Calidad** usa la cartera que guarda el mail (`cartera_calidad.json`), la última revisión (`panel_calidad.json`) y la historia del backtest (`historial_calidad.json`). **Momentum** se recalcula en vivo con el mismo código del mail, incluido su backtest desde 2011.
- Se publica gratis en Streamlit Community Cloud (share.streamlit.io) → Create app → este repositorio, rama principal, archivo `dashboard/app.py`.
- En **Advanced settings → Secrets** van los mismos datos que las variables del momentum:
  ```
  MOMENTUM_INICIO = "2026-10-01"
  MOMENTUM_CAPITAL = "10000"
  ```
- Con el repositorio privado, la app es privada: en la app → Settings → Sharing se invitan los mails que pueden entrar.
- Se actualiza sola: cada vez que el mail mensual guarda la cartera en GitHub, la web toma los datos nuevos.

## 5. Explorador y fichas de empresa (dashboard)
Página **Explorador**: todas las empresas del universo, con buscador, filtros por sector y estrategia, y orden por cualquier
columna. Tocando una fila se abre la **ficha**: métricas de 5 años (balances de la SEC), filtros mínimos de calidad, precio
contra el S&P y qué dice cada estrategia. Los datos los actualiza el workflow **Explorador del dashboard** (domingos), la
revisión mensual de calidad, el momentum (`panel_momentum.json`) y el screener diario (`panel_screener.json`).
- **Logos:** por defecto, el ícono de la web de cada empresa. Para logos de mejor calidad, crear una cuenta gratis en
  logo.dev y cargar su clave pública en Streamlit → Settings → Secrets: `LOGO_DEV_TOKEN = "pk_..."`.

## Secretos (los mismos para los tres)
Settings → Secrets and variables → Actions → pestaña **Secrets**: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `MAIL_TO`.
