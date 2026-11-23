"use client";

import { ArrowLeft, ArrowUpRight, CalendarBlank, Cards, ChartBar, FirstAidKit, Heartbeat, ListChecks, Newspaper, Target, Users } from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { useParams } from "next/navigation";
import { GameCard, Pick, Team, kickoffLabel, num, pct, useApi } from "@/lib/api";
import { COLS, RankPill } from "@/components/equipo-rank";
import { IconTile } from "@/components/icons";
import { NewsList } from "@/components/news-list";
import { PickCard } from "@/components/pick-card";
import { useTeams } from "@/components/teams";
import { Empty, Headshot, Loading, SectionTitle, TeamLogo, WinBar } from "@/components/ui";

type R = { value: number | null; rank: number };
type Resultado = { game_id: string; week: number; rival: string; local: boolean; pf: number; pa: number; res: "G" | "P" | "E";
  cubre: boolean | "push" | null; cinna: number | null; autopsia?: string | null };
type Jugador = { player_id: string; name: string; position: string; headshot?: string | null; snap?: number | null; p_td?: number | null;
  availability?: { p_play: number; status: string } | null;
  stats: { stat: string; label: string; med?: number | null; q?: number[] | null; linea?: number | null }[] };
type Equipo = {
  team: Team & { record: string; conf?: string; division?: string }; ranks: Record<string, R>; proximo: GameCard | null;
  resultados: Resultado[]; jugadores: Jugador[]; picks: Pick[];
  lesiones: { player_id: string; name: string; position: string; status: string; p_play: number; comment?: string }[];
  noticias: Parameters<typeof NewsList>[0]["items"];
};

const STAT_TXT: Record<string, string> = { pass_yds: "yds de pase", pass_tds: "TD de pase", rush_yds: "yds por tierra",
  rush_att: "acarreos", rec_yds: "yds de recepción", receptions: "recepciones" };

