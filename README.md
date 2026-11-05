# CinnaParleys

*(antes «Cerebro NFL»; la carpeta y el conector `cerebro-nfl` conservan el nombre viejo para no romper nada)*

Analizador y predictor de partidos NFL para armar picks y parlays (Draftea u otras casas): quién gana,
tiempo extra, total de puntos, hándicap y props de jugadores (yardas por pase, carrera y recepción,
recepciones, acarreos, touchdowns…). Clasifica cada pick en **Seguras**, **Valor** o **Arriesgadas**, arma
parlays automáticamente y explica el porqué.

Todo es gratis: no usa APIs de pago ni créditos.

## Instalación en una PC nueva

Requisitos: **Windows 10/11**, **Python 3.12**, **Node.js 20.9 o más nuevo** y **Git**. No necesitas cuentas ni llaves de ninguna API.

1. Clona el repositorio:
   ```bash
   git clone https://github.com/DarioRafael/CinnaParleys.git
   ```
2. Doble clic en `instalar.bat`. Crea el entorno de Python, instala y compila la web, descarga la historia de la
   NFL (2016 a hoy), entrena los modelos, hace la primera actualización y deja listo el conector de Claude
   (`.mcp.json`). **La primera vez tarda un buen rato** (descarga varios cientos de MB).
3. Doble clic en `iniciar.bat` → se abre http://localhost:3100.

Qué **no** viene en el repositorio (se genera solo en cada PC): la base de datos, las descargas, las
simulaciones y los registros (`data/`), y `.mcp.json`. Los modelos ya entrenados sí vienen (`data/models/`).

## Cómo usarlo

1. Doble clic en `iniciar.bat` (o `iniciar_oculto.vbs`) → arranca TODO en segundo plano, sin terminales, y abre http://localhost:3100 cuando está listo (registros en `data/api.log` y `data/web.log`)
2. Al abrirse, si los datos tienen más de 30 minutos, se actualiza solo. Mientras esté abierto:
   - **cada hora**: marcadores, momios de 8 casas, props, lesiones, noticias y clima → recalcula todo
   - **cada día 8:15**: descarga las estadísticas oficiales y recalcula ratings y el modelo de partido
   - **cada martes 9:30**: califica la semana, reentrena los modelos, descarga las líneas reales de la
     semana que terminó, rehace el backtest y reentrena el meta-modelo Élite
   - **día de partido**: cada 10 minutos durante las 2.5 h previas a cada kickoff (inactivos, clima final,
     últimos momios) y marcador en vivo cada 2 minutos
3. Para apagarlo: doble clic en `detener.bat`. El asistente de Claude también enciende la API solo, sin ventana, si está apagada.

