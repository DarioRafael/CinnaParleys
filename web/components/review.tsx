"use client";

import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Dice5, Search, UserRound, Users } from "lucide-react";
import { pct } from "@/lib/api";
import { SectionTitle } from "./ui";

export type Autopsia = {
  game_id: string; partido: string; kickoff: string; marcador: Record<string, number>; ganador: string | null;
  cerebro: { favorito: string; prob_favorito: number; prob_ganador_real: number | null; margen_proyectado: number; total_proyectado: number };
  mercado: { prob_local: number | null; spread_local: number | null; total: number | null };
  acerto_ganador: boolean | null; error_margen: number; error_total: number;
  suerte: { balones_perdidos: Record<string, number | null>; td_no_ofensivos: Record<string, number>; puntos_por_suerte_local: number; error_sin_suerte: number };
  estadisticas: Record<string, Record<string, string | null>>;
  escenario?: { se_dio: string; prob_que_le_daba: number | null };
  jugadores_fuera_de_rango: { jugador: string; equipo: string; stat: string; real: number; proyeccion: number | null; rango80: number[]; direccion: string }[];
  qbs: { qb: string; equipo: string; yds_pase: number; proyeccion: number | null; rango80: number[]; td?: number; int?: number; fuera_de_rango: string | null }[];
  picks: Record<string, { aciertos: number; fallos: number }>;
  veredicto: { tipo: string; texto: string };
};
export type LiveSeason = {
  partidos?: number; ganador_acertado?: number; logloss_cerebro?: number | null; logloss_mercado?: number | null;
  error_medio_margen?: number; tipos_de_resultado?: Record<string, number>; elite_en_vivo?: { aciertos: number; fallos: number };
  super_elite_en_vivo?: { aciertos: number; fallos: number }; prob_media_del_escenario_que_se_dio?: number | null; nota?: string;
};

const STAT_ES: Record<string, string> = { pass_yds: "yds de pase", rush_yds: "yds por tierra", rec_yds: "yds de recepción", receptions: "recepciones" };
export const VERDICT: Record<string, { label: string; icon: typeof Dice5; cls: string }> = {
  acierto: { label: "Lo leyó bien", icon: CheckCircle2, cls: "text-good" },
  suerte: { label: "Decidió la suerte", icon: Dice5, cls: "text-warning" },
  qb: { label: "QB fuera de lo esperado", icon: UserRound, cls: "text-accent" },
  modelo: { label: "Error del modelo", icon: AlertTriangle, cls: "text-critical" },
};

function Rec({ r }: { r?: { aciertos: number; fallos: number } }) {
  if (!r || r.aciertos + r.fallos === 0) return <span className="text-mute">—</span>;
  return <span className="tnum"><b className="text-ink">{r.aciertos}</b>–{r.fallos} <span className="text-mute">({pct(r.aciertos / (r.aciertos + r.fallos), 0)})</span></span>;
}

