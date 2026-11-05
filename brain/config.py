"""Configuración central del Cerebro NFL."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
FEAT = DATA / "features"
MODELS = DATA / "models"
REPORTS = DATA / "reports"
for _p in (DATA, RAW, FEAT, MODELS, REPORTS):
    _p.mkdir(parents=True, exist_ok=True)

# Local: SQLite. En la nube basta con definir DATABASE_URL (Postgres/Supabase).
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{(DATA / 'cerebro.db').as_posix()}")

# Temporadas usadas para entrenar. 2016+ tiene snap counts y datos de pbp completos.
FIRST_SEASON = 2016

# Simulación
N_SIMS = 20000

# Actualización automática
REFRESH_MINUTES = 60          # cada cuánto corre el refresco ligero
STALE_MINUTES = 30            # al abrir la app, si los datos tienen más de esto, se refresca

# Umbral de cuota estándar -110 → prob. de equilibrio
BREAKEVEN_110 = 110 / 210

HTTP_TIMEOUT = 25
USER_AGENT = "CerebroNFL/1.0 (personal analytics)"

# ------------------------------------------------------------------
# Fuentes de noticias y su nivel de confianza
#   1 = oficial (equipo / reporte de lesiones de la NFL / ESPN estructurado)
#   2 = insider nacional top (Rapoport, Pelissero, Schefter...)
#   3 = medio / reportero de cobertura
#   4 = agregador / rumor
# ------------------------------------------------------------------
RSS_FEEDS = [
    ("Rotowire", "https://www.rotowire.com/rss/news.php?sport=NFL", 3),
    ("ProFootballTalk", "https://www.nbcsports.com/profootballtalk.rss", 3),
    ("CBS Sports", "https://www.cbssports.com/rss/headlines/nfl/", 3),
    ("Yahoo Sports", "https://sports.yahoo.com/nfl/rss/", 4),
    ("Google News", "https://news.google.com/rss/search?q=NFL+(injury+OR+%22ruled+out%22+OR+questionable+OR+activated+OR+%22will+start%22)+when:2d&hl=en-US&gl=US&ceid=US:en", 4),
]

# Cuentas de X que también publican en Bluesky (API pública y gratuita).
BLUESKY_ACCOUNTS = [
    ("rapsheet.bsky.social", "Ian Rapoport", 2),
    ("tompelissero.bsky.social", "Tom Pelissero", 2),
    ("fieldyates.bsky.social", "Field Yates", 2),
    ("profootballtalk.bsky.social", "ProFootballTalk", 3),
    ("nflnewsreposterbot.bsky.social", "NFL News (espejo de X)", 3),
    ("bepryor.bsky.social", "Brooke Pryor", 3),
    ("jourdanrodrigue.bsky.social", "Jourdan Rodrigue", 3),
    ("greggrosenthal.bsky.social", "Gregg Rosenthal", 3),
]

TIER_LABEL = {1: "Oficial", 2: "Insider", 3: "Medio", 4: "Agregador"}