Instalación desde cero en otra PC: ver [Instalación en una PC nueva](#instalación-en-una-pc-nueva).

## Pregúntale a Claude (asistente conectado a CinnaParleys)

Claude puede consultar el cerebro directamente (conector MCP en `asistente/mcp_server.py`, registrado en
`.mcp.json`) y razonar contigo: analiza partidos, arma varios parlays y los verifica con la probabilidad real.
Usa tu plan de Claude: **sin créditos ni APIs de pago**.

1. En la app de Claude → pestaña **Code** → nueva sesión en la carpeta `Cerebro_NFL`.
2. La primera vez, aprueba el conector **cerebro-nfl** (si el cerebro no está abierto, lo enciende solo).
3. Pregunta normal, o usa los atajos: `/semana`, `/partido Eagles`, `/parlays presupuesto 500 pesos`.

Herramientas que usa Claude: `semana`, `partido`, `escenarios`, `la_pueden_romper`, `revision`, `jugador`, `picks`, `parlays`, `evaluar` (probabilidad
conjunta de cualquier combinación, con correlaciones), `lesiones`, `noticias`, `rendimiento`, `actualizar`.
Las reglas de cómo debe responder están en `CLAUDE.md`.

## Pantallas

| Pantalla | Qué muestra |
|---|---|
| Semana | Saludo de Cinna, partidos, probabilidades, las picks más seguras y los parlays de Cinna |
| Partido | Ofensiva vs defensa, 20,000 simulaciones, **comparador de 8 casas**, jugadores, picks, lesiones y noticias |
| Picks | Seguras / Valor / Arriesgadas con **mejor precio, valor esperado, apuesta sugerida**, sello **Élite**, historial real de picks así y **rango probable** (dónde cae el jugador 8 de cada 10 partidos vs la línea) |
| **Parlays** | Armados solos: La más segura, Balanceada, Bomba, Mismo partido, Touchdowns, **Solo Élite**, **Pago objetivo** (el más probable para el pago que pidas) y **Guion del partido**. Opción *blindados* (sólo picks sanos y estables) y **cartera** (probabilidad de que salga al menos uno) |
| **Draftea** | Buscador con autocompletar: eliges jugador o equipo, la estadística (yardas de pase/tierra/recepción, recepciones, acarreos, pases completos, TD, spread, total, ganador, puntos del equipo) y la línea ya viene puesta (la de Playdoit o el consenso). Momio opcional (1.80x o -110). Probabilidad al instante, línea blanda y probabilidad de que salgan todas juntas |
| Jugador | Proyección, historial vs la línea, **mercado de 8 casas vs Cinna**, **consenso de expertos** y calculadora para tu línea de Draftea |
| Calculadora | Escribe cualquier línea (jugador o partido) y te da la probabilidad y el momio justo |
| Equipos | Ranking de poder ajustado por rival |
| Noticias | Noticias con impacto, qué cambió Cinna y bajas clave (ordenadas por importancia del jugador) |
| Rendimiento | Aciertos y **retorno** con líneas reales de cierre (Más/Menos, escaleras, TDs), parlays élite, parlays del mismo partido, calibración, pesos aprendidos |

## Fuentes (todas gratuitas)

| Fuente | Para qué |
|---|---|
| nflverse | Jugada por jugada, stats, snaps, rosters, reporte oficial de lesiones, **expected stats** y **Next Gen Stats** |
| **Playdoit** (Altenar) | Casa mexicana de referencia: sus líneas y momios exactos del partido completo (Draftea pone casi las mismas; Draftea no publica sus momios en internet). Permite armar parlays "a la casa" |
| **Action Network** | Momios de **8 casas** (Consenso, Apertura, DraftKings, FanDuel, BetMGM, bet365, Caesars, BetRivers) para partidos y props, con precios |
| **FantasyPros (vía nflverse)** | Consenso semanal de expertos (con historial desde 2020) |
| ESPN | Calendario, marcador en vivo, lesiones de toda la liga, clima, FPI, noticias y props de DraftKings (respaldo) |
| Sleeper | Estado de lesión y práctica (respaldo) y **proyecciones semanales** (segunda opinión, historial 2022-hoy) |
| Open-Meteo | Pronóstico de viento, lluvia y temperatura en el estadio |
| **Kalshi** (API pública, sin clave) | Mercado regulado con dinero real: precio de **cada escalón X+** de jugador (yds, recepciones, TD…), ganador/spread/total del partido **también en vivo**. Historial desde oct-2025 |
| Rotowire, PFT, CBS, Yahoo, Google News | Noticias |
| Bluesky | Insiders de X que también publican ahí (Rapoport, Pelissero, Yates…) |

## Cómo piensa

1. **Ratings de equipo** ajustados por rival y rating del QB titular. El titular se decide con el mercado
   (la casa le pone la línea más alta al QB que jugará); si el mercado no se decide, queda como
   *titular incierto* y sus props salen de seguras y parlays.
2. **Modelo de partido** mezclado con el mercado → **simulación de 20,000 partidos** con lógica de final de
   partido (tiempo extra 5.2% vs 5.5% real). Cada casa se evalúa con su propia línea y precio.
3. **Props**: LightGBM por estadística con volumen × eficiencia, defensa rival, game script, clima, bajas de
   compañeros, **expected stats**, **Next Gen Stats** y **consenso de expertos**.
4. **Tres opiniones**: modelo + mercado sin comisión (consenso de 8 casas) + expertos. La proyección final
   combina modelo y mercado; el valor esperado se calcula con el **mejor momio disponible**.
5. **Parlays**: 20,000 escenarios correlacionados (cópula gaussiana con correlaciones reales entre roles);
   el pago de picks del mismo partido se estima como lo cobraría una casa (sin la ventaja de la correlación).
6. **Aprendizaje**: cada evaluación y cada parlay sugerido se califican al terminar los partidos; se
   aprenden los pesos modelo/mercado para Más/Menos, escaleras, TDs y partidos, y se corrigen sesgos.
7. **Backtest con líneas reales** (`brain/backtest.py`): reconstruye cada apuesta de 2024 a hoy con la
   línea de cierre de 8 casas y lo que el modelo decía *sin ver el futuro*. De ahí salen:
   - el **meta-modelo Élite** (entrenado en 2024, probado en 2025 y en la temporada en curso),
   - la **calibración** (un 60% en pantalla significa 60% real),
   - la validación de **parlays** (de partidos distintos y del mismo partido) y el **CLV**.
8. **Simulación conjunta (escenarios)** (`brain/models/joint.py`, `brain/scenarios.py`): en cada una de las
   20,000 simulaciones de un partido se generan también las estadísticas de todos los jugadores según cómo fue
   ESE partido (si su equipo gana por mucho, el RB corre más y el QB lanza menos; los TDs de cada jugador salen
   de los TDs de su equipo). Las relaciones vienen de datos reales y la probabilidad individual de cada jugador
   no se deforma. De ahí salen los **escenarios** (el favorito domina / cerrado / sorpresa / tiroteo /
   defensivo) con qué picks suben en cada uno, el **medio tiempo**, **quién la puede romper** y la
   probabilidad **exacta** de los parlays del mismo partido (incluye ganador, spread y total).
9. **Esquema** (`brain/features/scheme.py`): cobertura hombre/zona, blitz, presión, caja, play action, motion
   y RPO de cada equipo, y cómo le va a cada jugador contra eso. Es **contexto**: se probó y no mejora las
   proyecciones, así que no las mueve.
10. **Retroalimentación después de cada partido** (`brain/autopsy.py`): en cuanto termina un partido se califica
    y se revisa sola: pronóstico previo vs resultado, cuánto explican la suerte (balones perdidos, TDs de defensa),
    los QBs y los jugadores que se salieron de su rango, qué escenario se dio y qué probabilidad le daba, y el
    veredicto (acierto / suerte / QB / error del modelo). Se lleva el récord **Élite en vivo** y el resumen de la
    temporada contra las casas (pestaña Revisión y Rendimiento → Temporada en vivo).
11. **Incertidumbre del partido**: cambio o duda de QB suma variación real al simulador (+6%, medido en 593
    partidos) y marca el partido; también se muestra la opinión del público (contexto, no señal).
12. **Segunda opinión (Sleeper)** (`brain/ingest/projections.py`): cada proyección se mezcla con la proyección
    independiente de Sleeper, con un peso por estadística aprendido sólo con temporadas pasadas (≈50/50). Error
    1–4% menor en 14 de 15 estadísticas y, contra líneas reales, la línea se mueve hacia el cerebro 66% de las
    veces (antes 62%) y en 2026 calibra mejor que el mercado (log-loss 0.6863 vs 0.6882). Jugadores tocados por
    lesión no se mezclan (su ajuste ya lo hace el módulo de disponibilidad).
13. **Salud de las unidades** (`brain/features/units.py`): titulares de línea ofensiva, línea defensiva, LB, CB
    y safeties (por snaps) que están fuera o en duda según ESPN y el reporte oficial. Probado contra líneas de
    cierre 2016-2026: con un **CB titular fuera, el rival anota +1 a +1.5 pts más de lo que dice la línea**
    (t≈3.7, positivo en cada bloque de temporadas; el Más del total ganó 53-54%) → el simulador le suma +1 pt al
    rival por cada CB titular fuera. Línea ofensiva mermada y LB fuera sólo se muestran como contexto.
14. **Informe de analista** (`brain/informe.py`, pestaña *Informe* del partido y herramienta `informe` de Claude):
    lectura del partido, salud de cada unidad, bajas y **quién absorbe su volumen**, QBs, plan de juego,
    escenarios y **ángulos para parlays con su nivel de evidencia** (validado / modelo / contexto).
15. **Escalones X+ y parlays con la regla de Draftea** (`brain/escaleras.py`, páginas Draftea y Parlays, herramientas
    `escalones`, `parlays` y `parlays_draftea`): en Draftea sólo cabe una Más/Menos de jugador por partido; lo demás son
    escalones fijos. Los escalones son **los que publica Playdoit** (API pública, iguales a los de Draftea: Judkins
    desde 36+) con su momio; si aún no los publica (1–2 días antes), se estiman con su patrón (yardas en saltos de 10
    desde ~20 abajo de la línea, recepciones de 1 en 1, etc.). Para cada escalón, la probabilidad del cerebro:
    validada con ~93 mil escalones reales 2025-26 (88% → salió 88%; 92.5% → 92%). En recepciones, pases y TD de pase
    se usa una distribución de conteo por jugador (binomial negativa/binomial): antes todos los jugadores de un mismo
    rango de proyección salían con la misma probabilidad; ahora predice mejor que la casa en recepciones
    (logloss 0.4163 vs 0.4179). Los escalones más bajos de la casa suelen estar entre 60% y 85%, no en 90%.
16. **Conteos con distribución propia de cada jugador** (`brain/models/props.py`): recepciones, pases completos,
    intentos, TD de pase, acarreos de QB, targets y TDs usan una binomial negativa / binomial con la media de cada
    jugador (antes, todos los del mismo rango de proyección salían con la misma probabilidad). Validado con el
    backtest completo: Súper élite 60.7% → 62.1% (ROI +11% → +15%), Élite 58.7% → 59.4%, log-loss Más/Menos
    0.68875 → 0.68745. Acarreos de RB se quedan con el método anterior (ahí no mejoró).
17. **Modo en vivo** (`brain/live_engine.py`, `brain/models/live_wp.py`, `brain/models/live.py`): cada ~2 minutos,
    para cada partido en juego, la probabilidad de ganar/remontar con un modelo entrenado en ~480 mil jugadas reales
    2016-2025 (marcador, reloj, balón, yarda, oportunidad, tiempos fuera y la línea previa). Validado dejando fuera
    2023, 2024 y 2025: mejor que el modelo de nflverse en general (p. ej. 0.427 vs 0.470 en 2024) y en los 3 primeros
    cuartos; en los últimos 5 minutos es algo menos preciso. Además: marcador y total proyectados (simulación de lo
    que falta desde la yarda real) y cómo van los jugadores contra sus líneas. Antes del partido: "¿y si va perdiendo
    al medio?" (qué tan seguido pasa cada situación y cuánto gana desde ahí).
18. **Retroalimentación por categoría** (`meta.category`): cada tipo de Élite (estadística × lado) lleva su récord
    (backtest de la temporada de prueba y la actual + picks calificados en vivo, con punto de partida bayesiano);
    si cae de 53.5% con muestra suficiente, deja de etiquetarse Élite hasta que se recupere (página Rendimiento).
19. **Top Élite** (modo de parlays por defecto y en la portada): las 6 Élite más probables de la semana, una por
    partido (cabe en la regla de Draftea), combinadas de 2 o 3. Validado en 2025 (temporada que el selector no vio),
    con momio de una casa típica (7% menos de ganancia que el mejor de 8 casas): sueltas 71.3% (108 picks, retorno
    +18%); de 2 patas 50% pagando 2.7x (retorno +37%, intervalo 90% por semanas +13% a +62%); de 3 patas 34% pagando
    4.4x (+57%). El backtest lo recalcula cada semana y la descripción muestra los números vigentes.
    **Pero no todos los años**: probando cada temporada con un selector que no la vio (y sin los momios extremos de
    2023, capturados durante los partidos: su favorito acertaba 93%), los parlays de 2 del Top Élite dieron 2023 −21%,
    2024 +5%, 2025 +39%, 2026 +93% (3 semanas). En las 57 semanas: 54% en positivo y +12% de lo apostado por
    semana; los de 3 patas quedan casi parejos a la larga. En 2023 el cerebro calibró peor que las casas.
20. **Plan de la semana** (`brain/plan.py`, arriba en Parlays, herramienta `plan_semana` de Claude): con tu banca y tu
    perfil te dice qué parlays hacer y cuánto en cada uno, usando el Top Élite revisado con la línea EXACTA de
    Playdoit (si ahí la línea es peor, baja la probabilidad y lo avisa). Perfiles, probados con 21 semanas reales:
    conservador (las 15 combinaciones de 2, 5% de la banca): 76% de semanas en positivo, banca típica ×1.42 en 18
    semanas; medio (3 parlays de 2, 8%): ×1.70; agresivo (2 parlays de 3, 10%): ×1.80 pero 15% de terminar perdiendo.
    El historial del plan usa TODAS las temporadas (57 semanas): perfil conservador al 5% → banca típica ×1.09 en 18
    semanas y 28% de probabilidad de terminar perdiendo. "Modo precaución": si las Élite van por debajo de 52% en las
    últimas 3 semanas (≥40 picks), el plan apuesta la mitad.
    Con las Élite conviene apostar cerca del partido: con la línea final acertaron 62% vs 60% con la de apertura
    (2025) y 57% vs 53% (2026).
21. **Contra el rival, por rol** (`brain/features/matchup.py`): cómo le ha ido a cada ROL (WR1, WR2, WR3, TE, RB1, RB2,
    QB) contra cada defensa respecto a su proyección (sólo partidos anteriores). La auditoría mostró que el cerebro
    no lo aprovechaba del todo (yds de recepción t=8.2, yds por tierra t=5.9, positivo cada temporada) y que la casa
    también lo pasa por alto en parte; pero metido en las proyecciones empeoró el Top Élite (2 patas +37% → +30% en
    2025), así que se usa como EXPLICACIÓN de cada pata ("contra JAX, los WR3 han quedado 40% abajo de lo proyectado
    → a favor de tu pick"), no para mover números.
22. **Récord real del Plan** (`plan.snapshot/grade/record`): cada actualización guarda el plan de la semana y lo congela
    10 minutos antes del primer partido de sus patas; al terminar se califica solo con la línea exacta y se lleva el
    récord de cada perfil (Plan de la semana y `plan_semana`). Empieza en la semana 4 de 2026.
23. **Avisos de tus patas** (`plan.snapshot`, cada actualización y cada 10 min en día de partido): compara cada pata
    del Plan con cómo entró (misma fuente de probabilidad) y avisa si bajó 4+ puntos, si dejó de ser Élite, si el
    jugador aparece en duda/fuera, si cambió la línea o si salió del plan. Se ven en el Plan, en la portada de cambios
    y en `plan_semana`.
24. **Red neuronal** (`brain/models/neural.py`, apagada con `ENABLED = False`): red multi-tarea (todas las
    estadísticas del jugador a la vez). En QB proyecta mejor que los árboles (yds de pase −2.8% de error, igual en
    2023, 2024 y 2025); en RB/WR/TE no. Pero en los picks, comparando limpio 2023-2026 deja-una-temporada-fuera,
    empata (Top Élite sueltas 61.5% vs 61.8%, plan conservador +12% vs +15% por semana, Élite 53.1% vs 52.8%):
    no se usa. El límite no es el tipo de modelo sino la información que el mercado no tenga.
25. **Vigilante de noticias** (`brain/watcher.py`, cada 5 minutos): vigila a los jugadores de tu Plan, a sus
    compañeros de equipo y a las Élite de la semana (~145 jugadores). Revisa el reporte de lesiones de ESPN y las
    noticias nuevas de insiders (Bluesky) y RSS; si algo cambia (fuera, en duda, limitado, regresa, pierde la
    titularidad…) avisa en el Plan y en la portada y lanza una actualización en ese momento. Ejemplo real: "Rams:
    Terrance Ferguson se perdería el domingo · compañero de tu pata (Tyler Higbee: Menos de 3.5 recepciones)".
    Los avisos de línea movida distinguen si a quien ya apostó le quedó mejor o peor línea.
26. **Todo en segundo plano**: `iniciar.bat` → `iniciar_oculto.vbs` arranca API e interfaz sin terminales;
    `detener.bat` las apaga; el conector de Claude usa `pythonw.exe` y enciende la API con consola oculta.
28. **Kalshi** (`brain/ingest/kalshi.py`): mercado de predicción regulado (gratis, sin clave). Publica escaleras
    como las de Draftea ("Barkley 70+ yds", "Collins 5+ recepciones") con precio = probabilidad del mercado.
    - **Escalones**: cada escalón muestra "K 63%" (lo que paga Kalshi por ese mismo número) junto al % del cerebro
      (web, `escalones`, `parlays_draftea`, Plan). Validación con ~19,400 escalones (nov-2025 a feb-2026 y
      2026 sem. 1-3, precio una hora antes de la patada): Kalshi y el cerebro empatan (log-loss 0.554 vs 0.553) y
      **elegir con el cerebro acierta más** (escalones de ~80%: 84.1% vs 82.8% con Kalshi; ~72%: 74.5% vs 70.5%),
      así que NO se mezclan. Lo útil: cuando Kalshi da 3-8 puntos menos que el cerebro, el escalón acierta menos
      (76% vs 80%, 179 casos) → se avisa en naranja y el armador de Draftea lo castiga un poco.
    - **En vivo** (validado, 49 partidos 2026, jugada por jugada): en el **último cuarto** el precio en vivo de
      Kalshi acierta más que nuestro modelo (log-loss 0.304 vs 0.328; mejor en el 96-100% de los remuestreos por
      partido) y en los cuartos 1-3 el modelo es mejor (0.553 vs 0.569). Por eso en el 4o cuarto la probabilidad
      de ganar/remontar es la de Kalshi y antes la del cerebro (`fuente_prob` lo indica). También se muestran el
      spread y el total en vivo de Kalshi: sirven para saber si un momio en vivo de Draftea tiene valor.
29. **Revisión de la semana 4 de 2026** (McMillan 14-192, Adams 4 rec., Allen 4 yds por tierra):
    - La PC estuvo apagada el domingo (2:14 a.m. a 9:46 p.m.): el cerebro decidió con datos del viernes (Coker
      "en duda" 65%, Puka "en duda" 54%) y nunca vio los inactivos. Ahora `plan`, `guiones` y el asistente avisan
      cuando los datos son viejos y hay partido pronto (AVISO_DATOS).
    - **Error corregido (activos)**: al entrenar, la cuota de targets/acarreos se reparte sólo entre los que
      jugaron; al predecir se contaba a todo el roster (suplentes que no se visten) y la suma llegaba a 113% (CAR),
      bajándole la cuota a todos justo cuando faltaba un titular. `pipeline.offense_active` usa lo que hizo cada
      jugador en los últimos 3 partidos (CAR 1.12 → 0.99; McMillan 17.5% → 19.7%, 22.6% sin Coker).
    - **Corredor sin su compañero** (validado 2022-2025, sabiendo quién jugó): el RB principal corrió más de lo
      proyectado las 4 temporadas (acarreos ×1.01-1.06, yds ×1.05-1.16) → ×1.04 / ×1.08 proporcional a la cuota
      que se va (`RB_VAC`).
    - Receptores: con 12%+ de targets liberados el #1 salió 0.93-1.06 según el año (sin sesgo), y aun con el resto
      débil (#2 con <14%) 0.98 → no se ajusta. 16 targets de McMillan fue un extremo, no un patrón.
    - Patas que dependen de un compañero en duda llevan `depende_de` (y se avisa esperar los inactivos).
30. **Parlays con guion** (`brain/guiones.py`, `/api/guiones`, MCP `parlays_con_guion`, arriba en Parlays):
    cada parlay cuenta una historia del partido (volumen liberado, dominio, persecución, tiroteo, trabado, duelo)
    con "va a pasar porque", "en contra", "se cae si" y "evidencia" (qué está validado y qué es contexto). Las
    patas son escalones de Playdoit (o estimados con nuestra mediana si la casa aún no publica) y la probabilidad
    conjunta sale de la simulación del partido. Un guion de volumen sólo sale si el cerebro de verdad le ve más
    volumen al beneficiario; los de dominio/persecución, si la simulación cambia 5%+ sus acarreos/pases.
31. **Los guiones contra líneas REALES** (`brain/guiones_hist.py`, se recalcula cada semana): cada tesis se midió
    contra el Más/Menos de cierre 2024-2026 con el corredor/receptor/QB principal de cada equipo:

    | Historia (apostando al Más) | Casos | Sale el Más | Veredicto |
    |---|---|---|---|
    | QB en partido de pocos puntos (total ≤41.5): yardas | 219 | 56% (58/53/56 por año) | **a favor** |
    | RB del favorito (≥5.5): yardas | 200 | 51% | neutral |
    | QB en total alto (≥48.5): yardas | 171 | 52% | neutral |
    | RB principal sin su compañero: yardas / acarreos | 164 / 182 | 49% / 46% | neutral / trampa |
    | RB del favorito "que corre el reloj": acarreos | 239 | 43.5% (42/45/43) | **trampa** |
    | Receptor #1 cuando falta un compañero: recepciones | 184 | 43% | **trampa** |
    | Receptor #1 del equipo que va abajo: recepciones / yardas | 221 / 200 | 42% / 38.5% | **trampa** |

    Las historias que "todos saben" ya están en la línea (el público las apuesta y la casa la sube). Por eso los
    guiones sólo ofrecen como Más lo neutral o a favor (con su récord a la vista) y las trampas salen al revés en
    **Contra la narrativa**: el Menos en sencilla, sólo si el cerebro también se inclina al Menos.
    Los guiones y los contra se guardan en cada actualización y se califican solos (`guiones_log`, récord en la página).
32. **Perfil Sencillas del Plan**: las 6 Élite sueltas, 1% de la banca cada una. Validación temporada por temporada
    (`python -m scripts.validacion`, deja fuera el año que prueba; 57 semanas): sencillas +3.3% por semana, 53% de
    semanas en positivo, peor semana −78%; conservador (15 parlays de 2) +8.5%, 49%, peor −100%; medio +2.9%;
    agresivo +2.4%. Por año las sencillas: 2023 −14%, 2024 +4%, 2025 +13%, 2026 +40% (3 semanas).
33. **Noticias con negaciones** (semana 6 de 2026): el titular "Cam Ward isn't getting benched, but should Titans
    consider drafting a QB…?" se leía como "pierde la titularidad" y le recortaba 45% de su juego (17 intentos
    proyectados en vez de 33, y hasta salía "Súper élite" al Menos). Ahora `news.extract_events` descarta eventos
    negados ("isn't", "won't", "no plans to"…) y la especulación ("should", "could", "?") para eventos de impacto
    (fuera, banca, IR, liberado, titular, traspaso); reconoce "non-participant"/"isn't participating" como "no
    entrenó"; y en cada actualización se releen las noticias guardadas con las reglas vigentes.
34. **Súper parlay** (`brain/super_parlay.py`, `/api/super_parlay`, MCP `super_parlay`, arriba en Parlays): revisa
    cada pata posible en el escalón MÁS BAJO de la casa (los mínimos reales de Draftea que el usuario guarda con
    `minimos_draftea` / `/api/draftea/minimos`, o los de Playdoit, o estimados) con probabilidad del cerebro, Kalshi,
    rival (defensa y cómo le ha ido a ese rol), guion (si su equipo gana o pierde, de la simulación), salud (en duda,
    regresa de lesión, compañero clave fuera, receptores en duda para el QB, QB en duda para el receptor), viento e
    historias trampa → semáforo verde/amarillo/rojo. Arma parlays de 3/4/5 que maximizan la prob. conjunta (máx. 2
    patas por partido y sólo del mismo jugador), da el plan de juego de cada partido y lo que hay que revisar.
35. **La racha NO predice** (validado 2024-26, 145 mil líneas reales): "lo pasó 5 de 5" no agrega nada a la
    probabilidad del cerebro (los que pasaron todo salieron 70% cuando el cerebro decía 73%; peso de la racha −0.04 en
    las 3 temporadas). Se muestra sólo como contexto.
36. **Reporte oficial con campos vacíos**: el 20-oct-2026 un NaN en "estado de práctica" tumbó la actualización
    completa (no se calificó la semana 6 ni se actualizó nada). `availability._practice` y `_nfl_injuries_week` ya
    toleran campos vacíos.
37. **Desacuerdo modelo-mercado NO es error** (2024-26): cuando la media del modelo y la del mercado difieren 35%+,
    el resultado quedó más cerca del modelo 56-58% de las veces y las Élite ahí acertaron igual o más (2025 60% vs
    59%; 2026 67% vs 52%). Por eso NO hay "freno general"; el freno va en las noticias: "pierde la titularidad" sólo
    recorta con fuente oficial/insider o Rotowire/ESPN, y un QB al que las casas siguen poniendo su línea de titular
    no se recorta por una noticia.
38. **Calibración de escalones por estadística** (55-85%, 2024-26): yds de pase +0.5 pts, yds por tierra −0.7,
    yds de recepción −1.2, acarreos −0.2 → bien. Yds por tierra de QB −3.7 (sólo 2025) y recepciones −6 (casi todo
    de 2024; 2025-26 bien): no se corrigen por ahora.
39. **Mis apuestas** (`brain/apuestas.py`, `/api/mis_apuestas`, MCP `registrar_apuesta` / `mis_apuestas`, tarjeta en
    Parlays): el usuario anota lo que apostó (texto libre + monto + pago); cada pata se revisa con el semáforo del
    súper parlay, se calcula la probabilidad conjunta real y el pago justo; se califica sola con el marcador de ESPN
    y lleva el récord (apostado, cobrado, aciertos por tipo de pata vs lo que decía el cerebro).
40. **El súper parlay se califica solo** (kv `super_log`): cada actualización guarda sus patas (con semáforo) y sus
    parlays; al terminar los partidos se califican → récord por color (¿verde sale más que amarillo?). Además permite
    dos jugadores del mismo partido (QB con su receptor) sólo si la simulación dice que se ayudan (≥3% más juntos).
41. **Limpieza de datos**: Action Network mezcla bajo el mismo mercado las líneas de cuartos y mitades
   (p. ej. "anota TD en el 1er cuarto") y líneas en vivo. El cerebro usa sólo las del **partido completo,
   antes del kickoff**.
42. **Partidos atrasados se ponen al día solos**: si la PC estaba apagada cuando terminó un partido de la semana
    pasada (p. ej. el del lunes), la actualización normal ya sólo bajaba la semana actual y la siguiente, así que se
    quedaba "por jugar": sus picks seguían saliendo como Seguras y nunca se calificaban. Ahora cada actualización
    busca partidos de semanas anteriores sin final (5+ h después del kickoff) y baja su marcador de ESPN
    (`_catch_up_stale` en `brain/pipeline.py`).

## Diseño (CinnaParleys)

- **Tipografías** (Google Fonts, vía `next/font`): **Fredoka** para títulos y la marca (redonda, con carácter) y
  **Nunito** para el cuerpo y los números (suave y muy legible). JetBrains Mono sólo para código.
- **Paleta**: tema claro «Crema» por defecto (masa, canela, glaseado rosa y cielo) y tema oscuro «Chocolate»
  (botón luna/sol; se guarda en `localStorage` como `cinna_theme` y se aplica antes de pintar, sin parpadeo).
  Contrastes de texto medidos con WCAG (texto normal ≥ 4.4:1). Tokens en `web/app/globals.css`.
- **Marca**: logo de balón con espiral de canela (`components/brand.tsx`, `app/icon.svg`) y la mascota **Cinna**
  (rol de canela con cara) en la portada, estados vacíos, cargas («Horneando datos…») y la página 404.
- **Menú** agrupado (La jornada · A jugar · Para entender) con descripción de cada sección; en el celular,
  menú lateral (botón ☰) más barra inferior flotante. Cada página tiene su encabezado (`PageHeader` en `components/ui.tsx`).
- **Menú lateral** (v2): orilla ondulada de papel de repostería, glaseado que gotea detrás del logo, **íconos diseñados**
  (Phosphor Icons, licencia MIT, estilo duotono pintado con la paleta: contorno fuerte + relleno pastel, un tono por
  sección: canela, rosa, cielo, menta, miel, lila; `web/components/icons.tsx`). Nada de emojis, secciones con letra a mano (**Caveat**), una
  píldora que se desliza con rebote a la opción activa, contadores (picks seguras, «nuevo» en noticias), un **boleto**
  con la cuenta regresiva al próximo kickoff (o el marcador en vivo, rotando), el **clip del momento** y consejos de
  Cinna que cambian solos. Interruptor Crema/Chocolate con sol y luna. Todo sale de `/api/menu` (una sola llamada).
- **Cosas que cambian con el momento**: saludo y ánimo de Cinna según la hora (con sueño de noche, emocionada si hay
  partido en vivo), globito con mensajes (cuántas picks te horneó, quién juega pronto), parpadea, flota; el degradado
  del encabezado se mueve despacio; las secciones aparecen escalonadas y los números cuentan solos.
- **Videos** (`/videos`, Noticias, pestaña «Jugadas y videos» de cada partido y página del jugador): clips públicos de
  ESPN en mp4 (sin cuenta ni llave) con jugadores y equipos etiquetados, clasificados en «Para tus apuestas»,
  «Jugada» y «Noticia»; se ven en un reproductor dentro de la app. En partidos en vivo o terminados, la línea de tiempo
  de anotaciones. `brain/ingest/videos.py`, caché de 30 min. **Sólo para ver: no entran al modelo.**
- La portada siempre es la **semana actual** (sin flechas); las semanas pasadas quedan al final como «semanas pasadas»
  (`/?semana=8`).
- En la interfaz y en los textos que genera el motor, al modelo se le dice **Cinna** (no «el cerebro»). Las claves
  internas (`p_cerebro`, `cerebro_vs_mercado`…) siguen igual.

## Probado y descartado

Ideas que se midieron con datos y **no** ayudaron (por eso no están):

| Idea | Resultado |
|---|---|
| Árbitros (cuántos puntos "permiten") | Correlación −0.01 con el resultado contra la línea de cierre (2,473 partidos) |
| Ajustar los TDs de cada jugador al total de puntos del equipo | Mejora de 0.0001 en log-loss: ruido |
| Meta-modelo logístico para reemplazar la probabilidad del cerebro | Peor que la mezcla modelo+mercado; sólo se usa para elegir los Élite |
| Más hiperparámetros / ensambles | El modelo ya está en el techo de lo que dan los datos |
| Ajustar proyecciones por esquema (receptor vs hombre/zona, corredor vs caja, QB vs blitz/presión) | Sin señal en 2025, ni con tendencias del año anterior ni de la misma temporada (t entre −1.4 y +0.2) |
| Recalibrar los juegos grandes (100+ yds, 300+ de pase) | El sesgo cambia de año a año (−20% a +35%); en promedio el modelo ya está calibrado |
| Opinión del público (quiniela ESPN, 591 partidos 2024-26) | Sola predice peor que las casas (log-loss 0.728 vs 0.603) y mezclada empeora (0.631 vs 0.617): sólo se muestra como contexto |
| Predecir intercepciones con el historial del QB (o con "pases de INT" de FTN) | Peor que usar el promedio de la liga: en un partido son casi azar |
| "Mala suerte" en balones perdidos del equipo | +1 pt contra la línea, no significativo (t=1.5) |
| Movimiento fuerte de línea como alerta | Al revés: el favorito final pierde MENOS (25% vs 34%) |
| Viento, desacuerdo modelo-mercado como alerta | +0–2% de variación: ruido |
| Desacuerdo del cerebro con la línea de cierre en partidos (hándicap/total), 2019-2025 | Acierta ~51% (entre 44% y 55% según el año): el peso del simulador en hándicap bajó de 0.8 a 0.5 |
| Ordenar el Top Élite por valor esperado (en vez de probabilidad) | Se ve espectacular pero elige momios atípicos de una de las 8 casas (líneas viejas) que en Draftea no existen |
| Top 4, 8 o 10 en lugar de 6 / Súper élite primero | Top 6 por probabilidad es lo más estable; Súper primero fue peor en 2025 y mejor en 2026 |
| Ajustar las proyecciones por el rival según el ROL (WR1/WR2/…) | Mejora un poco la calibración general pero empeora el Top Élite (2025): sólo se usa como explicación |
| Alarma "rival en contra" para las patas del Top Élite | Sin patrón consistente (muestras chicas): no filtra |
| Red neuronal multi-tarea (proyecciones de QB y de RB/WR/TE) | Mejor precisión en QB pero los picks empatan con los árboles (2023-2026): apagada |
| Selector Élite con más variables (rol, contexto, movimiento de línea), logística o LightGBM | Peor: marca el doble de Élite y aciertan menos (55% vs 59% en 2025) |
| Movimiento de línea (apertura → ahora) para filtrar Élite | Sin señal estable: en 2025 los que se movían en contra acertaron más, en 2026 menos |
| Amplificar las correlaciones de los parlays del mismo partido | Mejora mínima en 2025 (k=1.5) que no se sostiene en 2026: se dejan como están |
| Ordenar las patas del parlay por el récord de su categoría | Sin validación limpia (la categoría se aprendió con la misma temporada): no se usa para elegir |
| Modelo especial de final de partido (últimos 10 min) | No superó al de nflverse en los últimos 5 minutos: se usa el modelo general |
| Proyecciones de Sleeper como señal directa contra la línea | Sola no agrega nada sobre el mercado (coef. ≈0); sirve mezclada con el modelo (arriba) |
| Guiones "obvios" como Más (receptor que se queda con el volumen, corredor del favorito, receptor del que va abajo) | Contra líneas reales 2024-26 el Más salió 39-46%: la casa ya los trae inflados → se ofrecen al revés (Menos) |
| La racha reciente ("lo pasó 5 de 5") como señal extra | 145 mil líneas 2024-26: no agrega (peso −0.04 en las 3 temporadas); sólo contexto |
| Kalshi como filtro de las Élite (Más/Menos .5) | En 1,353 líneas de 2026 Kalshi = consenso de 8 casas (0.6917 vs 0.6915) y el cerebro sigue mejor (0.6893); que Kalshi "confirme" una Élite no subió el acierto |
| Apostar escalones de las casas donde Kalshi ve valor | ROI −17% (235 casos, 2025 y 2026): Kalshi no es un oráculo contra las casas (el cerebro tampoco encuentra valor en escalones: −11%) |
| Kalshi en vivo durante los cuartos 1-3 | Peor que nuestro modelo (sólo mejor en 18% de los remuestreos): ahí manda el cerebro |
| Bajas no habilidosas en props de jugador (CB rival → receptores Más, OL propia → corredor Menos, LB rival → carrera Más) | Signo correcto y el lado favorecido ganó 53-58% en 2025, pero la validación cruzada entre temporadas no fue estable → sólo contexto; lo que sí se aplica es el efecto a nivel partido (CB) |

## Honestidad (backtest con líneas reales, datos limpios)

~190 mil líneas de cierre de 8 casas, 2024–2026. El modelo se entrenó hasta 2024; **2025 es una temporada que
nunca vio** y 2026 es la temporada en curso. Retorno medido al momio típico de una casa (no al mejor precio).

| Más/Menos de jugadores | 2025 | 2026 (sem. 1–3) |
|---|---|---|
| Todas las líneas (lado del cerebro) | 52.0% · +0.5% | 50.5% · −3% |
| "Valor" calculado sin Élite | 50.0% · 0% | 52.4% · +5% |
| **Élite** (nivel Valor) | 57.5% · +6.5% (778) | 58.8% · +9.6% (131) |
| **Súper élite** (nivel Seguro) | **60.7% · +11% (478)** | **59.6% · +7% (89)** |

Con la segunda opinión de Sleeper (sep-2026): Élite+Súper 2025 58.7% (antes 59.6%, dentro del ruido) y 2026
59.1% (antes 54.4%); lo que mejoró claramente es la calibración y el CLV, que se miden con miles de líneas.

- Para ganarle a -110 basta 52.4%. La ventaja real está en los **Súper élite**; los Élite simples son
  apenas positivos y los demás picks de Más/Menos no le ganan al mercado.
- **Escaleras y TDs**: ningún filtro le ganó al margen de la casa a la larga. Las muy probables aciertan ~90%
  pero pagan tan poco que pierden (−4%); sirven como base de parlays, no solas.
- El mercado es muy eficiente: sólo el modelo pierde contra la línea de cierre; la mezcla modelo+mercado la
  iguala en probabilidad y sirve sobre todo para **elegir** (cuando el meta-modelo coincide).
- La línea se movió hacia el lado del modelo 66% de las veces (apertura → cierre), pero para las **Élite** la línea final les fue mejor que la de apertura (62% vs 60% en 2025; 57% vs 53% en 2026): no hay prisa, conviene revisar cerca del partido.
- Los parlays de partidos distintos y del mismo partido salen menos de lo que diría la probabilidad sin
  calibrar; por eso en vivo toda probabilidad pasa por la calibración con resultados reales.
- Estos números se recalculan solos cada martes. Apuesta con responsabilidad.

## Estructura

```
brain/        motor: ingest/ (ESPN, Action Network, expertos, noticias…), features/ (métricas + extra),
              models/ (partido, props, simulador), market.py, parlays.py, availability.py, picks.py,
              backtest.py, meta.py (Élite + calibración), draftea.py, learning.py, pipeline.py
api/          FastAPI (puerto 8765) + programador de actualizaciones
web/          interfaz Next.js (puerto 3100)
scripts/      entrenar.py (entrenamiento completo), historico.py (descarga las líneas reales para el backtest)
data/         caché, modelos y base de datos local (SQLite)
```

## Siguiente paso: la nube (sin PC prendida)

- **Vercel**: la interfaz (`web/`)
- **GitHub Actions**: corre `brain` cada hora/día/semana (gratis)
- **Supabase**: base de datos (basta con definir `DATABASE_URL`; el código ya soporta Postgres)
