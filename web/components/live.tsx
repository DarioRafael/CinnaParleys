"use client";

import clsx from "clsx";
import { Activity, TrendingUp } from "lucide-react";
import { pct } from "@/lib/api";
import { SectionTitle, WinBar } from "./ui";

export type LiveStat = { stat: string; label?: string; lleva: number; proyeccion_final: number; linea: number | null; prob_mas: number | null; proy_previa?: number | null };
export type LiveState = {
  at: string; p_home: number; p_away: number; pre_p_home?: number | null;
  estado: { home_score: number; away_score: number; period?: number; clock?: string; texto?: string | null; possession?: string | null };
  final_proyectado?: { home: number; away: number }; total_proyectado?: number; total_q?: number[];
  p_over_linea?: number | null; linea_total?: number | null; p_home_cubre?: number | null; spread?: number | null;
  remontada?: { equipo: string; prob: number } | null;
  fuente_prob?: string; p_home_cerebro?: number;
  kalshi?: { p_home: number; p_over_linea?: number | null; p_home_cubre?: number | null; diferencia?: number } | null;
  historia?: { at: string; p_home: number; score: string; periodo?: number; reloj?: string }[];
  jugadores?: { player_id: string; name: string; team: string; position: string; stats: LiveStat[] }[];
};

function Sparkline({ pts, home }: { pts: number[]; home: string }) {
  if (pts.length < 2) return null;
  const W = 600, H = 90;
  const d = pts.map((p, i) => `${(i / (pts.length - 1)) * W},${(1 - p) * H}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-24 w-full" preserveAspectRatio="none" role="img" aria-label={`Probabilidad de ${home} en el tiempo`}>
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="var(--border)" strokeDasharray="4 4" />
      <polyline points={d} fill="none" stroke="var(--accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function LivePanel({ v, home, away }: { v: LiveState; home: string; away: string }) {
  const st = v.estado;
  const hist = (v.historia ?? []).map((h) => h.p_home);
  const rows = (v.jugadores ?? []).flatMap((p) => p.stats.filter((s) => s.linea != null && s.prob_mas != null)
    .map((s) => ({ ...s, name: p.name, team: p.team })))
    .sort((a, b) => Math.abs((a.prob_mas ?? 0.5) - 0.5) - Math.abs((b.prob_mas ?? 0.5) - 0.5)).slice(0, 14);
  return (
    <section className="card space-y-4 border-accent/40 p-5">
      <SectionTitle right={<span className="text-xs text-mute">se actualiza cada ~2 min</span>}>
        <span className="inline-flex items-center gap-1.5"><Activity size={14} className="text-critical" />En vivo · Q{st.period} {st.clock}{st.texto ? ` · ${st.texto}` : ""}</span>
      </SectionTitle>
      <div className="grid gap-4 md:grid-cols-4">
        <div className="md:col-span-2">
          <div className="flex items-baseline justify-between text-sm">
            <span><b>{away}</b> {pct(v.p_away, 0)}</span>
            <span className="text-[11px] text-mute">antes del partido: {home} {pct(v.pre_p_home, 0)}</span>
            <span>{pct(v.p_home, 0)} <b>{home}</b></span>
          </div>
          <div className="mt-1"><WinBar left={away} right={home} pLeft={v.p_away} height={12} /></div>
          {v.kalshi && (
            <div className="mt-1.5 text-xs text-mute" title="Precio en vivo del mercado de Kalshi (dinero real). Si difiere mucho de Cinna, el mercado suele saber algo (lesión, clima, ritmo).">
              {v.fuente_prob?.startsWith("Kalshi")
                ? <>Último cuarto: la probabilidad es la del <b className="text-ink2">mercado en vivo (Kalshi)</b>, que en 2026 acertó más que el modelo al final. Modelo: {home} {pct(v.p_home_cerebro, 0)}</>
                : <>Mercado en vivo (Kalshi): <b className="text-ink2 tnum">{home} {pct(v.kalshi.p_home, 0)}</b>
                  {Math.abs(v.kalshi.diferencia ?? 0) >= 0.08 && <span className="ml-1 text-warning">· difiere de Cinna {Math.round(Math.abs((v.kalshi.diferencia ?? 0) * 100))} pts</span>}</>}
            </div>
          )}
          {v.remontada && (
            <div className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-[var(--warning)]/15 px-2 py-1 text-sm text-warning">
              <TrendingUp size={14} /> {v.remontada.equipo} remonta y gana: <b className="tnum">{pct(v.remontada.prob, 0)}</b>
            </div>
          )}
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wider text-mute">Final proyectado</div>
          <div className="text-lg font-semibold tnum">{away} {Math.round(v.final_proyectado?.away ?? 0)} – {Math.round(v.final_proyectado?.home ?? 0)} {home}</div>
          {v.p_home_cubre != null && v.spread != null && <div className="text-xs text-mute">{home} cubre {v.spread > 0 ? "-" : "+"}{Math.abs(v.spread)}: {pct(v.p_home_cubre, 0)}{v.kalshi?.p_home_cubre != null && <span> · Kalshi {pct(v.kalshi.p_home_cubre, 0)}</span>}</div>}
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wider text-mute">Total</div>
          <div className="text-lg font-semibold tnum">{Math.round(v.total_proyectado ?? 0)} <span className="text-xs font-normal text-mute">(80%: {v.total_q?.[0]}–{v.total_q?.[2]})</span></div>
          {v.linea_total != null && <div className="text-xs text-mute">Más de {v.linea_total}: {pct(v.p_over_linea, 0)}{v.kalshi?.p_over_linea != null && <span> · Kalshi {pct(v.kalshi.p_over_linea, 0)}</span>}</div>}
        </div>
      </div>
      {hist.length > 1 && (
        <div>
          <div className="text-[11px] text-mute">Probabilidad de {home} durante el partido</div>
          <Sparkline pts={hist} home={home} />
        </div>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-mute">Jugadores contra su línea (los más en duda)</div>
          <table className="w-full min-w-[520px] text-sm">
            <thead><tr className="text-left text-[11px] uppercase tracking-wider text-mute">
              <th className="pb-1 font-medium">Jugador</th><th className="pb-1 text-right font-medium">Lleva</th>
              <th className="pb-1 text-right font-medium">Proyección final</th><th className="pb-1 text-right font-medium">Línea</th>
              <th className="pb-1 text-right font-medium">Más</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name + r.stat} className="border-t border-line">
                  <td className="py-1 text-ink2">{r.name} <span className="text-xs text-mute">{r.label ?? r.stat}</span></td>
                  <td className="py-1 text-right tnum">{r.lleva}</td>
                  <td className="py-1 text-right tnum">{r.proyeccion_final}</td>
                  <td className="py-1 text-right tnum text-mute">{r.linea}</td>
                  <td className={clsx("py-1 text-right font-semibold tnum", (r.prob_mas ?? 0) >= 0.6 ? "text-good" : (r.prob_mas ?? 0) <= 0.4 ? "text-critical" : "")}>{pct(r.prob_mas, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[11px] text-mute">Probabilidad de ganar: modelo entrenado con ~480 mil jugadas reales (marcador, reloj, balón, yarda, tiempos fuera y la línea previa).
        Validado 2023-2025: mejor que el de nflverse en general y en los primeros 3 cuartos; en los últimos 5 minutos es algo menos preciso.</p>
    </section>
  );
}

export function Caminos({ c }: { c: Record<string, { situacion: string; prob_de_estar: number; gana_desde_ahi: number }[]> }) {
  return (
    <div className="card p-4">
      <SectionTitle right={<span className="text-xs text-mute">al medio tiempo</span>}>¿Y si va perdiendo (o ganando)?</SectionTitle>
      <div className="grid gap-4 md:grid-cols-2">
        {Object.entries(c).map(([t, rows]) => (
          <table key={t} className="w-full text-sm">
            <thead><tr className="text-left text-[11px] uppercase tracking-wider text-mute">
              <th className="pb-1 font-medium">{t} al medio</th><th className="pb-1 text-right font-medium">Pasa</th><th className="pb-1 text-right font-medium">Gana desde ahí</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.situacion} className="border-t border-line">
                  <td className="py-1 text-ink2">{r.situacion}</td>
                  <td className="py-1 text-right tnum text-mute">{pct(r.prob_de_estar, 0)}</td>
                  <td className={clsx("py-1 text-right font-semibold tnum", r.gana_desde_ahi >= 0.5 ? "text-good" : r.gana_desde_ahi < 0.25 ? "text-critical" : "")}>{pct(r.gana_desde_ahi, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-mute">"Pasa" sale de la simulación del partido; "gana desde ahí", del modelo en vivo entrenado con jugadas reales.</p>
    </div>
  );
}
