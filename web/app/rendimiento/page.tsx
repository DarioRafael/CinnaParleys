"use client";

import { ChartLineUp } from "@phosphor-icons/react";
import clsx from "clsx";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { ago, pct, post, useApi } from "@/lib/api";
import { CalibrationChart } from "@/components/charts";
import { Loading, PageHeader, SectionTitle, Stat, TierBadge } from "@/components/ui";
import { RealLines, RealLinesSection } from "@/components/real-lines";
import { Autopsia, Categoria, CategoriesSection, LiveSeason, LiveSeasonSection } from "@/components/review";

type Agg = { n: number; win: number; loss: number; push: number; hit: number; avg_prob: number; roi_110: number | null };
type Perf = {
  total: number;
  tiers: (Agg & { tier: string })[]; markets: (Agg & { market: string })[];
  weeks: (Agg & { season: number; week: number })[];
  calibration: { bin: string; pred: number; real: number; n: number }[];
  props_backtest: Record<string, { n: number; mae: number; mae_baseline: number; mejora_pct: number; calibracion: { bin: string; pred: number; real: number; n: number }[] }> | null;
  game_backtest: Record<string, number> | null;
  calibration_state: { prop_shrink?: number; prop_mu_w?: number; pool_w?: number; alt_w?: number; td_w?: number; game_w?: number;
    bias?: Record<string, number>; history?: { at: string; note: string }[] } | null;
  parlays?: { mode: string; n: number; win: number; hit: number; avg_p: number }[];
  real_lines?: RealLines | null;
};

const STAT_ES: Record<string, string> = {
  pass_att: "Intentos de pase", pass_cmp: "Pases completos", pass_yds: "Yardas por pase", pass_tds: "TDs por pase",
  pass_ints: "Intercepciones", qb_rush_att: "Acarreos QB", qb_rush_yds: "Yardas tierra QB", pass_rush_yds: "Pase + carrera",
  targets: "Targets", receptions: "Recepciones", rec_yds: "Yardas recepción", rush_att: "Acarreos", rush_yds: "Yardas tierra",
  rush_rec_yds: "Yardas totales", tds: "Touchdowns",
};

