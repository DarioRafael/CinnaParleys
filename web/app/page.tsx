"use client";

import { Duo, IconTile } from "@/components/icons";
import { Broadcast, Cake, Clover, Coffee, Cookie, Football, MoonStars, Rocket, Sparkle, Ticket, Trophy } from "@phosphor-icons/react";
import clsx from "clsx";
import { AlertTriangle, ArrowLeft, CloudRain, Home, Wind } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { GameCard, Pick, dayKey, kickoffLabel, num, pct, useApi } from "@/lib/api";
import { PickCard } from "@/components/pick-card";
import { CountUp, Empty, Loading, SectionTitle, StatusPill, TeamLogo, TierBadge, WinBar } from "@/components/ui";
import { CinnaBun } from "@/components/brand";
import { Romper, RomperList } from "@/components/scenarios";
import { MenuData, useMenu, useMood } from "@/components/shell";
import { Clip, VideoRail } from "@/components/videos";

function saludo() {
  const h = new Date().getHours();
  return h < 12 ? "Buenos días" : h < 19 ? "Buenas tardes" : "Buenas noches";
}

type WeekResp = { season: number; week: number; weeks: number[]; games: GameCard[] };

export default function Page() {
  return <Suspense fallback={<Loading label="Horneando la semana…" />}><WeekPage /></Suspense>;
}

/** Lo que Cinna dice en su globito: cambia con el momento (en vivo, día de partido, mañana, noche). */
function mensajes(m: MenuData | undefined, games: GameCard[]): string[] {
  const out: string[] = [];
  const h = new Date().getHours();
  const vivo = games.filter((g) => g.status === "in").length;
  if (vivo) out.push(`¡Hay ${vivo} partido${vivo > 1 ? "s" : ""} en vivo! La probabilidad se mueve al momento.`);
  const nx = m?.proximo;
  if (nx) {
    const hrs = (new Date(nx.kickoff).getTime() - Date.now()) / 3.6e6;
    if (hrs > 0 && hrs < 30) out.push(`${hrs < 12 ? "Hoy" : "Ya casi"} juegan ${nx.away.abbr} @ ${nx.home.abbr}. Revisa los inactivos 90 min antes.`);
  }
  if (m) out.push(`Te horneé ${m.conteos.segura} picks seguras y ${m.conteos.valor} de valor.`);
  if (m?.clips.length) out.push("Hay videos nuevos: ponte cómodo y agarra palomitas.");
  out.push(h < 12 ? "¡Buenos días! Café, datos y nada de corazonadas."
    : h >= 22 ? "Ya es noche: apuesta poquito y duerme bien."
      : "Dos o tres patas sanas valen más que un parlay de ocho.");
  return out;
}

function Globito({ msgs }: { msgs: string[] }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((x) => x + 1), 7000);
    return () => clearInterval(t);
  }, []);
  if (!msgs.length) return null;
  const msg = msgs[i % msgs.length];
  return (
    <div key={msg} className="swap-in relative inline-block max-w-[330px] rounded-2xl rounded-tl-[4px] border border-line bg-pill px-3 py-1.5 font-hand text-[17px] font-medium leading-[1.15] text-ink2 shadow-sm">
      {msg}
    </div>
  );
}

