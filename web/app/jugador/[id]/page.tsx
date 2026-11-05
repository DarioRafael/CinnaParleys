"use client";

import clsx from "clsx";
import { ArrowDownRight, ArrowLeft, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Pick, Reason, Team, american, kickoffLabel, num, pct, useApi } from "@/lib/api";
import { LogBars, RangeStrip } from "@/components/charts";
import { NewsItem, NewsList } from "@/components/news-list";
import { PlayerVideos } from "@/components/jugadas";
import { PickCard } from "@/components/pick-card";
import { Calc } from "@/components/calc";
import { Empty, Headshot, Loading, SectionTitle, Segmented, TeamLogo, TierBadge } from "@/components/ui";

type Line = { line: number; open?: number | null; kind: string; p_over: number; side: string; p_side: number; edge?: number | null;
  tier: string | null; confidence: number; p_model?: number | null; p_market?: number | null; book?: string | null; odds?: number | null; ev?: number | null };
type StatEntry = { mu: number; med?: number; med_model?: number; mu_model: number; market_line: number | null; q: number[]; label: string; unit: string; lines: Line[];
  why: { up: Reason[]; down: Reason[] }; p_any?: number; p_two?: number };
type LogRow = Record<string, number | string | null>;
type PlayerResp = {
  player_id: string; name: string; team: string; opp: string; position: string; headshot?: string; game_id: string; kickoff: string;
  is_home: boolean; availability: { p_play: number; status: string; comment?: string; source?: string };
  role: Record<string, number | null | boolean>; context: Record<string, number | boolean | null>;
  experts?: { ecr: number; sd: number; pos_rank: string; our_rank: string; lean: number } | null;
  stats: Record<string, StatEntry>; log: LogRow[]; picks: Pick[]; news: NewsItem[];
  injury: { data: { history: { src: string; text: string; at?: string; applied?: boolean }[] } } | null;
  team_info?: Team; opp_info?: Team;
};

const ORDER = ["pass_yds", "pass_att", "pass_cmp", "pass_tds", "pass_ints", "pass_rush_yds", "qb_rush_yds", "qb_rush_att",
  "rec_yds", "receptions", "targets", "rush_yds", "rush_att", "rush_rec_yds", "tds"];
const LOG_KEY: Record<string, (r: LogRow) => number | null> = {
  pass_yds: (r) => r.pass_yds as number, pass_att: (r) => r.att as number, pass_cmp: (r) => r.cmp as number,
  pass_tds: (r) => r.pass_tds as number, pass_ints: (r) => r.ints as number,
  pass_rush_yds: (r) => ((r.pass_yds as number) ?? 0) + ((r.rush_yds as number) ?? 0),
  qb_rush_yds: (r) => r.rush_yds as number, qb_rush_att: (r) => r.carries as number,
  rec_yds: (r) => r.rec_yds as number, receptions: (r) => r.rec as number, targets: (r) => r.targets as number,
  rush_yds: (r) => r.rush_yds as number, rush_att: (r) => r.carries as number,
  rush_rec_yds: (r) => ((r.rush_yds as number) ?? 0) + ((r.rec_yds as number) ?? 0),
  tds: (r) => ((r.rush_tds as number) ?? 0) + ((r.rec_tds as number) ?? 0),
};