export default function EquipoPage() {
  const { abbr } = useParams<{ abbr: string }>();
  const { data, isLoading } = useApi<Equipo>(`/api/equipo/${abbr}`);
  const teams = useTeams();
  if (isLoading && !data) return <Loading label="Abriendo la ficha del equipo…" />;
  if (!data) return <Empty>Equipo no encontrado.</Empty>;
  const t = data.team, n = data.proximo;
  const net = data.ranks.net;
  const fuertes = COLS.filter((c) => c.key !== "net" && c.key !== "pace" && c.key !== "proe" && data.ranks[c.key])
    .sort((a, b) => data.ranks[a.key].rank - data.ranks[b.key].rank);
  const local = n ? n.home.abbr === t.abbr : false;
  const rival = n ? (local ? n.away : n.home) : null;
  const pGana = n?.pred ? (local ? n.pred.p_home + n.pred.p_tie / 2 : n.pred.p_away + n.pred.p_tie / 2) : null;

  return (
    <div className="space-y-6">
      <Link href="/equipos" className="inline-flex items-center gap-1 text-sm text-ink2 hover:text-ink"><ArrowLeft size={15} /> Equipos</Link>

      {/* ---------- encabezado ---------- */}
      <div className="card overflow-hidden">
        <div className="h-1.5" style={{ background: `linear-gradient(90deg, ${t.color ?? "var(--brand)"}, ${t.color2 ?? t.color ?? "var(--brand)"})` }} />
        <div className="flex flex-wrap items-center gap-5 px-5 py-6">
          <TeamLogo team={t} size={84} />
          <div className="min-w-0 flex-1">
            <div className="text-xs font-semibold uppercase tracking-wider text-mute">{t.division}</div>
            <h1 className="font-display text-3xl font-semibold leading-tight text-ink">{t.name}</h1>
            <div className="mt-1 text-sm text-ink2">Récord <b className="text-ink tnum">{t.record}</b>{net && <> · Poder <b className="text-ink tnum">{net.value != null && net.value > 0 ? "+" : ""}{num(net.value, 1)}</b> pts por partido</>}</div>
          </div>
          {net && (
            <div className="text-right">
              <div className="text-xs text-mute">Ranking de poder</div>
              <div className="font-display text-5xl font-semibold leading-none text-ink tnum">#{net.rank}</div>
              <div className="text-[11px] text-mute">de 32</div>
            </div>
          )}
        </div>
        <div className="grid gap-px border-t border-line bg-[var(--border)] sm:grid-cols-3 lg:grid-cols-7">
          {COLS.filter((c) => c.key !== "net").map((c) => {
            const r = data.ranks[c.key];
            return (
              <div key={c.key} className="bg-s1 px-4 py-3" title={c.hint}>
                <div className="text-[11px] uppercase tracking-wider text-mute">{c.label}</div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="font-semibold text-ink tnum">{r?.value == null ? "—" : c.fmt ? c.fmt(r.value) : r.value.toFixed(3)}</span>
                  {r && <RankPill rank={r.rank} />}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ---------- próximo partido ---------- */}
      {n && rival && (
        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
            <IconTile icon={CalendarBlank} tone="cielo" size={34} />
            <div className="flex-1">
              <div className="font-display text-base font-semibold text-ink">Próximo partido</div>
              <div className="text-xs text-mute">{n.status === "in" ? "En vivo" : kickoffLabel(n.kickoff)} · {n.venue}</div>
            </div>
            <Link href={`/partido/${n.game_id}`} className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-on-accent">
              Abrir partido <ArrowUpRight size={14} weight="bold" />
            </Link>
          </div>
          <div className="grid items-center gap-6 px-5 py-5 md:grid-cols-[1fr_auto_1fr]">
            <div className="flex items-center gap-3">
              <TeamLogo team={t} size={52} />
              <div><div className="font-display text-xl font-semibold text-ink">{t.nick}</div>
                {pGana != null && <div className="text-sm text-ink2"><b className="font-display text-2xl text-ink tnum">{pct(pGana)}</b> gana · proyecta {num(local ? n.pred?.home_mu : n.pred?.away_mu, 1)} pts</div>}</div>
            </div>
            <div className="text-center text-lg font-semibold text-mute">{local ? "vs" : "@"}</div>
            <Link href={`/equipos/${rival.abbr}`} className="flex items-center justify-end gap-3 text-right hover:opacity-80">
              <div><div className="font-display text-xl font-semibold text-ink">{rival.nick}</div>
                {pGana != null && <div className="text-sm text-ink2"><b className="font-display text-2xl text-ink tnum">{pct(1 - pGana)}</b> gana · proyecta {num(local ? n.pred?.away_mu : n.pred?.home_mu, 1)} pts</div>}</div>
              <TeamLogo team={rival} size={52} />
            </Link>
          </div>
          {pGana != null && <div className="px-5 pb-4"><WinBar left={t.abbr} right={rival.abbr} pLeft={pGana} height={10} /></div>}
          <div className="flex flex-wrap gap-2 border-t border-line bg-s2/50 px-5 py-3">
            {[
              { href: `/partido/${n.game_id}?tab=mercados`, label: "Mercados del partido", icon: ChartBar },
              { href: `/partido/${n.game_id}?tab=picks`, label: "Picks", icon: Target },
              { href: `/picks?partido=${n.game_id}`, label: "Súper pick", icon: Cards },
              { href: `/partido/${n.game_id}?tab=jugadores`, label: "Jugadores", icon: Users },
            ].map((b) => (
              <Link key={b.label} href={b.href} className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-s1 px-3 py-1.5 text-sm font-semibold text-ink2 hover:border-accent hover:text-ink">
                <b.icon size={15} weight="duotone" /> {b.label}
              </Link>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_1.15fr]">
        {/* ---------- fortalezas ---------- */}
        <section className="card min-w-0 p-5">
          <SectionTitle icon={Heartbeat} tone="rosa">En qué es bueno y en qué no</SectionTitle>
          <div className="space-y-3">
            {fuertes.map((c) => {
              const r = data.ranks[c.key];
              const w = (33 - r.rank) / 32;
              return (
                <div key={c.key}>
                  <div className="mb-1 flex items-baseline justify-between text-sm">
                    <span className="text-ink2">{c.label}</span>
                    <span className="flex items-center gap-2"><span className="text-xs text-mute tnum">{r.value == null ? "" : c.fmt ? c.fmt(r.value) : r.value.toFixed(3)}</span><RankPill rank={r.rank} /></span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-s3">
                    <div className="h-full rounded-full" style={{ width: `${w * 100}%`,
                      background: r.rank <= 8 ? "var(--good)" : r.rank >= 25 ? "var(--critical)" : "var(--accent)" }} />
                  </div>
                </div>
              );
            })}
          </div>
          <p className="mt-4 text-xs text-mute">Barra llena = de los mejores de la liga. Ajustado por la calidad de los rivales que ha enfrentado.</p>
        </section>

        {/* ---------- resultados ---------- */}
        <section className="card min-w-0 p-5">
          <SectionTitle icon={ListChecks} tone="cielo" right={<span className="text-xs text-mute">más reciente primero</span>}>Resultados de la temporada</SectionTitle>
          {data.resultados.length ? (
            <ul className="divide-y divide-[var(--border)]">
              {data.resultados.map((r) => {
                const rv = teams[r.rival] ?? { abbr: r.rival };
                return (
                  <li key={r.game_id}>
                    <Link href={`/partido/${r.game_id}`} className="flex items-center gap-3 py-2 hover:bg-s2/60">
                      <span className="w-12 text-[11px] text-mute">Sem {r.week}</span>
                      <span className={clsx("grid h-6 w-6 place-items-center rounded-md text-[11px] font-bold",
                        r.res === "G" ? "bg-good-soft text-good" : r.res === "P" ? "bg-[var(--critical)]/10 text-critical" : "bg-s2 text-ink2")}>{r.res}</span>
                      <span className="text-[11px] font-semibold text-mute">{r.local ? "vs" : "@"}</span>
                      <TeamLogo team={rv} size={22} />
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">{(rv as Team).nick ?? r.rival}</span>
                      <span className="font-semibold text-ink tnum">{r.pf}-{r.pa}</span>
                      <span className="hidden w-24 text-right text-[11px] text-mute sm:block">
                        {r.cubre === true ? "cubrió la línea" : r.cubre === false ? "no cubrió" : r.cubre === "push" ? "empate vs línea" : ""}
                      </span>
                      <span className="w-20 text-right text-[11px] text-mute" title="Lo que Cinna le daba antes del partido">
                        {r.cinna != null ? <>Cinna <b className={clsx("tnum", (r.cinna >= 0.5) === (r.res === "G") ? "text-good" : "text-ink2")}>{pct(r.cinna)}</b></> : ""}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : <p className="text-sm text-mute">Aún no juega esta temporada.</p>}
        </section>
      </div>

      {/* ---------- jugadores ---------- */}
      {data.jugadores.length > 0 && (
        <section>
          <SectionTitle icon={Users} tone="canela" right={<span className="text-xs text-mute">proyección para el próximo partido</span>}>Jugadores clave</SectionTitle>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {data.jugadores.map((p) => {
              const av = p.availability;
              return (
                <Link key={p.player_id} href={`/jugador/${p.player_id}`} className="card card-lift flex gap-3 p-4">
                  <Headshot src={p.headshot} name={p.name} size={48} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-semibold text-ink">{p.name}</span>
                      <span className="rounded bg-s2 px-1.5 text-[10px] font-semibold text-ink2">{p.position}</span>
                    </div>
                    {av && av.p_play < 0.95 && <div className="text-[11px] font-semibold text-warning">{av.status} · juega {pct(av.p_play)}</div>}
                    <ul className="mt-1.5 space-y-0.5 text-xs">
                      {p.stats.map((s) => (
                        <li key={s.stat} className="flex justify-between gap-2">
                          <span className="text-ink2">{STAT_TXT[s.stat] ?? s.label}</span>
                          <span className="tnum"><b className="text-ink">{num(s.med, s.stat === "pass_tds" || s.stat === "receptions" ? 1 : 0)}</b>
                            {s.q && s.q.length >= 5 && <span className="ml-1 text-mute">({num(s.q[0], 0)}–{num(s.q[4], 0)})</span>}</span>
                        </li>
                      ))}
                      {p.p_td != null && p.position !== "QB" && (
                        <li className="flex justify-between gap-2"><span className="text-ink2">anota TD</span><b className="text-ink tnum">{pct(p.p_td)}</b></li>
                      )}
                    </ul>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {/* ---------- picks ---------- */}
      {data.picks.length > 0 && (
        <section>
          <SectionTitle icon={Target} tone="rosa" right={n && <Link href={`/partido/${n.game_id}?tab=picks`} className="text-xs font-semibold text-accent hover:underline">ver todos</Link>}>
            Picks de su próximo partido</SectionTitle>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            {data.picks.slice(0, 6).map((p) => <PickCard key={p.pick_id} p={p} />)}
          </div>
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="min-w-0">
          <SectionTitle icon={FirstAidKit} tone="miel">Lesiones</SectionTitle>
          {data.lesiones.length ? (
            <div className="card divide-y divide-[var(--border)]">
              {data.lesiones.slice(0, 10).map((l) => (
                <div key={l.player_id} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-ink">{l.name} <span className="text-[11px] font-medium text-mute">{l.position}</span></div>
                    {l.comment && <div className="truncate text-[11px] text-mute">{l.comment}</div>}
                  </div>
                  <span className={clsx("rounded-full px-2 py-0.5 text-[11px] font-semibold",
                    l.p_play < 0.3 ? "bg-[var(--critical)]/10 text-critical" : l.p_play < 0.9 ? "bg-[var(--warning)]/15 text-warning" : "bg-s2 text-ink2")}>
                    {l.status} · {pct(l.p_play)}</span>
                </div>
              ))}
            </div>
          ) : <Empty mood="happy">Sin lesionados reportados.</Empty>}
          {data.lesiones.length > 10 && <p className="mt-2 text-xs text-mute">y {data.lesiones.length - 10} más en la lista de reserva.</p>}
        </section>
        <section className="min-w-0">
          <SectionTitle icon={Newspaper} tone="lila">Noticias</SectionTitle>
          <NewsList items={data.noticias} />
        </section>
      </div>
    </div>
  );
}
