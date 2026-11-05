"use client";

import clsx from "clsx";
import { ArrowLeft, Check, CloudSun, MapPin, MessageSquareText, Tv } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { GameCard, GamePred, Pick, american, ago, kickoffLabel, num, pct, useApi } from "@/lib/api";
import { PmfChart, ProbLine } from "@/components/charts";
import { NewsList } from "@/components/news-list";
import { PickCard } from "@/components/pick-card";
import { Escenarios, Esquema, ScenariosPanel } from "@/components/scenarios";
import { Autopsia, PublicOpinion, ReviewPanel } from "@/components/review";
import { InformePanel } from "@/components/informe";
import { JugadasPanel } from "@/components/jugadas";
import { Caminos, LivePanel, LiveState } from "@/components/live";
import { Empty, Headshot, Loading, Meter, SectionTitle, Segmented, StatusPill, TeamLogo, WinBar } from "@/components/ui";

type Rank = { value: number | null; rank: number };
type Ranks = Record<string, Rank> & { qb_id?: string };
type PlayerProj = {
  player_id: string; name: string; team: string; opp: string; position: string; headshot?: string;
  availability: { p_play: number; status: string };
  role: Record<string, number | null | boolean>;
  stats: Record<string, { mu: number; med?: number; q: number[]; label: string; unit: string; market_line?: number | null;
    lines: { line: number; kind: string; p_over: number; side: string; p_side: number; tier: string | null }[]; p_any?: number }>;
};
type BookLine = { spread_home?: number | null; spread_home_odds?: number | null; spread_away_odds?: number | null;
  total?: number | null; over_odds?: number | null; under_odds?: number | null; ml_home?: number | null; ml_away?: number | null };
type GameResp = GameCard & {
  books?: Record<string, BookLine> | null;
  pred_full: GamePred & { margin_pmf: { min: number; p: number[] }; total_pmf: { min: number; p: number[] };
    inputs: Record<string, number | null>; win_margin: { home: { range: string; p: number }[]; away: { range: string; p: number }[] };
    escenarios?: Escenarios; esquema?: Esquema; incertidumbre?: { nivel: string; razones: string[] };
    caminos?: Record<string, { situacion: string; prob_de_estar: number; gana_desde_ahi: number }[]> | null };
  en_vivo?: LiveState | null;
  autopsia?: Autopsia | null; publico?: { equipos: Record<string, number>; n: number } | null;
  ranks: { home: Ranks | null; away: Ranks | null };
  players: PlayerProj[]; picks: Pick[];
  injuries: { player_id: string; name: string; team: string; position: string; status: string; p_play: number; source: string; comment: string;
    data: { history: { src: string; text: string; at?: string; tier?: number; applied?: boolean }[] } }[];
  news: { news_id: string; source: string; tier: number; tier_label: string; published_at: string; title: string; url: string }[];
  history: { run_at: string; data: { p_home: number } }[];
};

const MATCHUPS: [string, string, string][] = [
  ["Juego aéreo", "off_pass", "def_pass"],
  ["Juego terrestre", "off_rush", "def_rush"],
  ["Puntos por serie", "off_ppd", "def_ppd"],
  ["Jugadas explosivas", "expl_off", "expl_def"],
  ["Protección vs presión", "sack_off", "sack_def"],
  ["Zona roja", "rz_off", "rz_def"],
];

