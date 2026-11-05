"use client";

import clsx from "clsx";
import { Layers, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { kickoffLabel, pct, useApi } from "@/lib/api";
import { Headshot, Loading, SectionTitle } from "./ui";

type Paso = { x: number; p: number; odds: number | null; dec: number | null; p_casa: number | null; valor: boolean; p_kalshi?: number | null; p_cerebro?: number };
type StatLadder = {
  stat: string; label: string; proyeccion: number | null; linea_mm?: number | null; playdoit?: number | null;
  fuente?: string; pasos?: Paso[]; prob_anota?: number; prob_2?: number; kalshi_anota?: number | null;
};
type Jug = { player_id: string; jugador: string; equipo: string; pos: string; headshot?: string | null; stats: StatLadder[] };
type GameL = { game_id: string; partido: string; kickoff: string; jugadores: Jug[] };
type Leg = { tipo: string; title: string; prob: number; dec: number; nivel?: string; proyeccion?: number | null; linea_mm?: number | null };
type DParlay = {
  modo: string; label: string; desc: string; error?: string; patas?: Leg[]; prob_conjunta?: number;
  prob_si_fueran_independientes?: number; pago_estimado?: number; sale_de_cada_10?: number; nota?: string;
};


export function GamePicker({ games, value, onChange, allLabel }: { games: { game_id: string; partido: string; kickoff: string }[];
  value: string; onChange: (v: string) => void; allLabel?: string }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      className="h-9 max-w-full rounded-lg border border-line bg-s1 px-2 text-sm text-ink outline-none focus:border-accent">
      {allLabel && <option value="">{allLabel}</option>}
      {games.map((g) => <option key={g.game_id} value={g.game_id}>{g.partido} · {kickoffLabel(g.kickoff)}</option>)}
    </select>
  );
}