export default function PerformancePage() {
  const { data, isLoading } = useApi<Perf>("/api/performance");
  const { data: au } = useApi<{ resumen: LiveSeason; partidos: Autopsia[] }>("/api/autopsias");
  const { data: cats } = useApi<{ categorias: Categoria[]; umbral: number }>("/api/categorias");
  const [learning, setLearning] = useState(false);
  if (isLoading && !data) return <Loading />;
  if (!data) return null;
  const gb = data.game_backtest;
  const cs = data.calibration_state;
  const tierOrder = ["segura", "valor", "arriesgada", "sin nivel"];

  return (
    <div className="space-y-6">
      <PageHeader duo={ChartLineUp} tone="menta" kicker="para entender" title="Rendimiento de Cinna"
        right={
          <button disabled={learning} onClick={() => { setLearning(true); post("/api/learn").finally(() => setTimeout(() => setLearning(false), 4000)); }}
            className="inline-flex items-center gap-2 rounded-full border border-line bg-s1 px-3.5 py-2 text-sm font-semibold text-ink2 hover:text-brand disabled:opacity-50">
            <RefreshCw size={15} className={learning ? "spin" : undefined} /> {learning ? "Reentrenando…" : "Reentrenar ahora"}
          </button>
        }>
        <p>Cada evaluación hecha antes del kickoff se califica al terminar el partido. Con eso Cinna se recalibra automáticamente, sin maquillar los números.</p>
      </PageHeader>

      <LiveSeasonSection r={au?.resumen} items={au?.partidos ?? []} />
      <CategoriesSection rows={cats?.categorias ?? []} umbral={cats?.umbral ?? 0.535} />
      <RealLinesSection r={data.real_lines} />

      <section>
        <SectionTitle>Resultados en vivo (temporada actual)</SectionTitle>
        {data.total === 0 ? (
          <div className="card px-5 py-6 text-sm text-ink2">
            Todavía no hay picks calificados: se califican solos en cuanto terminan los partidos que Cinna ya analizó (el primero es el del lunes).
            Mientras tanto, abajo está la validación con temporadas pasadas.
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-4">
            {tierOrder.map((t) => {
              const r = data.tiers.find((x) => x.tier === t);
              if (!r) return null;
              return (
                <div key={t} className="card px-4 py-3">
                  <div className="flex items-center justify-between">{t === "sin nivel" ? <span className="text-xs text-mute">Todas las líneas</span> : <TierBadge tier={t} />}<span className="text-xs text-mute">{r.n} picks</span></div>
                  <div className="mt-2 text-3xl font-semibold">{pct(r.hit, 1)}</div>
                  <div className="text-xs text-ink2">{r.win}-{r.loss}{r.push ? `-${r.push}` : ""} · esperado {pct(r.avg_prob)}{r.roi_110 != null ? ` · ROI ${(r.roi_110 * 100).toFixed(1)}%` : ""}</div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="card p-5">
          <SectionTitle>Calibración en vivo</SectionTitle>
          {data.calibration.length ? (
            <>
              <CalibrationChart bins={data.calibration} />
              <p className="mt-2 text-xs text-ink2">Si los puntos caen sobre la diagonal, cuando Cinna dice 60% se acierta ~60% de las veces.</p>
            </>
          ) : <div className="py-10 text-center text-sm text-mute">Se llena conforme se califican partidos.</div>}
        </div>
        <div className="card p-5">
          <SectionTitle>Lo que ha aprendido</SectionTitle>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Modelo vs mercado (Más/Menos)" value={`${Math.round((cs?.pool_w ?? 0.45) * 100)}%`} sub="el resto viene del consenso de 8 casas" />
            <Stat label="Modelo vs mercado (TDs)" value={`${Math.round((cs?.td_w ?? 0.45) * 100)}%`} sub="mezcla logística" />
            <Stat label="Modelo vs mercado (escaleras)" value={`${Math.round((cs?.alt_w ?? 0.4) * 100)}%`} sub="“al menos X”" />
            <Stat label="Simulador vs mercado (partidos)" value={`${Math.round((cs?.game_w ?? 0.5) * 100)}%`} sub="ganador, hándicap, total" />
          </div>
          {cs?.bias && Object.keys(cs.bias).length > 0 && (
            <div className="mt-4">
              <div className="mb-1.5 text-xs font-semibold text-ink2">Correcciones de sesgo activas</div>
              {Object.entries(cs.bias).map(([k, v]) => (
                <div key={k} className="flex justify-between py-0.5 text-xs"><span className="text-ink2">{STAT_ES[k] ?? k}</span><span className="tnum">{v > 0 ? "+" : ""}{(v * 100).toFixed(1)}%</span></div>
              ))}
            </div>
          )}
          <div className="mt-4 space-y-1.5">
            {(cs?.history ?? []).slice().reverse().slice(0, 6).map((h, i) => (
              <div key={i} className="text-xs text-ink2"><span className="text-mute">{ago(h.at)}:</span> {h.note}</div>
            ))}
            {!cs?.history?.length && <div className="text-xs text-mute">Aún sin ajustes: empieza con los primeros partidos calificados.</div>}
          </div>
        </div>
      </div>

      <section>
        <SectionTitle>Validación con temporadas pasadas (sin ver el futuro)</SectionTitle>
        <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
          {gb && (
            <div className="card p-5">
              <div className="text-sm font-semibold">Modelo de partido · {gb.games} juegos (2019–2025)</div>
              <div className="mt-3 space-y-2 text-sm">
                <Row k="Error del margen · Cinna" v={`${gb.mae_margin_final.toFixed(2)} pts`} />
                <Row k="Error del margen · casas" v={`${gb.mae_margin_market.toFixed(2)} pts`} />
                <Row k="Error del total · Cinna" v={`${gb.mae_total_final.toFixed(2)} pts`} />
                <Row k="Error del total · casas" v={`${gb.mae_total_market.toFixed(2)} pts`} />
                <Row k="Aciertos de ganador" v={pct(gb.straight_up_final, 1)} />
                {gb.ats_hit != null && <Row k={`Hándicap cuando difiere de la línea (${gb.ats_n})`} v={pct(gb.ats_hit, 1)} />}
              </div>
              <p className="mt-3 text-xs text-ink2">En spreads y totales las casas son muy eficientes: Cinna las iguala y busca ventaja en noticias de último momento y en props de jugadores.</p>
            </div>
          )}
          {data.props_backtest && (
            <div className="card overflow-x-auto">
              <table className="w-full min-w-[520px] text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-mute">
                    <th className="px-4 py-2.5 font-medium">Props de jugador (2022–2025)</th>
                    <th className="px-3 py-2.5 text-right font-medium">Partidos</th>
                    <th className="px-3 py-2.5 text-right font-medium">Error</th>
                    <th className="px-3 py-2.5 text-right font-medium">vs promedio simple</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.props_backtest).sort((a, b) => b[1].mejora_pct - a[1].mejora_pct).map(([k, v]) => (
                    <tr key={k} className="border-b border-line last:border-0">
                      <td className="px-4 py-2">{STAT_ES[k] ?? k}</td>
                      <td className="px-3 py-2 text-right text-ink2 tnum">{v.n.toLocaleString("es-MX")}</td>
                      <td className="px-3 py-2 text-right tnum">{v.mae.toFixed(2)}</td>
                      <td className={clsx("px-3 py-2 text-right font-semibold tnum", v.mejora_pct > 1 ? "text-good" : "text-mute")}>
                        {v.mejora_pct > 0 ? "−" : "+"}{Math.abs(v.mejora_pct).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {(data.parlays?.length ?? 0) > 0 && (
        <section>
          <SectionTitle>Parlays sugeridos</SectionTitle>
          <div className="grid gap-3 md:grid-cols-5">
            {data.parlays!.map((p) => (
              <div key={p.mode} className="card px-4 py-3">
                <div className="text-xs text-mute">{p.mode}</div>
                <div className="mt-1 text-2xl font-semibold">{pct(p.hit, 0)}</div>
                <div className="text-xs text-ink2">{p.win} de {p.n} · esperado {pct(p.avg_p, 0)}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {data.weeks.length > 0 && (
        <section>
          <SectionTitle>Por semana (picks con nivel)</SectionTitle>
          <div className="card divide-y divide-[var(--border)]">
            {data.weeks.map((w) => (
              <div key={`${w.season}-${w.week}`} className="flex items-center justify-between px-4 py-2.5 text-sm">
                <span>Semana {w.week}</span>
                <span className="text-ink2 tnum">{w.win}-{w.loss} · {pct(w.hit, 1)}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex justify-between border-b border-line pb-1.5 last:border-0"><span className="text-ink2">{k}</span><span className="font-semibold tnum">{v}</span></div>;
}