export default function GamePage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, mutate: reload } = useApi<GameResp>(`/api/game/${id}`);
  // en vivo: actualiza marcador y probabilidades cada minuto
  useEffect(() => {
    if (data?.status !== "in") return;
    const t = setInterval(() => { fetch("/api/live").finally(() => reload()); }, 60000);
    return () => clearInterval(t);
  }, [data?.status, reload]);
  const [tab, setTab] = useState<"resumen" | "informe" | "revision" | "escenarios" | "jugadores" | "picks" | "lesiones" | "noticias" | "jugadas">("resumen");
  const [tabTouched, setTabTouched] = useState(false);
  useEffect(() => {
    if (!tabTouched && data?.autopsia) setTab("revision");        // partido terminado: abre directo la revisión
  }, [data?.autopsia, tabTouched]);
  if (isLoading && !data) return <Loading />;
  if (!data) return <Empty>Partido no encontrado.</Empty>;
  const g = data, p = data.pred_full, m = data.market;
  const hasPred = p && p.p_home != null;

  return (
    <div className="space-y-6">
      <Link href="/" className="inline-flex items-center gap-1 text-sm text-ink2 hover:text-ink"><ArrowLeft size={15} /> Semana {g.week}</Link>

      {/* ---------- encabezado ---------- */}
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3 text-xs text-ink2">
          <div className="flex flex-wrap items-center gap-3">
            <span>{kickoffLabel(g.kickoff)}</span>
            <span className="inline-flex items-center gap-1"><MapPin size={12} />{g.venue}{g.city ? `, ${g.city}` : ""}</span>
            {g.broadcast && <span className="inline-flex items-center gap-1"><Tv size={12} />{g.broadcast}</span>}
            {g.weather && !g.indoor && (
              <span className="inline-flex items-center gap-1"><CloudSun size={12} />
                {g.weather.label} · {num(g.weather.temp_f, 0)}°F · viento {num(g.weather.wind_mph, 0)} mph
                {g.weather.precip_prob != null ? ` · lluvia ${Math.round(g.weather.precip_prob)}%` : ""}</span>
            )}
            {g.indoor && <span>Techado</span>}
          </div>
          <span className="flex items-center gap-2">
            {g.status === "pre" && p?.incertidumbre && p.incertidumbre.nivel !== "normal" && (
              <span title={p.incertidumbre.razones.join("\n")}
                className={clsx("rounded-md px-2 py-0.5 text-[11px] font-semibold", p.incertidumbre.nivel === "alta" ? "bg-[var(--warning)]/15 text-warning" : "bg-s3 text-ink2")}>
                Incertidumbre {p.incertidumbre.nivel}
              </span>
            )}
            {g.status === "pre" && <PublicOpinion pub={data.publico} home={g.home.abbr} away={g.away.abbr} />}
            {g.status === "pre" && <AskClaude text={`/partido ${g.away.abbr} vs ${g.home.abbr}`} />}
            <StatusPill status={g.status} detail={g.status_detail} period={g.period} clock={g.clock} />
          </span>
        </div>
        <div className="grid items-center gap-6 px-5 py-6 md:grid-cols-[1fr_auto_1fr]">
          <TeamSide t={g.away} p={hasPred ? p.p_away + p.p_tie / 2 : null} mu={hasPred ? p.away_mu : null} score={g.status !== "pre" ? g.away.score : null} align="left" />
          <div className="text-center text-xs text-mute">
            <div className="text-lg font-semibold text-ink2">@</div>
            {hasPred && <div className="mt-1">Tiempo extra<br /><span className="text-base font-semibold text-ink tnum">{pct(p.p_ot, 1)}</span></div>}
          </div>
          <TeamSide t={g.home} p={hasPred ? p.p_home + p.p_tie / 2 : null} mu={hasPred ? p.home_mu : null} score={g.status !== "pre" ? g.home.score : null} align="right" />
        </div>
        {hasPred && (
          <div className="px-5 pb-5">
            <WinBar left={g.away.abbr} right={g.home.abbr} pLeft={p.p_away + p.p_tie / 2} height={10} />
          </div>
        )}
        {hasPred && (
          <div className="grid gap-px border-t border-line bg-[var(--border)] sm:grid-cols-4">
            <MarketCell title="Ganador (moneyline)"
              market={`${g.away.abbr} ${american(m.ml_away)} · ${g.home.abbr} ${american(m.ml_home)}`}
              brain={`${g.home.abbr} ${pct(p.p_home + p.p_tie / 2)}`} />
            <MarketCell title="Hándicap"
              market={m.spread_home != null ? `${g.home.abbr} ${m.spread_home > 0 ? "-" : "+"}${Math.abs(m.spread_home)}${m.spread_home_open != null ? ` (abrió ${m.spread_home_open > 0 ? "-" : "+"}${Math.abs(m.spread_home_open)})` : ""}` : "—"}
              brain={`${p.margin_mu >= 0 ? g.home.abbr : g.away.abbr} por ${num(Math.abs(p.margin_mu), 1)} · ${g.home.abbr} cubre ${pct(p.p_home_cover)}`} />
            <MarketCell title="Total de puntos"
              market={m.total != null ? `${m.total}${m.total_open != null && m.total_open !== m.total ? ` (abrió ${m.total_open})` : ""}` : "—"}
              brain={`${num(p.total_mu, 1)} · más ${pct(p.p_over)}`} />
            <MarketCell title="Otras opiniones" labels={["Modelo puro", "ESPN FPI"]}
              market={p.model_only ? `${g.home.abbr} ${pct(p.model_only.p_home)}` : "—"}
              brain={g.fpi ? `${g.home.abbr} ${num(g.fpi.home, 0)}%` : "—"} />
          </div>
        )}
      </div>

      {g.status === "in" && data.en_vivo && <LivePanel v={data.en_vivo} home={g.home.abbr} away={g.away.abbr} />}

      <Segmented value={tab} onChange={(v) => { setTabTouched(true); setTab(v as typeof tab); }} options={[
        { value: "resumen", label: "Resumen" },
        ...(data.autopsia ? [{ value: "revision", label: "Revisión" }] : []),
        ...(g.status === "pre" && hasPred ? [{ value: "informe", label: "Informe" }] : []),
        ...(p?.escenarios ? [{ value: "escenarios", label: "Escenarios" }] : []),
        { value: "jugadores", label: "Jugadores", count: g.players.length },
        { value: "picks", label: "Picks", count: g.picks.length },
        { value: "lesiones", label: "Lesiones", count: g.injuries.filter((i) => i.p_play < 1).length },
        { value: "noticias", label: "Noticias", count: g.news.length },
        { value: "jugadas", label: g.status === "pre" ? "Videos" : "Jugadas y videos" },
      ]} />

      {tab === "resumen" && hasPred && <Summary g={data} />}
      {tab === "resumen" && data.books && Object.keys(data.books).length > 0 && <Books g={data} />}
      {tab === "resumen" && !hasPred && <Empty>Este partido ya se jugó antes de que Cinna lo analizara.</Empty>}
      {tab === "revision" && data.autopsia && <ReviewPanel a={data.autopsia} />}
      {tab === "informe" && <InformePanel id={g.game_id} />}
      {tab === "escenarios" && p?.caminos && <Caminos c={p.caminos} />}
      {tab === "escenarios" && p?.escenarios && <ScenariosPanel esc={p.escenarios} sq={p.esquema} home={g.home.abbr} away={g.away.abbr} />}
      {tab === "jugadores" && <Players g={data} />}
      {tab === "picks" && (g.picks.length ? (
        <div className="grid gap-4 lg:grid-cols-2">{g.picks.map((pk) => <PickCard key={pk.pick_id} p={pk} />)}</div>
      ) : <Empty>Sin picks con nivel para este partido todavía (las casas publican props unos días antes).</Empty>)}
      {tab === "lesiones" && <Injuries g={data} />}
      {tab === "noticias" && <NewsList items={g.news} />}
      {tab === "jugadas" && <JugadasPanel gameId={g.game_id} home={g.home.abbr} away={g.away.abbr} />}
    </div>
  );
}

