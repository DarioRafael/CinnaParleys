"use client";

import { Ticket } from "@phosphor-icons/react";
import clsx from "clsx";
import { Bomb, Check, Clapperboard, Copy, Crosshair, Crown, Flame, Layers, Link2, Scale, ShieldCheck, Target, Trophy } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { GameCard, Pick, american, kickoffLabel, pct, useApi } from "@/lib/api";
import { useParlay } from "@/components/parlay";
import { EvChip } from "@/components/pick-card";
import { Empty, Headshot, Loading, SectionTitle, TeamLogo, TierBadge, PageHeader } from "@/components/ui";
import { PlanSemana } from "@/components/plan";
import { ParlaysGuion } from "@/components/guiones";
import { SuperParlay } from "@/components/superparlay";
import { MisApuestas } from "@/components/misapuestas";
import { useTeams } from "@/components/teams";

type Leg = {
  pick_id: string; log_id?: string; game_id: string; player_id?: string | null; team?: string | null; market: string;
  kind: string; side: string; line?: number | null; prob: number; dec?: number | null; book?: string | null;
  odds?: number | null; title: string; game_label?: string; tier?: string | null; headshot?: string | null;
  name?: string; position?: string; triple?: boolean; fact?: string | null; kickoff?: string; nivel?: number; elite?: boolean;
};
type Parlay = {
  id: string; legs: Leg[]; p_joint: number; p_independent: number; lift: number; same_game: boolean;
  payout_dec: number | null; payout_american: number | null; fair_dec: number; fair_american: number;
  ev: number | null; notes: { a: number; b: number; r: number; text: string }[]; games: string[]; first_kickoff: string;
};
type Resp = { mode: string; label: string; desc: string; legs: number; min_p: number; parlays: Parlay[];
  n_candidates: number; modes: Record<string, { label: string; desc: string; legs: number; min_p: number }>;
  cartera?: { n: number; p_al_menos_uno: number; ev_promedio: number } | null; casa?: string | null; casas?: string[] };

const MODES = [
  { key: "top_elite", icon: Trophy, label: "Top Élite" },
  { key: "elite", icon: Crown, label: "Solo Élite" },
  { key: "segura", icon: ShieldCheck, label: "La más segura" },
  { key: "balanceada", icon: Scale, label: "Balanceada" },
  { key: "bomba", icon: Bomb, label: "Bomba" },
  { key: "mismo_partido", icon: Link2, label: "Mismo partido" },
  { key: "tds", icon: Flame, label: "Touchdowns" },
  { key: "objetivo", icon: Target, label: "Pago objetivo" },
  { key: "guion", icon: Clapperboard, label: "Guion del partido" },
];

export default function ParlaysPage() {
  return <Suspense fallback={<Loading />}><ParlaysInner /></Suspense>;
}