export function ReviewPanel({ a }: { a: Autopsia }) {
  const v = VERDICT[a.veredicto.tipo] ?? VERDICT.modelo;
  const [A, H] = a.partido.split(" @ ");
  const Icon = v.icon;
  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className={clsx("flex items-center gap-2 text-sm font-semibold", v.cls)}><Icon size={17} /> {v.label}</div>
        <p className="mt-1.5 text-[15px] text-ink">{a.veredicto.texto}</p>
        <div className="mt-4 grid gap-3 text-sm sm:grid-cols-4">
          <div><div className="text-[11px] uppercase tracking-wider text-mute">Resultado</div>
            <div className="font-semibold tnum">{A} {a.marcador[A]} – {H} {a.marcador[H]}</div></div>
          <div><div className="text-[11px] uppercase tracking-wider text-mute">Cinna decía</div>
            <div className="font-semibold">{a.cerebro.favorito} {pct(a.cerebro.prob_favorito)}</div>
            <div className="text-xs text-mute">al ganador real le daba {pct(a.cerebro.prob_ganador_real)}</div></div>
          <div><div className="text-[11px] uppercase tracking-wider text-mute">Escenario que se dio</div>
            <div className="font-semibold">{a.escenario?.se_dio ?? "—"}</div>
            {a.escenario?.prob_que_le_daba != null && <div className="text-xs text-mute">le daba {pct(a.escenario.prob_que_le_daba)}</div>}</div>
          <div><div className="text-[11px] uppercase tracking-wider text-mute">Error en el margen</div>
            <div className="font-semibold tnum">{Math.abs(a.error_margen).toFixed(0)} pts</div>
            <div className="text-xs text-mute">sin la suerte: {Math.abs(a.suerte.error_sin_suerte).toFixed(0)} pts</div></div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-4">
          <SectionTitle>Suerte y estadísticas</SectionTitle>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-[11px] uppercase tracking-wider text-mute"><th className="pb-1.5 font-medium"></th>
              <th className="pb-1.5 text-right font-medium">{A}</th><th className="pb-1.5 text-right font-medium">{H}</th></tr></thead>
            <tbody>
              <tr className="border-b border-line"><td className="py-1.5 text-ink2">Balones perdidos</td>
                {[A, H].map((t) => <td key={t} className="py-1.5 text-right font-semibold tnum">{a.suerte.balones_perdidos[t] ?? "—"}</td>)}</tr>
              <tr className="border-b border-line"><td className="py-1.5 text-ink2">TDs de defensa / especiales</td>
                {[A, H].map((t) => <td key={t} className="py-1.5 text-right tnum">{a.suerte.td_no_ofensivos[t] ?? 0}</td>)}</tr>
              {["Total Yards", "3rd down efficiency", "Red Zone (Made-Att)", "Possession", "Penalties", "Sacks-Yards Lost"].map((k) => (
                <tr key={k} className="border-b border-line last:border-0"><td className="py-1.5 text-ink2">{({ "Total Yards": "Yardas totales", "3rd down efficiency": "3ª oportunidad", "Red Zone (Made-Att)": "Zona roja", Possession: "Posesión", Penalties: "Castigos", "Sacks-Yards Lost": "Capturas recibidas" } as Record<string, string>)[k]}</td>
                  {[A, H].map((t) => <td key={t} className="py-1.5 text-right tnum text-ink2">{a.estadisticas[t]?.[k] ?? "—"}</td>)}</tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-mute">Cada balón perdido vale ≈ 4.5 pts. Medido 2022-2025: en un partido son casi puro azar, por eso cuentan como suerte.</p>
        </div>
        <div className="card p-4">
          <SectionTitle>QBs y jugadores fuera de su rango</SectionTitle>
          <ul className="space-y-1.5 text-sm">
            {a.qbs.map((q) => (
              <li key={q.qb} className="flex justify-between gap-3">
                <span className="text-ink2">{q.qb} <span className="text-xs text-mute">{q.equipo}</span></span>
                <span className="tnum">{q.yds_pase.toFixed(0)} yds{q.td != null ? `, ${q.td} TD, ${q.int ?? 0} INT` : ""}
                  <span className="text-xs text-mute"> (proy. {q.proyeccion?.toFixed(0)}, rango {q.rango80[0].toFixed(0)}–{q.rango80[1].toFixed(0)})</span></span>
              </li>
            ))}
          </ul>
          <div className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-mute">Se salieron del rango del 80%</div>
          <ul className="mt-1 space-y-1 text-sm">
            {a.jugadores_fuera_de_rango.length ? a.jugadores_fuera_de_rango.map((j, i) => (
              <li key={i} className="flex justify-between gap-3">
                <span className="text-ink2">{j.jugador} <span className="text-xs text-mute">{j.equipo} · {STAT_ES[j.stat] ?? j.stat}</span></span>
                <span className={clsx("tnum", j.direccion === "arriba" ? "text-good" : "text-critical")}>{j.real} <span className="text-xs text-mute">(proy. {j.proyeccion?.toFixed(0)})</span></span>
              </li>
            )) : <li className="text-mute">Nadie: todos quedaron dentro de su rango.</li>}
          </ul>
        </div>
      </div>

      <div className="card flex flex-wrap gap-x-8 gap-y-2 p-4 text-sm">
        <span className="text-ink2">Picks con nivel: <Rec r={a.picks.todos_con_nivel} /></span>
        <span className="text-ink2">Élite: <Rec r={a.picks.elite} /></span>
        <span className="text-ink2">Súper élite: <Rec r={a.picks.super_elite} /></span>
      </div>
    </div>
  );
}

export function LiveSeasonSection({ r, items }: { r?: LiveSeason | null; items: Autopsia[] }) {
  if (!r || !r.partidos) return null;
  const t = r.tipos_de_resultado ?? {};
  return (
    <section className="space-y-4">
      <SectionTitle right={<span className="text-xs text-mute">{r.partidos} partidos revisados</span>}>Temporada en vivo (se aprende de cada partido)</SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="card p-4"><div className="text-[11px] uppercase tracking-wider text-mute">Ganador acertado</div>
          <div className="text-2xl font-bold tnum">{pct(r.ganador_acertado ?? 0, 0)}</div>
          <div className="text-xs text-mute">error medio del margen {r.error_medio_margen} pts</div></div>
        <div className="card p-4"><div className="text-[11px] uppercase tracking-wider text-mute">Cinna vs casas (log-loss)</div>
          <div className="text-2xl font-bold tnum">{r.logloss_cerebro?.toFixed(3) ?? "—"}</div>
          <div className="text-xs text-mute">casas {r.logloss_mercado?.toFixed(3) ?? "—"} · menor es mejor</div></div>
        <div className="card p-4"><div className="text-[11px] uppercase tracking-wider text-mute">Élite en vivo</div>
          <div className="text-lg"><Rec r={r.elite_en_vivo} /></div>
          <div className="text-xs text-mute">Súper élite: <Rec r={r.super_elite_en_vivo} /></div></div>
        <div className="card p-4"><div className="text-[11px] uppercase tracking-wider text-mute">Por qué acertó o falló</div>
          <ul className="mt-1 space-y-0.5 text-xs">
            {Object.entries(VERDICT).map(([k, v]) => (
              <li key={k} className="flex justify-between"><span className={v.cls}>{v.label}</span><b className="tnum text-ink">{t[k] ?? 0}</b></li>
            ))}
          </ul></div>
      </div>
      <div className="card divide-y divide-[var(--border)]">
        {items.slice(0, 12).map((a) => {
          const v = VERDICT[a.veredicto.tipo] ?? VERDICT.modelo;
          const Icon = v.icon;
          const [A, H] = a.partido.split(" @ ");
          return (
            <a key={a.game_id} href={`/partido/${a.game_id}`} className="flex flex-wrap items-center gap-3 px-4 py-2.5 hover:bg-s2">
              <Icon size={15} className={v.cls} />
              <span className="w-36 text-sm font-semibold tnum">{A} {a.marcador[A]} – {H} {a.marcador[H]}</span>
              <span className="min-w-0 flex-1 truncate text-xs text-ink2">{a.veredicto.texto}</span>
            </a>
          );
        })}
      </div>
      <p className="flex items-center gap-1.5 text-[11px] text-mute"><Search size={12} /> {r.nota}</p>
    </section>
  );
}

export function PublicOpinion({ pub, home, away }: { pub?: { equipos: Record<string, number>; n: number } | null; home: string; away: string }) {
  if (!pub?.equipos) return null;
  const ph = pub.equipos[home], pa = pub.equipos[away];
  if (ph == null || pa == null) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink2" title="Quiniela gratuita de ESPN. Probado en 591 partidos: el público no le gana a las casas; es sólo contexto.">
      <Users size={12} className="text-mute" /> La gente: {away} {pct(pa, 0)} · {home} {pct(ph, 0)}
      <span className="text-mute">({(pub.n / 1000).toFixed(0)} mil picks)</span>
    </span>
  );
}

export type Categoria = { stat: string; side: string; n: number; hit: number | null; post: number; degradada: boolean;
  en_vivo?: { w: number; n: number } | null };
const STAT_LABEL: Record<string, string> = {
  pass_yds: "Yds de pase", pass_att: "Intentos de pase", pass_cmp: "Pases completos", pass_tds: "TD de pase", pass_ints: "Intercepciones",
  rush_yds: "Yds por tierra", rush_att: "Acarreos", rec_yds: "Yds de recepción", receptions: "Recepciones", targets: "Targets",
  rush_rec_yds: "Yds tierra + recepción", pass_rush_yds: "Yds pase + tierra", qb_rush_yds: "QB yds por tierra", qb_rush_att: "QB acarreos",
};

export function CategoriesSection({ rows, umbral }: { rows: Categoria[]; umbral: number }) {
  if (!rows.length) return null;
  return (
    <section className="space-y-3">
      <SectionTitle right={<span className="text-xs text-mute">se actualiza cada semana + con cada pick calificado</span>}>
        Élite por categoría (retroalimentación)
      </SectionTitle>
      <p className="text-xs text-mute">Récord de los picks Élite por tipo (backtest de la temporada de prueba y la actual + picks en vivo). Si una categoría
        baja de {Math.round(umbral * 1000) / 10}% con suficiente muestra, Cinna deja de etiquetarla como Élite hasta que se recupere.</p>
      <div className="card overflow-x-auto p-3">
        <table className="w-full min-w-[480px] text-sm">
          <thead><tr className="text-left text-[11px] uppercase tracking-wider text-mute">
            <th className="pb-1.5 font-medium">Categoría</th><th className="pb-1.5 text-right font-medium">Picks</th>
            <th className="pb-1.5 text-right font-medium">Acierto</th><th className="pb-1.5 text-right font-medium">Estimado</th>
            <th className="pb-1.5 text-right font-medium">Estado</th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.stat + c.side} className="border-t border-line">
                <td className="py-1.5 text-ink2">{STAT_LABEL[c.stat] ?? c.stat} · <b className="text-ink">{c.side === "over" ? "Más" : "Menos"}</b></td>
                <td className="py-1.5 text-right tnum text-mute">{c.n}</td>
                <td className="py-1.5 text-right tnum">{c.hit != null ? pct(c.hit, 1) : "—"}</td>
                <td className={clsx("py-1.5 text-right font-semibold tnum", c.post >= 0.58 ? "text-good" : c.post < umbral ? "text-critical" : "")}>{pct(c.post, 1)}</td>
                <td className="py-1.5 text-right text-xs">{c.degradada ? <span className="text-critical">en observación</span> : <span className="text-good">activa</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
