"""Validación temporada por temporada (deja-una-fuera): Élite, Top Élite y perfiles del Plan.

Para cada temporada con líneas reales se entrena la mezcla y el selector Élite SIN esa temporada y se mide en ella.
Escribe data/models/validacion_temporadas.json (lo usan el Plan y la descripción del Top Élite).
Uso:  python -m scripts.validacion
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from brain import backtest as BT
from brain.config import MODELS

SEASONS = (2023, 2024, 2025, 2026)
CACHE_2023 = MODELS / "bt_opp_2023.parquet"


def _opportunities() -> pd.DataFrame:
    cur = pd.read_parquet(MODELS / "bt_opportunities.parquet")
    if CACHE_2023.exists():
        old = pd.read_parquet(CACHE_2023)
    else:                                   # 2023 no cambia: se construye una vez (sin tocar el archivo de producción)
        orig = pd.DataFrame.to_parquet

        def guard(self, path, *a, **k):
            if str(path).endswith("bt_opportunities.parquet"):
                return None
            return orig(self, path, *a, **k)
        pd.DataFrame.to_parquet = guard
        try:
            old = BT.build_opportunities((2023,))
        finally:
            pd.DataFrame.to_parquet = orig
        old.to_parquet(CACHE_2023, index=False)
    opp = pd.concat([old[old["season"] == 2023], cur[cur["season"] != 2023]], ignore_index=True)
    return opp[opp["p_mkt"].notna() & opp["p_model"].notna()].reset_index(drop=True)


def main() -> dict:
    opp = _opportunities()
    out = {"nota": ("Selector entrenado con las demás temporadas (nunca con la que se prueba). Sin momios extremos "
                    "(en 2023 había líneas capturadas durante el partido). Momio de casa típica."),
           "temporadas": {}, "plan_semanas": {k: [] for k in BT.PLAN_STRATS}}
    for s in SEASONS:
        tr_all = opp[opp["season"] != s]
        mix = BT.tune_mix(tr_all)
        o = opp.copy()
        o["p_heur"] = BT.heur_prob(o, mix)
        d = o[o["kind"] == "ou"].reset_index(drop=True)
        tr, te = d[d["season"] != s], d[d["season"] == s].reset_index(drop=True)
        if len(te) < 200:
            continue
        sel = BT.fit_selector(tr, tr["p_heur"].values)
        pb = sel.predict_proba(BT.selector_features(te, te["p_heur"].values))[:, 1]
        eh, wh, sh, dh = BT._side_ev(te, te["p_heur"].values)
        eb, _, sb, _ = BT._side_ev(te, pb)
        elite = (eh >= 0.03) & (eb >= 0.03) & (sh == sb)
        side_p = np.where(sh == "over", te["p_heur"].values, 1 - te["p_heur"].values)
        top = BT.top_elite_validation(te, elite, wh, side_p, dh)
        pw = BT.plan_weeks(te, elite, wh, side_p, dh)
        plan = {}
        for k, w in pw.items():
            out["plan_semanas"][k] += w
            plan[k] = {"semanas": len(w), "positivas": float(np.mean([x > 0 for x in w])) if w else None,
                       "retorno_medio": float(np.mean(w)) if w else None}
        out["temporadas"][str(s)] = {
            "semanas": int(te["week"].nunique()),
            "logloss_mercado": BT._ll(te["p_mkt"].values, te["y"].values),
            "logloss_cerebro": BT._ll(te["p_heur"].values, te["y"].values),
            "elite": BT._sel_stats(elite, wh, dh), "top_elite": top, "plan": plan}
        print(s, "Élite", out["temporadas"][str(s)]["elite"], "| top sueltas", top.get("patas"),
              "| plan", {k: (v["semanas"], round(v["retorno_medio"] or 0, 3), round(v["positivas"] or 0, 2)) for k, v in plan.items()})
    (MODELS / "validacion_temporadas.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, w in out["plan_semanas"].items():
        w = np.array(w)
        print(f"{k:12s} semanas {len(w)} retorno medio {w.mean():+.3f} positivas {np.mean(w > 0):.2f} peor {w.min():+.2f} desv {w.std():.2f}")
    return out


if __name__ == "__main__":
    main()