function WeekPage() {
  const params = useSearchParams();
  const pasada = params.get("semana") ? Number(params.get("semana")) : null;
  const { data, isLoading, mutate } = useApi<WeekResp>(`/api/week${pasada ? `?week=${pasada}` : ""}`);
  const { data: m } = useMenu();
  const mood = useMood(m);
  const { data: picks } = useApi<{ picks: Pick[]; counts: Record<string, number> }>("/api/picks?tier=segura&limit=60");
  const { data: changes } = useApi<{ changes: { at: string; message: string }[] }>("/api/changes?limit=4");
  const { data: romper } = useApi<{ romper: Romper[] }>("/api/romper?limit=8");
  const { data: vids } = useApi<{ videos: Clip[] }>("/api/videos?limit=14");
  type HP = { parlays: { id: string; p_joint: number; payout_dec: number | null; legs: { pick_id: string; title: string; prob: number; game_label?: string }[] }[];
    modes?: Record<string, { desc: string }> };
  // regla de Draftea (una Más/Menos por partido): el Top Élite es el parlay con mejor historial
  const { data: sp } = useApi<HP>("/api/parlays?mode=top_elite&legs=2&top=1&casa=Draftea");
  const { data: t3 } = useApi<HP>("/api/parlays?mode=top_elite&legs=3&top=1&casa=Draftea");
  const { data: bal } = useApi<HP>("/api/parlays?mode=balanceada&top=1&casa=Draftea");

  const live = data?.games.some((g) => g.status === "in");
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => fetch("/api/live").then(() => mutate()), 45000);
    return () => clearInterval(t);
  }, [live, mutate]);

  if (isLoading && !data) return <Loading label="Horneando la semana…" />;
  if (!data || !data.games.length) return <Empty>Todavía no hay partidos cargados. Cinna está horneando los datos…</Empty>;

  const liveGames = data.games.filter((g) => g.status === "in");
  const groups: Record<string, GameCard[]> = {};
  for (const g of data.games.filter((x) => x.status === "pre")) (groups[dayKey(g.kickoff)] ??= []).push(g);
  const finals = data.games.filter((g) => g.status === "post");
  const counts = picks?.counts ?? {};
  const actual = m?.semana ?? data.week;
  const pasadas = data.weeks.filter((w) => w < actual).reverse();

  if (pasada && pasada !== actual) {
    return (
      <div className="space-y-6">
        <div className="hero px-5 py-5 md:px-7 md:py-6">
          <div className="relative z-10 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <CinnaBun size={64} mood="think" className="bob hidden shrink-0 sm:block" />
              <div>
                <div className="-rotate-1 font-hand text-[19px] font-semibold leading-none text-brand">de la libreta de Cinna</div>
                <h1 className="font-display text-[30px] font-semibold leading-tight">Semana {data.week} · resultados</h1>
                <p className="text-sm text-ink2">Cómo terminó cada partido y qué tanto se acercó Cinna.</p>
              </div>
            </div>
            <Link href="/" className="inline-flex items-center gap-1.5 rounded-full bg-brand-fill px-4 py-2 text-sm font-bold text-on-brand shadow-[0_8px_16px_-10px_var(--brand)]">
              <ArrowLeft size={15} /> Volver a la semana {actual}
            </Link>
          </div>
        </div>
        <PasadasChips weeks={pasadas} sel={data.week} />
        <section>
          <SectionTitle icon={Trophy} tone="miel">Resultados</SectionTitle>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {finals.map((g) => <FinalTile key={g.game_id} g={g} />)}
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="hero px-5 py-5 md:px-7 md:py-6">
        {/* repostería flotando, muy discreta */}
        <Duo icon={Cake} tone="rosa" size={34} className="float-a absolute right-[36%] top-3 hidden opacity-80 2xl:block" />
        <Duo icon={Cookie} tone="canela" size={30} className="float-b absolute bottom-3 right-[44%] hidden opacity-75 2xl:block" />
        <Duo icon={Sparkle} tone="miel" size={24} className="float-b absolute right-[30%] top-[45%] hidden opacity-80 xl:block" />
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-5">
          <div className="flex min-w-0 items-center gap-4">
            <div className="relative shrink-0 self-start sm:self-auto">
              <CinnaBun size={88} mood={mood} className="bob h-[58px] w-[58px] sm:h-[88px] sm:w-[88px]" />
              {mood === "sleepy" && <IconTile icon={MoonStars} tone="lila" size={28} className="float-a absolute -right-2 -top-1" />}
              {mood === "wow" && <IconTile icon={Football} tone="canela" size={28} className="float-a absolute -right-2 -top-2" />}
              {mood === "happy" && new Date().getHours() < 12 && <IconTile icon={Coffee} tone="canela" size={28} className="float-b absolute -right-2 top-0" />}
            </div>
            <div className="min-w-0">
              <div className="-rotate-1 font-hand text-[20px] font-semibold leading-none text-brand">{saludo()} · temporada {data.season}</div>
              <h1 className="mt-1 font-display text-[32px] font-semibold leading-tight tracking-tight md:text-[38px]">Semana {data.week}</h1>
              <p className="mt-0.5 text-sm text-ink2">
                <b className="text-ink tnum">{data.games.length}</b> partidos en la mesa
                {liveGames.length > 0 && <>, <b className="text-critical tnum">{liveGames.length}</b> en vivo</>}
                {finals.length > 0 && <>, <b className="text-ink tnum">{finals.length}</b> ya terminados</>}.
              </p>
              <div className="mt-2"><Globito msgs={mensajes(m, data.games)} /></div>
            </div>
          </div>
          <div className="grid w-full grid-cols-3 gap-2 sm:flex sm:w-auto">
            {(["segura", "valor", "arriesgada"] as const).map((t, k) => (
              <Link key={t} href={`/picks?tier=${t}`} style={{ animationDelay: `${0.1 + k * 0.08}s` }}
                className="enter card card-lift flex flex-col items-start gap-1.5 px-3 py-2.5 sm:flex-row sm:items-center sm:gap-3 sm:px-4">
                <TierBadge tier={t} size="md" />
                <span className="font-display text-2xl font-semibold tnum"><CountUp value={counts[t] ?? 0} /></span>
              </Link>
            ))}
          </div>
        </div>
      </div>

      {changes && changes.changes.length > 0 && (
        <div className="card flex items-start gap-3 border-l-4 border-l-[var(--caramel)] px-4 py-3">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warning" />
          <div className="min-w-0 flex-1 text-sm">
            <span className="font-semibold">Lo último que cambió Cinna: </span>
            <span className="text-ink2">{changes.changes[0].message}</span>
          </div>
          <Link href="/noticias" className="shrink-0 text-xs text-accent hover:underline">Ver todos</Link>
        </div>
      )}

      {picks && picks.picks.length > 0 && (
        <section>
          <SectionTitle icon={Clover} tone="menta" right={<Link href="/picks" className="text-xs text-accent hover:underline">Ver todos los picks</Link>}>
            Las más seguras de la semana
          </SectionTitle>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {[...picks.picks].sort((a, b) => (Number(!!b.super_elite) - Number(!!a.super_elite)) || (Number(a.kind === "alt") - Number(b.kind === "alt")) || (b.confidence - a.confidence)).slice(0, 3).map((p) => <PickCard key={p.pick_id} p={p} />)}
          </div>
        </section>
      )}

      {liveGames.length > 0 && (
        <section>
          <SectionTitle icon={Broadcast} tone="rosa">En vivo</SectionTitle>
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {liveGames.map((g) => <GameTile key={g.game_id} g={g} />)}
          </div>
        </section>
      )}

      {((sp?.parlays?.length ?? 0) > 0 || (bal?.parlays?.length ?? 0) > 0) && (
        <section>
          <SectionTitle icon={Ticket} tone="miel" right={<Link href="/parlays" className="text-xs text-accent hover:underline">Armar más parlays</Link>}>
            Parlays de la semana (regla de Draftea)
          </SectionTitle>
          {sp?.modes?.top_elite?.desc && <p className="-mt-1 mb-3 text-xs text-mute">{sp.modes.top_elite.desc}</p>}
          <div className="grid gap-4 md:grid-cols-3">
            {[{ t: "Top Élite · 2 patas", p: sp?.parlays?.[0] }, { t: "Top Élite · 3 patas", p: t3?.parlays?.[0] },
              { t: "Balanceado", p: bal?.parlays?.[0] }].map(({ t, p }) => p ? (
              <Link key={t} href="/parlays" className="card card-lift block p-4">
                <div className="flex items-end justify-between">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-mute">{t}</div>
                    <div className="mt-1 font-display text-3xl font-semibold tracking-tight">{pct(p.p_joint, 1)}</div>
                    <div className="text-xs text-mute">de que salga todo</div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-mute">Paga</div>
                    <div className="text-xl font-semibold tnum">{p.payout_dec ? `${p.payout_dec}x` : "—"}</div>
                  </div>
                </div>
                <ul className="mt-3 space-y-1 border-t border-line pt-3">
                  {p.legs.map((l) => (
                    <li key={l.pick_id} className="flex justify-between gap-3 text-sm">
                      <span className="line-clamp-2 text-ink2">{l.title}</span><span className="shrink-0 font-semibold tnum">{pct(l.prob)}</span>
                    </li>
                  ))}
                </ul>
              </Link>
            ) : null)}
          </div>
        </section>
      )}

      {(vids?.videos?.length ?? 0) > 0 && (
        <VideoRail clips={vids!.videos} title="Para ver con palomitas"
          right={<Link href="/videos" className="mr-1 text-xs text-accent hover:underline">Todos los videos</Link>} />
      )}

      {(romper?.romper?.length ?? 0) > 0 && (
        <section>
          <SectionTitle icon={Rocket} tone="lila" right={<span className="text-xs text-mute">juegos de 100+ yds, 2+ TDs, 300+ de pase…</span>}>
            La pueden romper
          </SectionTitle>
          <RomperList items={romper!.romper} showGame />
        </section>
      )}

      {Object.entries(groups).map(([day, games]) => (
        <section key={day}>
          <SectionTitle icon={Football} tone="canela">{day}</SectionTitle>
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {games.map((g) => <GameTile key={g.game_id} g={g} />)}
          </div>
        </section>
      ))}

      {finals.length > 0 && (
        <section>
          <SectionTitle icon={Trophy} tone="miel">Resultados</SectionTitle>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {finals.map((g) => <FinalTile key={g.game_id} g={g} />)}
          </div>
        </section>
      )}

      {pasadas.length > 0 && <PasadasChips weeks={pasadas} />}
    </div>
  );
}