export function DrafteaParlays({ games }: { games: { game_id: string; partido: string; kickoff: string }[] }) {
  const [gid, setGid] = useState("");
  const { data, isLoading } = useApi<{ parlays: DParlay[] }>(`/api/draftea/parlays${gid ? `?games=${gid}` : ""}`, { revalidateOnFocus: false });
  return (
    <section>
      <SectionTitle right={<GamePicker games={games} value={gid} onChange={setGid} allLabel="Toda la jornada" />}>
        <span className="inline-flex items-center gap-1.5"><Layers size={14} />Parlays con la regla de Draftea</span>
      </SectionTitle>
      <p className="mb-3 text-xs text-mute">Máximo <b className="text-ink2">una Más/Menos de jugador por partido</b> (la mejor Élite); lo demás son
        escalones <b className="text-ink2">X+</b>. La probabilidad sale de la simulación conjunta: si dos patas se ayudan, ya está contado.</p>
      {isLoading || !data ? <Loading label="Armando parlays…" /> : (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
          {data.parlays.map((p) => (
            <div key={p.modo} className="card flex flex-col p-4">
              <div className="flex items-baseline justify-between gap-2">
                <div className="text-base font-semibold">{p.label}</div>
                {p.pago_estimado != null && <div className="text-sm font-semibold tnum text-ink2">~{p.pago_estimado.toFixed(2)}x</div>}
              </div>
              <div className="text-xs text-mute">{p.desc}</div>
              {p.error ? <div className="mt-3 text-sm text-mute">{p.error}</div> : (
                <>
                  <ul className="mt-3 flex-1 space-y-2">
                    {p.patas!.map((l) => (
                      <li key={l.title} className="flex items-start justify-between gap-3 text-sm">
                        <div className="min-w-0">
                          <span className={clsx("mr-1.5 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                            l.tipo === "Más/Menos" ? "bg-accent/15 text-accent" : "bg-s3 text-ink2")}>{l.tipo === "Más/Menos" ? "M/M" : "X+"}</span>
                          <span className="text-ink">{l.title}</span>
                          {l.nivel && <span className="ml-1 text-[11px] text-good">{l.nivel}</span>}
                        </div>
                        <span className="shrink-0 font-semibold tnum">{pct(l.prob, 0)}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3 flex items-end justify-between border-t border-line pt-3">
                    <div>
                      <div className={clsx("text-2xl font-bold tnum", (p.prob_conjunta ?? 0) >= 0.5 ? "text-good" : "")}>{pct(p.prob_conjunta, 0)}</div>
                      <div className="text-[11px] text-mute">sale completo (~{p.sale_de_cada_10} de cada 10)</div>
                    </div>
                    <div className="text-right text-[11px] text-mute">si fueran independientes<br />{pct(p.prob_si_fueran_independientes, 0)}</div>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      <p className="mt-2 text-[11px] text-mute">Si Draftea no tiene el escalón exacto, usa el inmediato <b>inferior</b> (más seguro). El pago es un estimado con
        precios típicos de escalones; verifica el momio real en Draftea.</p>
    </section>
  );
}

export function EscalonesPanel({ games }: { games: { game_id: string; partido: string; kickoff: string }[] }) {
  const [gid, setGid] = useState("");
  const g0 = gid || games[0]?.game_id || "";
  const { data, isLoading } = useApi<{ partidos: GameL[] }>(g0 ? `/api/draftea/escalones?game_id=${g0}` : null, { revalidateOnFocus: false });
  const game = data?.partidos?.[0];
  const teams = useMemo(() => Array.from(new Set((game?.jugadores ?? []).map((j) => j.equipo))), [game]);
  return (
    <section>
      <SectionTitle right={<GamePicker games={games} value={g0} onChange={setGid} />}>
        <span className="inline-flex items-center gap-1.5"><ShieldCheck size={14} />Escalones X+ de la casa</span>
      </SectionTitle>
      <p className="mb-3 text-xs text-mute">
        Los escalones <b className="text-ink2">tal como los publica Playdoit</b> (los mismos de Draftea: p. ej. Judkins desde 36+) con la probabilidad
        de Cinna en cada uno. Si dice <i>estimado</i>, la casa todavía no los publica (suele ser 1–2 días antes) y se calculan con su patrón.
        <b className="text-good"> Verde</b> = 85% o más. <b className="text-good">✓</b> = Cinna le da más probabilidad de la que cobra la casa.
        <b className="text-ink2"> K</b> = lo que paga el mercado de Kalshi por ese mismo escalón (dinero real; segunda opinión). <span className="text-warning">K en naranja</span> = Kalshi le da 3+ puntos menos que Cinna: esos escalones han acertado menos.
      </p>
      {isLoading || !game ? <Loading /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          {teams.map((t) => (
            <div key={t} className="card p-3">
              <div className="mb-2 text-sm font-semibold">{t}</div>
              <div className="space-y-3">
                {game.jugadores.filter((j) => j.equipo === t).map((j) => (
                  <div key={j.player_id}>
                    <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-ink">
                      <Headshot src={j.headshot} name={j.jugador} size={22} />{j.jugador} <span className="text-xs font-normal text-mute">{j.pos}</span>
                    </div>
                    {j.stats.map((s) => (
                      <div key={s.stat} className="mb-1.5 ml-7">
                        <div className="text-xs text-ink2">
                          {s.label}
                          {s.stat !== "tds" && <span className={clsx("ml-1.5 rounded px-1 py-px text-[10px]", s.fuente === "Playdoit" ? "bg-accent/15 text-accent" : "bg-s3 text-mute")}>{s.fuente === "Playdoit" ? "Playdoit" : "estimado"}</span>}
                          {s.proyeccion != null && <span className="ml-1.5 text-[11px] text-mute">proy. {s.proyeccion}{s.linea_mm != null ? ` · línea ${s.linea_mm}` : ""}</span>}
                        </div>
                        {s.stat === "tds" ? (
                          <div className="mt-0.5 text-sm tnum text-ink2">Anota TD {pct(s.prob_anota, 0)}{s.kalshi_anota != null && <span className="ml-1 text-[10px] text-mute">K {pct(s.kalshi_anota, 0)}</span>} <span className="text-[11px] text-mute">· 2+ TDs {pct(s.prob_2, 0)}</span></div>
                        ) : (
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            {(s.pasos ?? []).map((p) => (
                              <span key={p.x} title={(p.odds != null ? `Playdoit ${p.odds > 0 ? "+" : ""}${p.odds} (la casa le da ${pct(p.p_casa, 0)})` : "estimado") + (p.p_kalshi != null ? ` · Kalshi ${pct(p.p_kalshi, 0)}` : "")}
                                className={clsx("rounded-md border px-2 py-0.5 text-xs tnum",
                                  p.p >= 0.85 ? "border-[var(--good)]/40 bg-[var(--good)]/10 text-good" : p.p >= 0.7 ? "border-line text-ink" : "border-line text-mute")}>
                                <b>{p.x}+</b> {pct(p.p, 0)}{p.odds != null && <span className="ml-1 text-[10px] opacity-70">{p.odds > 0 ? "+" : ""}{p.odds}</span>}{p.valor && <span className="ml-0.5">✓</span>}{p.p_kalshi != null && <span className={clsx("ml-1 text-[10px]", p.p_kalshi < (p.p_cerebro ?? p.p) - 0.03 ? "text-warning" : "text-mute")}>K {pct(p.p_kalshi, 0)}</span>}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