function TeamSide({ t, p, mu, score, align }: { t: GameCard["home"]; p: number | null; mu: number | null; score: number | null | undefined; align: "left" | "right" }) {
  return (
    <div className={clsx("flex items-center gap-4", align === "right" && "md:flex-row-reverse md:text-right")}>
      <TeamLogo team={t} size={64} />
      <div>
        <div className="text-xs text-mute">{t.name}</div>
        <div className="text-2xl font-bold">{t.nick}</div>
        <div className="text-xs text-mute">{t.record}</div>
      </div>
      <div className={clsx("ml-auto", align === "right" && "md:ml-0 md:mr-auto")}>
        {score != null ? (
          <div className="text-5xl font-bold tnum">{score}</div>
        ) : p != null ? (
          <div>
            <div className="text-4xl font-bold tracking-tight tnum">{pct(p)}</div>
            <div className="text-xs text-mute">gana · proyecta {num(mu, 1)} pts</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MarketCell({ title, market, brain, labels = ["Mercado", "Cinna"] }: { title: string; market: string; brain: string; labels?: [string, string] | string[] }) {
  return (
    <div className="bg-s1 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-mute">{title}</div>
      <div className="mt-1 text-sm tnum"><span className="text-mute">{labels[0]} </span>{market}</div>
      <div className="text-sm font-semibold tnum"><span className="font-normal text-mute">{labels[1]} </span>{brain}</div>
    </div>
  );
}

function Summary({ g }: { g: GameResp }) {
  const p = g.pred_full;
  const H = g.home.abbr, A = g.away.abbr;
  return (
    <div className="grid gap-6 xl:grid-cols-[1.25fr_1fr]">
      <div className="space-y-6">
        {p.factors && p.factors.length > 0 && (
          <div className="card p-5">
            <SectionTitle>Claves del partido</SectionTitle>
            <ul className="space-y-2">
              {p.factors.map((f, i) => (
                <li key={i} className="flex items-start gap-3 text-sm">
                  {f.team ? <TeamLogo team={f.team === H ? g.home : g.away} size={20} /> : <span className="mt-1 h-2 w-2 rounded-full bg-mute" />}
                  <span className="text-ink2">{f.text}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="card p-5">
          <SectionTitle right={<span className="text-xs text-mute">{A} vs {H} · posición en la liga (1 = mejor)</span>}>Duelo ofensiva vs defensa</SectionTitle>
          <div className="space-y-4">
            {MATCHUPS.map(([label, ok, dk]) => (
              <div key={label}>
                <div className="mb-1.5 text-xs font-medium text-ink2">{label}</div>
                <DuelRow off={g.away} def={g.home} o={g.ranks.away?.[ok]} d={g.ranks.home?.[dk]} />
                <DuelRow off={g.home} def={g.away} o={g.ranks.home?.[ok]} d={g.ranks.away?.[dk]} />
              </div>
            ))}
          </div>
        </div>
        <div className="card p-5">
          <SectionTitle right={<span className="text-xs text-mute">20,000 simulaciones</span>}>Diferencia final ({H} − {A})</SectionTitle>
          <PmfChart pmf={p.margin_pmf} lo={-28} hi={28} line={g.market.spread_home != null ? g.market.spread_home : null} mu={p.margin_mu}
            overLabel={`${H} cubre`} underLabel={`${A} cubre`} fmtX={(v) => (v > 0 ? `+${v}` : `${v}`)} />
        </div>
        <div className="card p-5">
          <SectionTitle>Total de puntos</SectionTitle>
          <PmfChart pmf={p.total_pmf} lo={14} hi={76} line={g.market.total} mu={p.total_mu} overLabel="Más" underLabel="Menos" />
        </div>
      </div>
      <div className="space-y-6">
        <div className="card p-5">
          <SectionTitle>QB titulares</SectionTitle>
          {(["away", "home"] as const).map((side) => {
            const s = p.starters?.[side];
            const t = side === "home" ? g.home : g.away;
            const r = g.ranks[side]?.qb;
            return s ? (
              <div key={side} className="flex items-center gap-3 border-b border-line py-2.5 last:border-0">
                <TeamLogo team={t} size={24} />
                <div className="min-w-0 flex-1">
                  <Link href={`/jugador/${s.player_id}`} className="text-sm font-semibold hover:underline">{s.name}</Link>
                  <div className="text-xs text-mute">
                    {s.reason ? `Según ${s.reason}` : ""}{s.changed ? " · cambio de titular" : ""}
                    {s.p_play < 0.95 ? ` · ${pct(s.p_play)} de jugar` : ""}
                  </div>
                </div>
                {r && <div className="text-right text-xs"><div className="text-mute">EPA/jugada</div><div className="font-semibold tnum">{r.value != null ? (r.value > 0 ? "+" : "") + r.value.toFixed(2) : "—"}</div></div>}
              </div>
            ) : null;
          })}
        </div>
        <div className="card p-5">
          <SectionTitle>Marcadores más probables</SectionTitle>
          <div className="grid grid-cols-2 gap-2">
            {(p.top_scores ?? []).slice(0, 6).map((s, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg bg-s2 px-3 py-2 text-sm">
                <span className="tnum">{A} {s.away} – {s.home} {H}</span>
                <span className="text-xs text-mute tnum">{pct(s.p, 1)}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-4 text-xs">
            {(["away", "home"] as const).map((side) => (
              <div key={side}>
                <div className="mb-1.5 font-medium text-ink2">{side === "home" ? H : A} gana por…</div>
                {p.win_margin?.[side].map((w) => (
                  <div key={w.range} className="flex items-center gap-2 py-0.5">
                    <span className="w-10 text-mute tnum">{w.range}</span>
                    <div className="flex-1"><Meter value={w.p / 0.35} height={5} /></div>
                    <span className="w-10 text-right tnum">{pct(w.p)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div className="card p-5">
          <SectionTitle>Cómo se ha movido la predicción</SectionTitle>
          <ProbLine points={g.history.map((h) => ({ t: h.run_at, p: h.data.p_home }))} label={`gana ${H}`} />
        </div>
        <div className="card p-5 text-xs text-ink2">
          <div className="mb-2 font-semibold text-ink">Cómo se calcula</div>
          Puntos esperados: modelo {num(p.inputs?.model_away as number, 1)}–{num(p.inputs?.model_home as number, 1)}, mercado{" "}
          {num(p.inputs?.market_away as number, 1)}–{num(p.inputs?.market_home as number, 1)}, combinado{" "}
          {num(p.inputs?.final_away as number, 1)}–{num(p.inputs?.final_home as number, 1)}. Se simulan ~{num(p.inputs?.drives as number, 1)} series por equipo con la lógica de final de partido calibrada con 2016–2025.
        </div>
      </div>
    </div>
  );
}

function Books({ g }: { g: GameResp }) {
  const rows = Object.entries(g.books ?? {});
  const H = g.home.abbr, A = g.away.abbr;
  const best = (key: keyof BookLine) => {
    const vals = rows.filter(([b]) => b !== "Consenso" && b !== "Apertura").map(([, v]) => v[key] as number | null | undefined)
      .filter((x): x is number => x != null);
    if (!vals.length) return null;
    const dec = (o: number) => (o > 0 ? 1 + o / 100 : 1 + 100 / -o);
    return vals.reduce((a, b) => (dec(b) > dec(a) ? b : a));
  };
  const cell = (v: number | null | undefined, isBest: boolean) => (
    <span className={clsx("tnum", isBest ? "font-semibold text-good" : "text-ink2")}>{american(v ?? null)}</span>
  );
  const bML = { h: best("ml_home"), a: best("ml_away"), o: best("over_odds"), u: best("under_odds") };
  return (
    <div className="card overflow-x-auto">
      <div className="px-5 pt-4"><SectionTitle right={<span className="text-xs text-mute">en verde, el mejor precio</span>}>Comparador de casas</SectionTitle></div>
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-mute">
            <th className="px-5 py-2 font-medium">Casa</th>
            <th className="px-3 py-2 text-right font-medium">Gana {A}</th>
            <th className="px-3 py-2 text-right font-medium">Gana {H}</th>
            <th className="px-3 py-2 text-right font-medium">Hándicap {H}</th>
            <th className="px-3 py-2 text-right font-medium">Total</th>
            <th className="px-3 py-2 text-right font-medium">Más</th>
            <th className="px-3 py-2 text-right font-medium">Menos</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([b, v]) => (
            <tr key={b} className={clsx("border-b border-line last:border-0", (b === "Consenso" || b === "Apertura") && "bg-s2")}>
              <td className="px-5 py-2 font-medium">{b}</td>
              <td className="px-3 py-2 text-right">{cell(v.ml_away, v.ml_away === bML.a && b !== "Consenso" && b !== "Apertura")}</td>
              <td className="px-3 py-2 text-right">{cell(v.ml_home, v.ml_home === bML.h && b !== "Consenso" && b !== "Apertura")}</td>
              <td className="px-3 py-2 text-right tnum">{v.spread_home != null ? `${v.spread_home > 0 ? "-" : "+"}${Math.abs(v.spread_home)}` : "—"} <span className="text-mute">{american(v.spread_home_odds ?? null)}</span></td>
              <td className="px-3 py-2 text-right tnum">{v.total ?? "—"}</td>
              <td className="px-3 py-2 text-right">{cell(v.over_odds, v.over_odds === bML.o && b !== "Consenso" && b !== "Apertura")}</td>
              <td className="px-3 py-2 text-right">{cell(v.under_odds, v.under_odds === bML.u && b !== "Consenso" && b !== "Apertura")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DuelRow({ off, def, o, d }: { off: GameCard["home"]; def: GameCard["home"]; o?: Rank; d?: Rank }) {
  if (!o || !d) return null;
  // ventaja para la ofensiva si su rank es bueno y el de la defensa es malo
  const edge = d.rank - o.rank;
  return (
    <div className="flex items-center gap-2 py-0.5 text-xs">
      <TeamLogo team={off} size={16} />
      <span className="w-24 text-ink2">Ofensiva <b className="text-ink tnum">#{o.rank}</b></span>
      <div className="relative h-1.5 flex-1 rounded-full bg-s3">
        <div className="absolute top-0 h-1.5 rounded-full"
          style={{ left: edge >= 0 ? "50%" : `${50 + (edge / 31) * 50}%`, width: `${(Math.abs(edge) / 31) * 50}%`,
            background: edge >= 0 ? "var(--accent)" : "var(--neutral-bar)" }} />
        <div className="absolute left-1/2 top-[-3px] h-3 w-px bg-[var(--axis)]" />
      </div>
      <span className="w-24 text-right text-ink2">Defensa <b className="text-ink tnum">#{d.rank}</b></span>
      <TeamLogo team={def} size={16} />
    </div>
  );
}

const MAIN: Record<string, string[]> = {
  QB: ["pass_yds", "pass_att", "pass_tds", "qb_rush_yds"],
  RB: ["rush_yds", "rush_att", "rec_yds", "tds"],
  WR: ["rec_yds", "receptions", "targets", "tds"],
  TE: ["rec_yds", "receptions", "targets", "tds"],
};

function Players({ g }: { g: GameResp }) {
  const [team, setTeam] = useState(g.away.abbr);
  const list = g.players.filter((p) => p.team === team);
  if (!g.players.length) return <Empty>Sin proyecciones de jugadores para este partido.</Empty>;
  return (
    <div className="space-y-4">
      <Segmented value={team} onChange={setTeam} options={[
        { value: g.away.abbr, label: <span className="flex items-center gap-1.5"><TeamLogo team={g.away} size={16} />{g.away.abbr}</span> },
        { value: g.home.abbr, label: <span className="flex items-center gap-1.5"><TeamLogo team={g.home} size={16} />{g.home.abbr}</span> },
      ]} />
      {["QB", "RB", "WR", "TE"].map((pos) => {
        const ps = list.filter((p) => p.position === pos);
        if (!ps.length) return null;
        return (
          <div key={pos} className="card overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-mute">
                  <th className="px-4 py-2.5 font-medium">{pos}</th>
                  {MAIN[pos].map((s) => <th key={s} className="px-3 py-2.5 text-right font-medium">{ps[0].stats[s]?.label ?? s}</th>)}
                  <th className="px-3 py-2.5 text-right font-medium">Snaps</th>
                </tr>
              </thead>
              <tbody>
                {ps.map((p) => (
                  <tr key={p.player_id} className="border-b border-line last:border-0 hover:bg-s2">
                    <td className="px-4 py-2.5">
                      <Link href={`/jugador/${p.player_id}`} className="flex items-center gap-2.5">
                        <Headshot src={p.headshot} name={p.name} size={30} />
                        <div>
                          <div className="font-medium hover:underline">{p.name}</div>
                          {p.availability.p_play < 0.97 && <div className="text-[11px] text-serious">{p.availability.status} · {pct(p.availability.p_play)}</div>}
                        </div>
                      </Link>
                    </td>
                    {MAIN[pos].map((s) => {
                      const st = p.stats[s];
                      if (!st) return <td key={s} className="px-3 text-right text-mute">—</td>;
                      const ou = st.lines.find((l) => l.kind === "ou");
                      return (
                        <td key={s} className="px-3 py-2.5 text-right tnum">
                          <div className="font-semibold">{s === "tds" ? pct(st.p_any) : num(st.med ?? st.mu, s.includes("yds") ? 0 : 1)}</div>
                          {ou ? (
                            <div className={clsx("text-[11px]", ou.tier ? "text-accent" : "text-mute")}>
                              {ou.line} · {ou.side === "over" ? "más" : "menos"} {pct(ou.p_side)}
                            </div>
                          ) : s === "tds" ? <div className="text-[11px] text-mute">anota</div> : null}
                        </td>
                      );
                    })}
                    <td className="px-3 text-right text-ink2 tnum">{pct(p.role.snap_pct as number)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

function Injuries({ g }: { g: GameResp }) {
  const list = g.injuries.filter((i) => i.p_play < 1 || i.data.history?.length);
  if (!list.length) return <Empty>Sin reportes de lesiones relevantes.</Empty>;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {list.map((i) => (
        <div key={i.player_id} className="card p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <Link href={`/jugador/${i.player_id}`} className="font-semibold hover:underline">{i.name}</Link>
              <div className="text-xs text-mute">{i.position} · {i.team} · fuente: {i.source}</div>
            </div>
            <div className="text-right">
              <div className={clsx("text-sm font-semibold", i.p_play < 0.2 ? "text-critical" : i.p_play < 0.8 ? "text-serious" : "text-good")}>{i.status}</div>
              <div className="text-xs text-mute tnum">{pct(i.p_play)} de jugar</div>
            </div>
          </div>
          {i.comment && <p className="mt-2 text-[13px] text-ink2">{i.comment}</p>}
          {i.data.history?.length > 1 && (
            <div className="mt-2 space-y-1 border-t border-line pt-2">
              {i.data.history.slice(-4).reverse().map((h, k) => (
                <div key={k} className={clsx("text-xs", h.applied === false ? "text-mute" : "text-ink2")}>
                  <span className="font-medium">{h.src}</span>{h.at ? ` · ${ago(h.at)}` : ""}: {h.text}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** Copia la pregunta para Claude (con el conector de Cinna) y lleva a las instrucciones si hace falta. */
function AskClaude({ text }: { text: string }) {
  const [ok, setOk] = useState(false);
  return (
    <button
      title="Copia el comando para pedirle a Claude el análisis de este partido y 3 parlays verificados"
      onClick={() => navigator.clipboard?.writeText(text).then(() => { setOk(true); setTimeout(() => setOk(false), 2000); })}
      className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-xs text-ink2 hover:border-accent hover:text-ink"
    >
      {ok ? <Check size={13} className="text-good" /> : <MessageSquareText size={13} />}
      {ok ? "Copiado: pégalo en Claude" : "Pregúntale a Claude"}
    </button>
  );
}
