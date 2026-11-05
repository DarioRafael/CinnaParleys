"use client";

import { Calculator } from "@phosphor-icons/react";
import clsx from "clsx";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { GameCard, american, pct, post, useApi } from "@/lib/api";
import { Calc } from "@/components/calc";
import { Headshot, SectionTitle, Segmented, TeamLogo, PageHeader } from "@/components/ui";

type P = { player_id: string; name: string; team: string; position: string };
type Proj = { player_id: string; game_id: string; name: string; headshot?: string; stats: Record<string, { mu: number; med?: number; label: string; unit: string }> };

export default function CalcPage() {
  const [mode, setMode] = useState<"jugador" | "partido">("jugador");
  return (
    <div className="space-y-5">
      <PageHeader duo={Calculator} tone="cielo" kicker="a jugar" title="Calculadora">
        <p>Escribe la línea que te da Draftea y Cinna te dice la probabilidad real y el momio justo.</p>
      </PageHeader>
      <Segmented value={mode} onChange={setMode} options={[{ value: "jugador", label: "Jugador" }, { value: "partido", label: "Partido" }]} />
      {mode === "jugador" ? <PlayerCalc /> : <GameCalc />}
    </div>
  );
}

function PlayerCalc() {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<P | null>(null);
  const [stat, setStat] = useState<string | null>(null);
  const { data: found } = useApi<{ players: P[] }>(q.length >= 2 ? `/api/search?q=${encodeURIComponent(q)}` : null);
  const { data: proj } = useApi<Proj>(sel ? `/api/player/${sel.player_id}` : null);
  const stats = useMemo(() => Object.entries(proj?.stats ?? {}).filter(([k]) => k !== "tds"), [proj]);
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
      <div className="card p-5">
        <SectionTitle>1. Elige al jugador</SectionTitle>
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-mute" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nombre del jugador…"
            className="w-full rounded-lg border border-line bg-s2 py-2 pl-9 pr-3 text-sm outline-none focus:border-accent" />
        </div>
        <div className="mt-2 max-h-80 overflow-y-auto">
          {(found?.players ?? []).map((p) => (
            <button key={p.player_id} onClick={() => { setSel(p); setStat(null); }}
              className={clsx("flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm hover:bg-s2", sel?.player_id === p.player_id && "bg-s2")}>
              <span>{p.name}</span><span className="text-xs text-mute">{p.position} · {p.team}</span>
            </button>
          ))}
        </div>
        {proj && (
          <div className="mt-4 border-t border-line pt-4">
            <div className="mb-3 flex items-center gap-3"><Headshot src={proj.headshot} name={proj.name} size={36} /><div className="font-semibold">{proj.name}</div></div>
            <SectionTitle>2. Elige la estadística</SectionTitle>
            <div className="flex flex-wrap gap-2">
              {stats.map(([k, v]) => (
                <button key={k} onClick={() => setStat(k)}
                  className={clsx("rounded-lg border px-3 py-1.5 text-sm", stat === k ? "border-accent bg-accent-soft text-accent" : "border-line text-ink2 hover:text-ink")}>
                  {v.label} <span className="text-mute tnum">({(v.med ?? v.mu).toFixed(1)})</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <div>
        {proj && stat ? (
          <Calc playerId={proj.player_id} gameId={proj.game_id} stat={stat} unit={proj.stats[stat].unit} mu={proj.stats[stat].med ?? proj.stats[stat].mu} />
        ) : (
          <div className="card grid h-full min-h-48 place-items-center p-6 text-center text-sm text-mute">Elige un jugador y una estadística.</div>
        )}
      </div>
    </div>
  );
}

type CalcRes = { p_over: number; p_under: number; side: string; fair_over: number; fair_under: number; verdict: string; mu: number };

function GameCalc() {
  const { data } = useApi<{ games: GameCard[] }>("/api/week");
  const games = (data?.games ?? []).filter((g) => g.status !== "post" && g.pred);
  const [gid, setGid] = useState<string | null>(null);
  const [market, setMarket] = useState<"total" | "margin_home">("total");
  const [line, setLine] = useState("");
  const [res, setRes] = useState<CalcRes | null>(null);
  const g = games.find((x) => x.game_id === gid);
  const run = () => {
    const v = parseFloat(line);
    if (!gid || isNaN(v)) return;
    post<CalcRes>("/api/calc", { game_id: gid, stat: market, line: v }).then(setRes);
  };
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
      <div className="card p-5">
        <SectionTitle>Partido</SectionTitle>
        <div className="space-y-1">
          {games.map((x) => (
            <button key={x.game_id} onClick={() => { setGid(x.game_id); setRes(null); }}
              className={clsx("flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-s2", gid === x.game_id && "bg-s2")}>
              <TeamLogo team={x.away} size={20} /> {x.away.abbr} @ {x.home.abbr} <TeamLogo team={x.home} size={20} />
            </button>
          ))}
        </div>
      </div>
      <div className="card p-5">
        {g ? (
          <>
            <Segmented value={market} onChange={(v) => { setMarket(v); setRes(null); }} options={[
              { value: "total", label: "Total de puntos" }, { value: "margin_home", label: `Hándicap ${g.home.abbr}` },
            ]} />
            <div className="mt-4 flex gap-2">
              <input value={line} onChange={(e) => setLine(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()}
                placeholder={market === "total" ? `${g.market.total ?? 44.5}` : `${g.home.abbr} ${g.market.spread_home != null ? -g.market.spread_home : -2.5}`}
                className="w-full rounded-lg border border-line bg-s2 px-3 py-2 text-sm outline-none focus:border-accent tnum" />
              <button onClick={run} className="rounded-lg bg-accent px-4 text-sm font-semibold text-on-accent">Calcular</button>
            </div>
            <div className="mt-1 text-xs text-mute">{market === "margin_home" ? `Hándicap del local: -3.5 = ${g.home.abbr} debe ganar por 4+; +3.5 = recibe 3.5 pts.` : "Total de ambos equipos, incluye tiempo extra."}</div>
            {res && (
              <div className="mt-4 grid grid-cols-2 gap-2">
                {(["over", "under"] as const).map((side) => (
                  <div key={side} className={clsx("rounded-xl border px-3 py-2.5", res.side === side ? "border-accent bg-accent-soft" : "border-line")}>
                    <div className="text-xs text-ink2">{market === "total" ? (side === "over" ? `Más de ${line}` : `Menos de ${line}`)
                      : side === "over" ? `${g.home.abbr} ${line}` : `${g.away.abbr} ${-parseFloat(line) > 0 ? "+" : ""}${-parseFloat(line)}`}</div>
                    <div className="text-2xl font-bold tnum">{pct(side === "over" ? res.p_over : res.p_under, 1)}</div>
                    <div className="text-[11px] text-mute">momio justo {american(side === "over" ? res.fair_over : res.fair_under)}</div>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : <div className="grid min-h-48 place-items-center text-sm text-mute">Elige un partido.</div>}
      </div>
    </div>
  );
}
