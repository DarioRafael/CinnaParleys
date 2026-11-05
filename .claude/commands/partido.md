---
description: Análisis completo de un partido con el Cerebro NFL y parlays sugeridos
argument-hint: "[equipo o partido, p. ej. Eagles o PHI vs CHI]"
---
Analiza el partido **$ARGUMENTS** con las herramientas del conector `cerebro-nfl`:

1. **`informe`** primero (salud de cada unidad —OL/DL/LB/CB/S—, bajas y quién absorbe el volumen, QBs,
   ángulos para parlays con evidencia). Luego `partido` para la simulación, líneas (consenso y Playdoit), rankings, factores, lesiones y jugadores clave,
   y `escenarios` para cómo se puede dar el juego (y quién la puede romper).
2. `jugador` para los 3–5 jugadores más relevantes (QBs, RB1, WR1/TE1) y `noticias` del partido si hay algo reciente.
3. Dame:
   - **Cómo veo el partido** (5–8 líneas): quién gana y por qué, marcador probable, ritmo/total, qué puede cambiar el guion.
   - **Lo que cambia esta semana**: bajas por unidad (quién falta en la línea, la secundaria, los LB) y quién
     hereda el volumen; marca cada punto como validado / modelo / contexto.
   - **Escenarios**: tabla con cada escenario (prob., marcador típico) y qué jugadores/picks se disparan en cada uno.
   - **Quién la puede romper** en este partido y en qué escenario.
   - **Lo más sólido** (Súper élite / Élite de este partido, si hay) con probabilidad, momio y VE.
   - **3 parlays de este partido** (mismo partido), con perfiles distintos (segura / balanceada / de guion
     alineado al escenario más probable),
     usando líneas principales de Playdoit cuando existan. Verifica cada uno con `evaluar` y reporta
     probabilidad conjunta, pago y VE.
   - **Qué evitar** (líneas trampa, jugadores en duda, patas que se estorban).