function ParlaysInner() {
  const sp = useSearchParams();
  const [mode, setMode] = useState("top_elite");
  const [strict, setStrict] = useState(false);
  const [draftea, setDraftea] = useState(sp.get("draftea") === "1");
  const [target, setTarget] = useState("3");
  const [legs, setLegs] = useState<number | null>(null);
  const [minP, setMinP] = useState<number | null>(null);
  const [payout, setPayout] = useState("");
  const [games, setGames] = useState<string[]>([]);
  const [casa, setCasa] = useState(sp.get("casa") ?? "Draftea");      // su casa principal: con su regla
  const [escaleras, setEscaleras] = useState(false);
  const { data: week } = useApi<{ week: number; weeks: number[]; games: GameCard[] }>("/api/week");
  const nextWeek = week?.weeks.find((w) => w > week.week);
  const { data: week2 } = useApi<{ games: GameCard[] }>(nextWeek ? `/api/week?week=${nextWeek}` : null);
  const upcoming = [...(week?.games ?? []), ...(week2?.games ?? [])].filter((g) => g.status === "pre");
  const q = useMemo(() => {
    const p = new URLSearchParams({ mode });
    if (legs) p.set("legs", String(legs));
    if (minP != null) p.set("min_p", String(minP));
    if (games.length) p.set("games", games.join(","));
    const pay = parseFloat(payout);
    if (!isNaN(pay) && pay > 1) p.set("payout", String(pay));
    if (strict) p.set("strict", "true");
    if (draftea) p.set("draftea", "true");
    if (casa && !draftea) p.set("casa", casa);
    if (escaleras) p.set("lineas", "todas");
    const t = parseFloat(target);
    if (mode === "objetivo" && !isNaN(t) && t > 1) p.set("target", String(t));
    return `/api/parlays?${p.toString()}`;
  }, [mode, legs, minP, games, payout, strict, draftea, target, casa, escaleras]);
  const { data, isLoading, isValidating } = useApi<Resp>(q);
  const cfg = data?.modes?.[mode];

  return (
    <div className="space-y-5">
      <PageHeader duo={Ticket} tone="miel" kicker="a jugar" title="Parlays">
        <p>
          Cinna arma combinaciones simulando 20,000 escenarios con las correlaciones reales entre jugadores
          (si el QB lanza mucho, su receptor también sube). Te dice la probabilidad real de que salga todo,
          lo que paga la casa y si tiene valor. Por defecto usa sólo <b>líneas principales</b> (Más/Menos, anota TD,
          ganador, hándicap y total), que son las que ponen Draftea y Playdoit.
        </p>
      </PageHeader>

      <SuperParlay />

      <MisApuestas />

      <ParlaysGuion />

      <PlanSemana />

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5 2xl:grid-cols-9">
        {MODES.map(({ key, icon: Icon, label }) => (
          <button key={key} onClick={() => { setMode(key); setLegs(null); setMinP(null); }}
            className={clsx("card flex flex-col items-start gap-1.5 px-3.5 py-3 text-left transition-colors",
              mode === key ? "border-accent bg-accent-soft" : "hover:border-line-strong")}>
            <Icon size={18} className={mode === key ? "text-accent" : "text-ink2"} />
            <span className="text-sm font-semibold">{label}</span>
            <span className="line-clamp-2 text-[11px] text-mute">{data?.modes?.[key]?.desc ?? ""}</span>
          </button>
        ))}
      </div>

      <div className="card flex flex-wrap items-end gap-4 px-4 py-3">
        <label className="text-xs text-mute">
          Líneas y momios de
          <div className="mt-1 flex rounded-lg bg-s2 p-0.5">
            {[...((data?.casas ?? ["Draftea"]).map((c) => [c, c])), ["", "Mejor precio (8 casas)"]].map(([v, l]) => (
              <button key={v} disabled={draftea} onClick={() => setCasa(v)}
                className={clsx("rounded-md px-2.5 py-1 text-sm", casa === v && !draftea ? "bg-s3 font-semibold text-ink" : "text-ink2", draftea && "opacity-50")}>{l}</button>
            ))}
          </div>
        </label>
        <label className="text-xs text-mute">
          Picks
          <div className="mt-1 flex rounded-lg bg-s2 p-0.5">
            {[2, 3, 4, 5, 6].map((n) => (
              <button key={n} onClick={() => setLegs(n)}
                className={clsx("rounded-md px-2.5 py-1 text-sm tnum", (legs ?? cfg?.legs) === n ? "bg-s3 font-semibold text-ink" : "text-ink2")}>{n}</button>
            ))}
          </div>
        </label>
        <label className="text-xs text-mute">
          Prob. mínima por pick
          <select value={minP ?? data?.min_p ?? cfg?.min_p ?? ""} onChange={(e) => setMinP(parseFloat(e.target.value))}
            className="mt-1 block rounded-lg border border-line bg-s2 px-2.5 py-1.5 text-sm text-ink outline-none">
            {Array.from(new Set([0.15, 0.25, 0.35, 0.45, 0.5, 0.55, 0.6, 0.62, 0.65, 0.7, 0.75, 0.8, ...(cfg ? [cfg.min_p] : []), ...(data?.min_p ? [data.min_p] : [])]))
              .sort((a, b) => a - b).map((v) => <option key={v} value={v}>{Math.round(v * 100)}%</option>)}
          </select>
        </label>
        {mode === "objetivo" && (
          <label className="text-xs text-mute">
            Quiero que pague (x)
            <input value={target} onChange={(e) => setTarget(e.target.value)} inputMode="decimal"
              className="mt-1 block w-24 rounded-lg border border-accent bg-s2 px-2.5 py-1.5 text-sm text-ink outline-none tnum" />
          </label>
        )}
        <label className="flex cursor-pointer items-center gap-2 self-center rounded-lg border border-line px-3 py-2 text-xs text-ink2">
          <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} className="accent-[var(--accent)]" />
          Solo picks blindados
        </label>
        <label className="flex cursor-pointer items-center gap-2 self-center rounded-lg border border-line px-3 py-2 text-xs text-ink2"
          title="Escaleras tipo 40+ yds o 60+ yds y 2+ TDs. Apagado = sólo líneas principales como las de Draftea">
          <input type="checkbox" checked={escaleras} onChange={(e) => setEscaleras(e.target.checked)} className="accent-[var(--accent)]" />
          Incluir escaleras (X+)
        </label>
        <label className="flex cursor-pointer items-center gap-2 self-center rounded-lg border border-line px-3 py-2 text-xs text-ink2">
          <input type="checkbox" checked={draftea} onChange={(e) => setDraftea(e.target.checked)} className="accent-[var(--accent)]" />
          Con mis líneas de Draftea
        </label>
        <label className="text-xs text-mute">
          Lo que paga Draftea (opcional)
          <input value={payout} onChange={(e) => setPayout(e.target.value)} inputMode="decimal" placeholder="p. ej. 3.5"
            className="mt-1 block w-32 rounded-lg border border-line bg-s2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent tnum" />
        </label>
        <div className="min-w-0 basis-full text-xs text-mute">
          Partidos {games.length ? `(${games.length})` : "(todos)"}
          <div className="mt-1 flex flex-wrap gap-1.5">
            {upcoming.map((g) => {
              const on = games.includes(g.game_id);
              return (
                <button key={g.game_id} onClick={() => setGames((x) => (on ? x.filter((y) => y !== g.game_id) : [...x, g.game_id]))}
                  className={clsx("flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]",
                    on ? "border-accent bg-accent-soft text-accent" : "border-line text-ink2 hover:text-ink")}>
                  <TeamLogo team={g.away} size={14} />{g.away.abbr}@{g.home.abbr}<TeamLogo team={g.home} size={14} />
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {data?.cartera && data.parlays.length > 1 && (
        <div className="card flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3 text-sm">
          <span className="font-semibold">Cartera de {data.cartera.n} parlays</span>
          <span className="text-ink2">Probabilidad de que salga <b className="text-ink">al menos uno</b>: <b className="text-ink tnum">{pct(data.cartera.p_al_menos_uno, 1)}</b></span>
          <span className="text-ink2">Valor esperado promedio: <b className={clsx("tnum", data.cartera.ev_promedio > 0 ? "text-good" : "text-ink")}>{data.cartera.ev_promedio > 0 ? "+" : ""}{(data.cartera.ev_promedio * 100).toFixed(1)}%</b></span>
          <span className="text-xs text-mute">Comparten pocos picks entre sí: un fallo no tumba a todos.</span>
        </div>
      )}
      {draftea && <div className="text-xs text-mute">Usando sólo tus líneas guardadas de Draftea y sus pagos. <a href="/draftea" className="text-accent hover:underline">Editar</a></div>}
      {casa === "Draftea" && !draftea && <div className="rounded-lg border border-accent/40 bg-accent-soft px-4 py-2.5 text-sm text-ink2">
        <b className="text-ink">Regla de Draftea:</b> como máximo <b className="text-ink">una Más/Menos de jugador por partido</b>; lo demás son
        escalones <b className="text-ink">X+</b> (Cinna te dice el número: si Draftea no lo tiene exacto, usa el inmediato <b>inferior</b>),
        ganador, hándicap, total o anota TD. Los pagos son aproximados: verifica el momio en Draftea. <a href="/draftea" className="text-accent hover:underline">Ver escalones por jugador</a>
      </div>}
      {casa && casa !== "Draftea" && !draftea && <div className="text-xs text-mute">Sólo líneas y momios que <b className="text-ink2">{casa}</b> tiene publicados ahora (casi iguales a los de Draftea). Los props de jugador aparecen cuando la casa los publica, normalmente 1–2 días antes del partido.</div>}

      {isLoading && !data ? <Loading label="Simulando 20,000 escenarios…" /> : data && data.parlays.length ? (
        <div className={clsx("grid gap-4 xl:grid-cols-2", isValidating && "opacity-60 transition-opacity")}>
          {data.parlays.map((p, i) => <ParlayCard key={p.id} p={p} rank={i + 1} customPayout={!!parseFloat(payout)} casa={data.casa} />)}
        </div>
      ) : (
        <Empty>
          No hay combinaciones que cumplan estos filtros todavía ({data?.n_candidates ?? 0} picks candidatos).
          Prueba bajar la probabilidad mínima o agregar partidos. Las casas publican las props unos días antes de cada partido.
        </Empty>
      )}
    </div>
  );
}

function ParlayCard({ p, rank, customPayout, casa }: { p: Parlay; rank: number; customPayout: boolean; casa?: string | null }) {
  const teams = useTeams();
  const { add, setOpen } = useParlay();
  const [copied, setCopied] = useState(false);
  const toPick = (l: Leg): Pick => ({
    pick_id: l.pick_id, game_id: l.game_id, player_id: l.player_id, type: l.player_id ? "player" : "game",
    market: l.market, kind: l.kind, market_label: "", side: l.side, line: l.line, prob: l.prob, tier: (l.tier as Pick["tier"]) ?? null,
    confidence: 0, title: l.title, kickoff: l.kickoff ?? "", game_label: l.game_label ?? "", team: l.team ?? undefined,
    headshot: l.headshot, name: l.name, position: l.position, odds: l.odds, book: l.book,
  });
  const copy = () => {
    const txt = [`Parlay (${pct(p.p_joint, 1)} de que salga, paga ${p.payout_dec ?? "?"}x)`,
      ...p.legs.map((l, i) => `${i + 1}. ${l.title} — ${pct(l.prob)}${l.book ? ` · ${l.book} ${american(l.odds)}` : ""}`)].join("\n");
    navigator.clipboard?.writeText(txt).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  };
  const good = p.ev != null && p.ev > 0.02;
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-mute">
            <span className="rounded-md bg-s3 px-1.5 py-0.5 font-semibold text-ink2">#{rank}</span>
            {p.legs.length} picks · {p.games.length} {p.games.length === 1 ? "partido" : "partidos"}
            {p.same_game && <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-accent">mismo partido</span>}
          </div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-4xl font-bold tracking-tight">{pct(p.p_joint, 1)}</span>
            <span className="text-sm text-mute">de que salga todo</span>
          </div>
          <div className="mt-0.5 text-xs text-ink2">
            Si fueran independientes: {pct(p.p_independent, 1)}
            {p.lift > 1.04 ? " · se ayudan entre sí" : p.lift < 0.96 ? " · se estorban un poco" : ""}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-mute">{customPayout ? "Paga (Draftea)" : casa === "Draftea" ? "Paga aprox. en Draftea" : casa ? `Paga en ${casa}` : "Paga (mejores casas)"}</div>
          <div className="text-2xl font-semibold tnum">{p.payout_dec ? `${p.payout_dec}x` : "—"}
            <span className="ml-1.5 text-sm text-mute">{american(p.payout_american)}</span></div>
          <div className="mt-1 flex items-center justify-end gap-2 text-xs">
            <span className="text-mute tnum">justo {p.fair_dec}x</span>
            <EvChip ev={p.ev} />
          </div>
        </div>
      </div>
      <div className="divide-y divide-[var(--border)]">
        {p.legs.map((l, i) => (
          <div key={l.pick_id} className="flex items-center gap-3 px-5 py-2.5">
            <span className="w-4 text-xs text-mute tnum">{i + 1}</span>
            {l.player_id ? <Headshot src={l.headshot} name={l.name} size={32} /> : <TeamLogo team={teams[l.team ?? l.side] ?? null} size={32} />}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">
                {casa === "Draftea" && l.player_id && (l.kind === "escalon" || l.kind === "ou") && (
                  <span className={clsx("mr-1.5 rounded px-1.5 py-0.5 align-middle text-[10px] font-semibold",
                    l.kind === "escalon" ? "bg-s3 text-ink2" : "bg-accent/15 text-accent")}>{l.kind === "escalon" ? "X+" : "M/M"}</span>
                )}
                {l.title}
              </div>
              <div className="truncate text-xs text-mute">
                {l.game_label}{l.kickoff ? ` · ${kickoffLabel(l.kickoff)}` : ""}{l.book ? ` · ${l.book} ${american(l.odds)}` : ""}
              </div>
            </div>
            {l.triple && <Crosshair size={14} className="text-accent" aria-label="Triple coincidencia" />}
            <TierBadge tier={l.tier} />
            <span className="w-12 text-right text-sm font-semibold tnum">{pct(l.prob)}</span>
          </div>
        ))}
      </div>
      {p.notes.length > 0 && (
        <div className="border-t border-line px-5 py-3">
          {p.notes.slice(0, 3).map((n, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs text-ink2">
              <Link2 size={12} className={n.r > 0 ? "text-good" : "text-critical"} />{n.text}
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between border-t border-line px-5 py-2.5">
        <span className={clsx("text-xs", good ? "text-good" : "text-mute")}>
          {p.ev == null ? "" : good ? "Paga más de lo que debería: tiene valor" : "Paga menos que su probabilidad real"}
          {p.same_game && !customPayout ? " · pago estimado para mismo partido" : ""}
        </span>
        <div className="flex gap-2">
          <button onClick={copy} className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-xs text-ink2 hover:text-ink">
            {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copiado" : "Copiar"}
          </button>
          <button onClick={() => { p.legs.forEach((l) => add(toPick(l))); setOpen(true); }}
            className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1 text-xs font-semibold text-on-accent">
            <Layers size={13} /> Al combinado
          </button>
        </div>
      </div>
    </div>
  );
}