/** Semanas anteriores: discretas, al final (la portada siempre es la semana actual). */
function PasadasChips({ weeks, sel }: { weeks: number[]; sel?: number }) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-dashed border-line pt-4">
      <span className="mr-1 font-hand text-[18px] font-semibold text-mute">semanas pasadas:</span>
      {weeks.map((w) => (
        <Link key={w} href={`/?semana=${w}`}
          className={clsx("rounded-full border px-3 py-1 text-xs font-bold transition-colors",
            sel === w ? "border-transparent bg-brand-fill text-on-brand" : "border-line bg-s1 text-ink2 hover:border-line-strong hover:text-ink")}>
          {w}
        </Link>
      ))}
    </div>
  );
}

function FinalTile({ g }: { g: GameCard }) {
  const hw = (g.home.score ?? 0) > (g.away.score ?? 0);
  return (
    <Link href={`/partido/${g.game_id}`} className="card card-lift flex items-center gap-3 px-3 py-2.5">
      <div className="flex-1 space-y-1">
        {[g.away, g.home].map((t, i) => {
          const won = i === 1 ? hw : !hw;
          return (
            <div key={t.abbr} className="flex items-center gap-2 text-sm">
              <TeamLogo team={t} size={18} />
              <span className={clsx("flex-1", won ? "font-semibold" : "text-mute")}>{t.nick}</span>
              <span className={clsx("tnum", won ? "font-bold" : "text-mute")}>{t.score}</span>
            </div>
          );
        })}
      </div>
      <span className="text-[10px] text-mute">{g.status_detail?.includes("OT") ? "Final TE" : "Final"}</span>
    </Link>
  );
}