export default function PlayerPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error } = useApi<PlayerResp>(`/api/player/${id}`);
  // sólo estadísticas relevantes para su rol (o con línea en DraftKings)
  const stats = useMemo(() => ORDER.filter((s) => {
    const e = data?.stats[s];
    return e && (e.lines.length > 0 || s === "tds" || (e.med ?? e.mu) >= 1.5);
  }), [data]);
  const [stat, setStat] = useState<string | null>(null);
  useEffect(() => {
    if (!data || stat) return;
    // arranca en la stat con línea en DraftKings o la principal de su posición
    const withLine = stats.find((s) => data.stats[s].lines.some((l) => l.kind === "ou"));
    setStat(withLine ?? stats[0]);
  }, [data, stats, stat]);

  if (isLoading && !data) return <Loading />;
  if (error || !data) return <Empty>Este jugador no tiene proyección esta semana (puede estar fuera o sin rol).</Empty>;
  const s = stat ? data.stats[stat] : null;
  const av = data.availability;

  return (
    <div className="space-y-6">
      <Link href={`/partido/${data.game_id}`} className="inline-flex items-center gap-1 text-sm text-ink2 hover:text-ink">
        <ArrowLeft size={15} /> Partido
      </Link>

      <div className="card flex flex-wrap items-center gap-5 p-5">
        <Headshot src={data.headshot} name={data.name} size={88} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs text-mute">
            <TeamLogo team={data.team_info} size={18} /> {data.team_info?.name} · {data.position}
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">{data.name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink2">
            {data.is_home ? "vs" : "@"} <TeamLogo team={data.opp_info} size={18} /> {data.opp_info?.name} · {kickoffLabel(data.kickoff)}
          </div>
        </div>
        <div className={clsx("rounded-xl px-4 py-3 text-right", av.p_play >= 0.97 ? "bg-good-soft" : av.p_play >= 0.5 ? "bg-serious-soft" : "bg-critical/15")}>
          <div className={clsx("text-sm font-semibold", av.p_play >= 0.97 ? "text-good" : av.p_play >= 0.5 ? "text-serious" : "text-critical")}>{av.status}</div>
          <div className="text-xs text-ink2">{pct(av.p_play)} de jugar{av.source ? ` · ${av.source}` : ""}</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <RoleTile label="Snaps (recientes)" v={pct(data.role.snap_pct as number)} sub={`último tramo ${pct(data.role.snap_recent as number)}`} />
        {data.position !== "QB" && <RoleTile label="Cuota de targets" v={pct(data.role.tgt_share as number)} sub={`proyectada ${pct(data.role.tgt_share_proj as number)}`} />}
        {data.position !== "QB" && <RoleTile label="Cuota de acarreos" v={pct(data.role.car_share as number)} sub={`proyectada ${pct(data.role.car_share_proj as number)}`} />}
        {data.position !== "QB" && <RoleTile label="Zona roja" v={pct(Math.max((data.role.rz_tgt_share as number) ?? 0, (data.role.rz_car_share as number) ?? 0))} sub="de las oportunidades" />}
        <RoleTile label="Su equipo proyecta" v={`${num(data.context.implied_pts as number, 1)} pts`}
          sub={data.context.spread != null ? `${(data.context.spread as number) > 0 ? "favorito" : "underdog"} por ${Math.abs(data.context.spread as number)}` : ""} />
      </div>

      <div className="overflow-x-auto">
        <Segmented value={stat ?? ""} onChange={setStat} options={stats.map((k) => ({
          value: k, label: data.stats[k].label,
        }))} />
      </div>

      {s && stat && (
        <div className="grid gap-6 xl:grid-cols-[1.3fr_1fr]">
          <div className="space-y-6">
            <div className="card p-5">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <div className="text-xs text-mute">Proyección de Cinna</div>
                  <div className="text-4xl font-bold tracking-tight tnum">{stat === "tds" ? pct(s.p_any) : num(s.med ?? s.mu, 1)} <span className="text-lg font-medium text-mute">{stat === "tds" ? "de anotar" : s.unit}</span></div>
                  {stat !== "tds" && <div className="text-xs text-ink2">80% de las veces entre {num(s.q[0], 0)} y {num(s.q[4], 0)} · promedio {num(s.mu, 1)}</div>}
                  {stat === "tds" && s.p_two != null && <div className="text-xs text-ink2">2 o más TDs: {pct(s.p_two, 1)}</div>}
                </div>
                {s.market_line != null && (
                  <div className="text-right text-xs">
                    <div className="text-mute">Modelo puro {num(s.med_model ?? s.mu_model, 1)}</div>
                    <div className="text-mute">Línea de consenso (8 casas) <b className="text-ink">{s.market_line}</b></div>
                  </div>
                )}
              </div>
              {stat !== "tds" && (
                <div className="mt-4">
                  <RangeStrip q={s.q} mu={s.med ?? s.q[2]} unit={s.unit}
                    lines={s.market_line != null ? [{ value: s.market_line, label: `línea ${s.market_line}`, strong: true }] : []} />
                </div>
              )}
            </div>

            <div className="card p-5">
              <SectionTitle right={<span className="text-xs text-mute">últimos {Math.min(10, data.log.length)} partidos</span>}>Historial vs la línea</SectionTitle>
              <LogBars unit={s.unit} line={s.market_line ?? (stat === "tds" ? 0.5 : null)}
                items={data.log.slice(-10).map((r) => ({ label: `S${r.week}`, sub: String(r.opp ?? ""), value: LOG_KEY[stat]?.(r) ?? null }))} />
            </div>

            {s.lines.length > 0 && (
              <div className="card overflow-x-auto">
                <div className="border-b border-line px-5 py-3 text-sm font-semibold">Mercado (8 casas) vs Cinna</div>
                <table className="w-full min-w-[560px] text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-mute">
                      <th className="px-5 py-2 font-medium">Apuesta</th>
                      <th className="px-3 py-2 text-right font-medium">Cinna</th>
                      <th className="px-3 py-2 text-right font-medium">Mercado</th>
                      <th className="px-3 py-2 text-right font-medium">Mejor precio</th>
                      <th className="px-3 py-2 text-right font-medium">VE</th>
                      <th className="px-3 py-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.lines.map((l, i) => (
                      <tr key={i} className="border-b border-line last:border-0">
                        <td className="px-5 py-2">
                          {l.kind === "ou" ? `${l.side === "over" ? "Más" : "Menos"} de ${l.line}` : l.kind === "alt" ? `${l.line + 0.5}+` : l.kind === "td2" ? "2+ TDs" : "Anota TD"}
                          {l.open != null && l.open !== l.line && <span className="text-xs text-mute"> · abrió {l.open}</span>}
                        </td>
                        <td className="px-3 py-2 text-right font-semibold tnum">{pct(l.p_side)}</td>
                        <td className="px-3 py-2 text-right text-ink2 tnum">{l.p_market != null ? pct(l.p_market) : "—"}</td>
                        <td className="px-3 py-2 text-right text-ink2 tnum">{l.book ? `${l.book} ${american(l.odds ?? null)}` : "—"}</td>
                        <td className={clsx("px-3 py-2 text-right tnum", (l.ev ?? 0) > 0.02 ? "font-semibold text-good" : "text-mute")}>
                          {l.ev != null ? `${l.ev > 0 ? "+" : ""}${(l.ev * 100).toFixed(1)}%` : "—"}
                        </td>
                        <td className="px-3 py-2"><TierBadge tier={l.tier} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="space-y-6">
            <Calc playerId={data.player_id} gameId={data.game_id} stat={stat} unit={s.unit} mu={s.med ?? s.mu} />
            {data.experts && (
              <div className="card p-5">
                <SectionTitle>Consenso de expertos</SectionTitle>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-xl bg-s2 px-3 py-2.5">
                    <div className="text-xs text-mute">FantasyPros (decenas de analistas)</div>
                    <div className="text-2xl font-semibold">{data.experts.pos_rank}</div>
                    <div className="text-[11px] text-mute tnum">consenso {data.experts.ecr?.toFixed(1)} · ±{data.experts.sd?.toFixed(1)}</div>
                  </div>
                  <div className="rounded-xl bg-s2 px-3 py-2.5">
                    <div className="text-xs text-mute">Cinna</div>
                    <div className="text-2xl font-semibold">{data.experts.our_rank}</div>
                    <div className="text-[11px] text-mute">según su proyección</div>
                  </div>
                </div>
                <div className="mt-3 text-sm text-ink2">
                  {data.experts.lean > 0 ? "Los expertos son más optimistas que Cinna con este jugador."
                    : data.experts.lean < 0 ? "Los expertos son más pesimistas que Cinna con este jugador."
                      : "Los expertos y Cinna lo ven parecido."}
                </div>
              </div>
            )}
            <div className="card p-5">
              <SectionTitle>Qué mueve su proyección</SectionTitle>
              {s.why.up.length === 0 && s.why.down.length === 0 && <div className="text-sm text-mute">Proyección cercana al promedio de su perfil.</div>}
              {s.why.up.map((x, i) => (
                <div key={`u${i}`} className="flex gap-2 py-1 text-sm text-ink2"><ArrowUpRight size={16} className="mt-0.5 shrink-0 text-good" />{x.text}</div>
              ))}
              {s.why.down.map((x, i) => (
                <div key={`d${i}`} className="flex gap-2 py-1 text-sm text-ink2"><ArrowDownRight size={16} className="mt-0.5 shrink-0 text-critical" />{x.text}</div>
              ))}
            </div>
            {data.injury?.data.history && data.injury.data.history.length > 0 && (
              <div className="card p-5">
                <SectionTitle>Reportes de estado</SectionTitle>
                {data.injury.data.history.slice().reverse().map((h, i) => (
                  <div key={i} className={clsx("border-b border-line py-2 text-xs last:border-0", h.applied === false ? "text-mute" : "text-ink2")}>
                    <span className="font-semibold">{h.src}</span>: {h.text}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {data.picks.length > 0 && (
        <section>
          <SectionTitle>Picks de {data.name}</SectionTitle>
          <div className="grid gap-4 lg:grid-cols-2">{data.picks.map((p) => <PickCard key={p.pick_id} p={p} />)}</div>
        </section>
      )}
      <PlayerVideos playerId={data.player_id} name={data.name} />
      <section>
        <SectionTitle>Noticias</SectionTitle>
        <NewsList items={data.news} showEvents />
      </section>
    </div>
  );
}

function RoleTile({ label, v, sub }: { label: string; v: string; sub?: string }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-xs text-mute">{label}</div>
      <div className="mt-0.5 text-xl font-semibold tnum">{v}</div>
      {sub && <div className="text-[11px] text-ink2">{sub}</div>}
    </div>
  );
}