function GameTile({ g }: { g: GameCard }) {
  const p = g.pred;
  const m = g.market;
  const done = g.status === "post";
  const showScore = g.status !== "pre";
  const mSpread = m.spread_home;
  return (
    <Link href={`/partido/${g.game_id}`} className="card card-lift group block p-4">
      <div className="mb-3 flex items-center justify-between text-xs text-mute">
        <span>{kickoffLabel(g.kickoff, false)}{g.broadcast ? ` · ${g.broadcast}` : ""}</span>
        <StatusPill status={g.status} detail={g.status_detail} period={g.period} clock={g.clock} />
      </div>
      {[g.away, g.home].map((t, i) => {
        const isHome = i === 1;
        const mu = p ? (isHome ? p.home_mu : p.away_mu) : null;
        const won = done && t.score != null && (isHome ? g.home.score! > g.away.score! : g.away.score! > g.home.score!);
        return (
          <div key={t.abbr} className="flex items-center gap-3 py-1.5">
            <TeamLogo team={t} size={30} />
            <div className="min-w-0 flex-1">
              <div className={clsx("truncate text-[15px]", won ? "font-bold" : "font-semibold")}>
                {t.nick ?? t.abbr} {isHome && <Home size={12} className="ml-0.5 inline text-mute" />}
              </div>
              <div className="text-xs text-mute">{t.record ?? ""}</div>
            </div>
            {showScore ? (
              <div className={clsx("text-2xl font-bold tnum", !won && done && "text-mute")}>{t.score}</div>
            ) : mu != null ? (
              <div className="text-right">
                <div className="text-lg font-semibold tnum">{num(mu, 1)}</div>
                <div className="text-[10px] text-mute">proyección</div>
              </div>
            ) : null}
          </div>
        );
      })}

      {p && !done && (
        <div className="mt-3">
          <WinBar left={g.away.abbr} right={g.home.abbr} pLeft={p.p_away + p.p_tie / 2} />
        </div>
      )}

      {!done && (
        <div className="mt-3 grid grid-cols-3 gap-2 rounded-xl bg-s2 px-3 py-2 text-xs">
          <div>
            <div className="text-mute">Hándicap</div>
            <div className="font-semibold tnum">{mSpread != null ? `${g.home.abbr} ${mSpread > 0 ? "-" : "+"}${Math.abs(mSpread)}` : "—"}</div>
            {p?.p_home_cover != null && <div className="text-mute tnum">cubre {pct(p.p_home_cover)}</div>}
          </div>
          <div>
            <div className="text-mute">Total</div>
            <div className="font-semibold tnum">{m.total ?? "—"}</div>
            {p && <div className="text-mute tnum">Cinna {num(p.total_mu, 1)}</div>}
          </div>
          <div>
            <div className="text-mute">Tiempo extra</div>
            <div className="font-semibold tnum">{p ? pct(p.p_ot, 1) : "—"}</div>
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        {g.weather && !g.indoor && (g.weather.wind_mph ?? 0) >= 12 && (
          <span className="inline-flex items-center gap-1 rounded-md bg-s2 px-2 py-0.5 text-ink2"><Wind size={12} /> {Math.round(g.weather.wind_mph!)} mph</span>
        )}
        {g.weather && !g.indoor && (g.weather.precip_prob ?? 0) >= 50 && (
          <span className="inline-flex items-center gap-1 rounded-md bg-s2 px-2 py-0.5 text-ink2"><CloudRain size={12} /> {Math.round(g.weather.precip_prob!)}%</span>
        )}
        {(g.injuries.home + g.injuries.away) > 0 && (
          <span className="rounded-md bg-s2 px-2 py-0.5 text-ink2">{g.injuries.away + g.injuries.home} bajas</span>
        )}
        {p?.starters?.home?.changed && <span className="rounded-md bg-serious-soft px-2 py-0.5 text-serious">QB nuevo en {g.home.abbr}</span>}
        {p?.starters?.away?.changed && <span className="rounded-md bg-serious-soft px-2 py-0.5 text-serious">QB nuevo en {g.away.abbr}</span>}
      </div>

      {g.top_pick && !done && (
        <div className="mt-3 flex items-center gap-2 border-t border-line pt-3 text-sm">
          <TierBadge tier={g.top_pick.tier} />
          <span className="min-w-0 flex-1 truncate text-ink2">{g.top_pick.title}</span>
          <span className="font-semibold tnum">{pct(g.top_pick.prob)}</span>
        </div>
      )}
    </Link>
  );
}
