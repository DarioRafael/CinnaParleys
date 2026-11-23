"use client";

import {
  Anchor, ArrowRight, Flask, Heartbeat, Info, Lightbulb, MapTrifold, Path, Prohibit, Shield, Strategy, Timer, TrendDown, UserMinus,
  Users,
} from "@phosphor-icons/react";
import clsx from "clsx";
import { Team, pct, useApi } from "@/lib/api";
import { IconTile, PIcon, Tone } from "./icons";
import { useTeams } from "./teams";
import { Headshot, Loading, SectionTitle, TeamLogo, WinBar } from "./ui";

type Unidad = { titulares: number; fuera: string[]; duda: string[] };
type Persona = { name: string; pos?: string; estado?: string; detalle?: string | null };
type Grupo = { grupo: string; nombre: string; titulares?: number | null; fuera: Persona[]; duda: Persona[] };
type Angulo = { angulo: string; evidencia: string; por_que: string; piernas_a_revisar?: string[]; tipo?: string; escenario?: string;
  prob?: string | number | null; marcador?: string | null; piernas?: string[]; headshot?: string | null; titulo?: string | null };
type Baja = { jugador: string; estado: string; prob_juega: string; detalle: string; name?: string; pos?: string; headshot?: string | null; p?: number };
type Absorbe = { jugador: string; sube: string; linea?: { stat: string; proyeccion: number; linea: number | null } | null; name?: string;
  pos?: string; headshot?: string | null; targets?: [number, number] | null; acarreos?: [number, number] | null };
type Camino = { situacion: string; prob_de_estar: number; gana_desde_ahi: number };
export type Informe = {
  partido: string; aviso?: string;
  lectura?: { favorito: string; prob_ganar: string; marcador_cerebro: string; total_cerebro: number; total_mercado: number | null;
    spread_mercado: string | null; cerebro_vs_mercado?: { margen_local_pts: number; total_pts: number | null };
    home?: string; away?: string; p_home?: number; p_away?: number; home_mu?: number; away_mu?: number;
    incertidumbre?: { nivel: string; razones: string[] } | null };
  unidades?: { equipos: Record<string, Record<string, Unidad> | string>; notas: string[]; ajuste_aplicado_pts: Record<string, number | null> };
  unidades_grid?: Record<string, Grupo[]>;
  bajas_ofensivas?: Record<string, Baja[]>;
  quien_absorbe_el_volumen?: Record<string, Absorbe[]>;
  qbs?: Record<string, { titular: string; prob_juega: string; motivo: string | null; p?: number; headshot?: string | null }>;
  plan_de_juego?: string[];
  picks_elite?: { pick: string; nivel: string; prob: string; mercado: string; momio: string | null }[];
  angulos_para_parlays?: Angulo[];
  como_leer?: string;
  caminos?: Record<string, Camino[]>;
  si_va_perdiendo_o_ganando_al_medio?: Record<string, string[]>;
};

const EVID: Record<string, { label: string; tone: Tone; icon: PIcon; txt: string }> = {
  validado: { label: "Validado", tone: "menta", icon: Anchor, txt: "Probado contra líneas reales en temporadas que el modelo no vio." },
  modelo: { label: "Modelo", tone: "cielo", icon: Flask, txt: "Sale de la proyección de Cinna: mejor calibrada que el mercado, pero sin garantía." },
  contexto: { label: "Contexto", tone: "miel", icon: Lightbulb, txt: "Tiene lógica, pero no pasó la prueba fuera de muestra: no lo apuestes solo." },
};
const TIPO: Record<string, { icon: PIcon; tone: Tone }> = {
  ancla: { icon: Anchor, tone: "menta" }, volumen: { icon: Users, tone: "cielo" }, evitar: { icon: Prohibit, tone: "rosa" },
  guion: { icon: Path, tone: "lila" }, secundaria: { icon: Shield, tone: "canela" }, linea: { icon: TrendDown, tone: "miel" },
};
const evidKey = (e: string) => (e.startsWith("validado") ? "validado" : e.startsWith("modelo") ? "modelo" : "contexto");
const tipoDe = (a: Angulo) => a.tipo ?? (a.angulo.startsWith("El pase de") ? "secundaria" : a.angulo.startsWith("Corredor de") ? "linea" : "volumen");

function Evid({ e }: { e: string }) {
  const v = EVID[evidKey(e)];
  return (
    <span title={v.txt} className={clsx("inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", `tone-${v.tone}`)}
      style={{ background: "var(--tb)", color: "var(--ti)" }}>
      <v.icon size={12} weight="fill" />{v.label}
    </span>
  );
}

/** Lectura rápida: quién gana, por cuánto y en qué no coincide Cinna con el mercado. */
function Lectura({ d, teams }: { d: Informe; teams: Record<string, Team> }) {
  const L = d.lectura!;
  const H = L.home ?? d.partido.split(" @ ")[1], A = L.away ?? d.partido.split(" @ ")[0];
  const th = teams[H] ?? ({ abbr: H } as Team), ta = teams[A] ?? ({ abbr: A } as Team);
  const pA = L.p_away != null && L.p_home != null ? L.p_away / (L.p_away + L.p_home) : null;
  const cvm = L.cerebro_vs_mercado;
  const lado = cvm ? (cvm.margen_local_pts >= 0 ? H : A) : null;
  return (
    <div className="card overflow-hidden">
      <div className="grid items-center gap-5 px-5 py-5 md:grid-cols-[1fr_auto_1fr]">
        {[{ t: ta, mu: L.away_mu, qb: d.qbs?.[A] }, null, { t: th, mu: L.home_mu, qb: d.qbs?.[H] }].map((x, i) => x === null ? (
          <div key="mid" className="text-center">
            <div className="text-[11px] uppercase tracking-wider text-mute">Cinna proyecta</div>
            <div className="font-display text-2xl font-semibold text-ink tnum">{L.away_mu ?? "—"} – {L.home_mu ?? "—"}</div>
            <div className="text-xs text-mute">línea {L.spread_mercado ?? "—"} · total {L.total_mercado ?? "—"}</div>
          </div>
        ) : (
          <div key={i} className={clsx("flex items-center gap-3", i === 2 && "md:flex-row-reverse md:text-right")}>
            <TeamLogo team={x.t} size={48} />
            <div className="min-w-0">
              <div className="font-display text-lg font-semibold text-ink">{x.t.nick ?? x.t.abbr}</div>
              {x.qb && (
                <div className={clsx("mt-1 flex items-center gap-2", i === 2 && "md:flex-row-reverse")}>
                  <Headshot src={x.qb.headshot} name={x.qb.titular} size={24} />
                  <span className="text-xs text-ink2">{x.qb.titular}
                    {x.qb.p != null && x.qb.p < 0.95 && <span className="ml-1 rounded-full bg-[var(--warning)]/15 px-1.5 font-semibold text-warning">juega {pct(x.qb.p)}</span>}</span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      {pA != null && <div className="px-5 pb-4"><WinBar left={A} right={H} pLeft={pA} height={10} /></div>}
      <div className="flex flex-wrap gap-2 border-t border-line bg-s2/50 px-5 py-3 text-xs">
        {cvm && (
          <span className="rounded-full bg-s1 px-2.5 py-1 text-ink2">
            {Math.abs(cvm.margen_local_pts) < 0.5 ? "Cinna coincide con la línea" : <>Cinna ve <b className="text-ink">{Math.abs(cvm.margen_local_pts)} pts más para {lado}</b> que la casa</>}
          </span>
        )}
        {cvm?.total_pts != null && (
          <span className="rounded-full bg-s1 px-2.5 py-1 text-ink2">
            {Math.abs(cvm.total_pts) < 0.5 ? "Total igual que la casa" : <>Cinna espera <b className="text-ink">{Math.abs(cvm.total_pts)} pts {cvm.total_pts > 0 ? "más" : "menos"}</b> que el total</>}
          </span>
        )}
        {L.incertidumbre && L.incertidumbre.nivel !== "normal" && (
          <span className="rounded-full bg-[var(--warning)]/15 px-2.5 py-1 font-semibold text-warning" title={L.incertidumbre.razones.join("\n")}>
            Incertidumbre {L.incertidumbre.nivel}: {L.incertidumbre.razones[0]}</span>
        )}
      </div>
    </div>
  );
}

const GR_TXT: Record<string, string> = { OL: "Línea ofensiva", DL: "Línea defensiva", LB: "Linebackers", CB: "Cornerbacks", S: "Safeties" };

/** Salud de las 5 unidades de cada equipo como semáforo, con los nombres de quien falta. */
function Unidades({ d, teams }: { d: Informe; teams: Record<string, Team> }) {
  const grid = d.unidades_grid ?? {};
  const adj = d.unidades?.ajuste_aplicado_pts ?? {};
  return (
    <section className="card p-5">
      <SectionTitle icon={Heartbeat} tone="rosa" right={<span className="text-xs text-mute">titulares fuera o en duda</span>}>Salud de cada unidad</SectionTitle>
      <div className="grid gap-5 md:grid-cols-2">
        {Object.entries(grid).map(([t, gs]) => (
          <div key={t}>
            <div className="mb-2 flex items-center gap-2">
              <TeamLogo team={teams[t] ?? { abbr: t }} size={24} />
              <span className="font-semibold text-ink">{teams[t]?.nick ?? t}</span>
              {adj[t] ? <span className="ml-auto rounded-full bg-good-soft px-2 py-0.5 text-[11px] font-semibold text-good">+{adj[t]!.toFixed(1)} pts por CB rival fuera</span> : null}
            </div>
            <div className="grid grid-cols-5 gap-1.5">
              {gs.map((g) => {
                const st = g.fuera.length ? "fuera" : g.duda.length ? "duda" : "ok";
                return (
                  <div key={g.grupo} title={GR_TXT[g.grupo] ?? g.nombre}
                    className={clsx("rounded-xl px-2 py-2 text-center",
                      st === "fuera" ? "bg-[var(--critical)]/10" : st === "duda" ? "bg-[var(--warning)]/12" : "bg-good-soft")}>
                    <div className={clsx("text-sm font-bold", st === "fuera" ? "text-critical" : st === "duda" ? "text-warning" : "text-good")}>{g.grupo}</div>
                    <div className="text-[10px] text-mute">{st === "fuera" ? `${g.fuera.length} fuera` : st === "duda" ? `${g.duda.length} en duda` : "completa"}</div>
                  </div>
                );
              })}
            </div>
            <ul className="mt-2 space-y-1">
              {gs.flatMap((g) => [...g.fuera.map((x) => ({ ...x, k: "fuera" })), ...g.duda.map((x) => ({ ...x, k: "duda" }))].map((x) => (
                <li key={`${g.grupo}|${x.name}`} className="flex items-center gap-2 text-xs">
                  <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", x.k === "fuera" ? "bg-[var(--critical)]" : "bg-[var(--warning)]")} />
                  <span className="text-ink"><b>{x.name}</b> <span className="text-mute">{x.pos}</span></span>
                  <span className="text-mute">{x.estado}{x.detalle ? ` · ${x.detalle}` : ""}</span>
                </li>
              )))}
            </ul>
          </div>
        ))}
      </div>
      {!!d.unidades?.notas.length && (
        <ul className="mt-4 space-y-1 border-t border-line pt-3 text-xs text-ink2">
          {d.unidades.notas.map((n) => <li key={n} className="flex gap-2"><Info size={14} className="mt-px shrink-0 text-accent" />{n}</li>)}
        </ul>
      )}
    </section>
  );
}

function Cuota({ label, de, a }: { label: string; de: number; a: number }) {
  const max = Math.max(a, de, 0.01);
  return (
    <div className="text-[11px]">
      <div className="flex justify-between text-mute"><span>{label}</span><span className="tnum"><b className="text-ink2">{pct(de)}</b> → <b className="text-good">{pct(a)}</b></span></div>
      <div className="relative mt-0.5 h-1.5 overflow-hidden rounded-full bg-s3">
        <div className="absolute inset-y-0 left-0 rounded-full bg-good/60" style={{ width: `${(a / max) * 100}%`, background: "var(--good)" }} />
        <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${(de / max) * 100}%`, background: "var(--neutral-bar)" }} />
      </div>
    </div>
  );
}

/** Quién falta en la ofensiva y a quién le toca su volumen. */
function Bajas({ d, teams }: { d: Informe; teams: Record<string, Team> }) {
  const equipos = Object.keys(d.bajas_ofensivas ?? {});
  return (
    <section className="card p-5">
      <SectionTitle icon={UserMinus} tone="miel">Bajas en la ofensiva y quién toma su lugar</SectionTitle>
      <div className="grid gap-6 md:grid-cols-2">
        {equipos.map((t) => {
          const bajas = d.bajas_ofensivas?.[t] ?? [];
          const abs = d.quien_absorbe_el_volumen?.[t] ?? [];
          return (
            <div key={t} className="space-y-3">
              <div className="flex items-center gap-2"><TeamLogo team={teams[t] ?? { abbr: t }} size={22} /><span className="font-semibold text-ink">{teams[t]?.nick ?? t}</span></div>
              {bajas.length ? bajas.map((b) => (
                <div key={b.jugador} className="flex items-start gap-3">
                  <Headshot src={b.headshot} name={b.name ?? b.jugador} size={34} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 text-sm"><b className="text-ink">{b.name ?? b.jugador}</b><span className="text-[11px] text-mute">{b.pos}</span>
                      <span className={clsx("rounded-full px-1.5 text-[11px] font-semibold", (b.p ?? 1) < 0.5 ? "bg-[var(--critical)]/10 text-critical" : "bg-[var(--warning)]/15 text-warning")}>
                        {b.estado} · juega {b.prob_juega}</span></div>
                    {b.detalle && <div className="line-clamp-2 text-[11px] text-mute">{b.detalle}</div>}
                  </div>
                </div>
              )) : <p className="text-sm text-mute">Sin bajas en la ofensiva.</p>}
              {abs.length > 0 && (
                <div className="rounded-xl bg-s2 p-3">
                  <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-mute"><ArrowRight size={12} weight="bold" />Le toca más juego a</div>
                  <div className="space-y-3">
                    {abs.map((x) => (
                      <div key={x.jugador} className="flex items-start gap-3">
                        <Headshot src={x.headshot} name={x.name ?? x.jugador} size={30} />
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="text-sm"><b className="text-ink">{x.name ?? x.jugador}</b> <span className="text-[11px] text-mute">{x.pos}</span></div>
                          {x.targets && <Cuota label="de los pases de su equipo" de={x.targets[0]} a={x.targets[1]} />}
                          {x.acarreos && <Cuota label="de los acarreos" de={x.acarreos[0]} a={x.acarreos[1]} />}
                          {x.linea && <div className="text-[11px] text-ink2">{x.linea.stat}: proyecta <b className="text-ink">{x.linea.proyeccion}</b> · línea {x.linea.linea ?? "aún sin línea"}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** Ideas para parlays, cada una con qué tan probada está. */
function Angulos({ d }: { d: Informe }) {
  const angs = d.angulos_para_parlays ?? [];
  if (!angs.length) return null;
  return (
    <section className="card p-5">
      <SectionTitle icon={Strategy} tone="lila">Ideas para parlays</SectionTitle>
      <div className="mb-4 grid gap-2 sm:grid-cols-3">
        {Object.entries(EVID).map(([k, v]) => (
          <div key={k} className="flex items-start gap-2 rounded-xl bg-s2 px-3 py-2 text-[11px] text-ink2"><Evid e={k} /><span>{v.txt}</span></div>
        ))}
      </div>
      <div className="grid grid-cols-1 items-start gap-3 lg:grid-cols-2">
        {angs.map((a, i) => {
          const T = TIPO[tipoDe(a)] ?? TIPO.volumen;
          return (
            <div key={i} className="flex gap-3 rounded-xl border border-line p-3">
              {a.headshot ? <Headshot src={a.headshot} name={a.titulo ?? a.angulo} size={38} /> : <IconTile icon={T.icon} tone={T.tone} size={38} />}
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm font-semibold leading-snug text-ink">
                    {a.tipo === "guion" ? <>Si el partido va por «{a.escenario}»{a.prob ? <span className="ml-1 font-normal text-mute">({typeof a.prob === "number" ? pct(a.prob) : a.prob} de las veces{a.marcador ? `, ${a.marcador}` : ""})</span> : null}</>
                      : a.tipo === "ancla" ? <>Pata ancla: {a.titulo}</> : a.angulo}
                  </div>
                  <Evid e={a.evidencia} />
                </div>
                {a.tipo === "guion" && a.piernas?.length ? (
                  <div className="flex flex-wrap gap-1.5">{a.piernas.map((p) => <span key={p} className="rounded-lg bg-s2 px-2 py-0.5 text-[11px] font-semibold text-ink2">{p}</span>)}</div>
                ) : null}
                <p className="text-xs text-mute">{a.por_que}</p>
                {a.piernas_a_revisar?.map((l) => <div key={l} className="flex gap-1.5 text-xs text-ink2"><ArrowRight size={12} className="mt-0.5 shrink-0" />{l}</div>)}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** Medio tiempo: qué tan seguido va así y cuánto gana desde ahí. */
function MedioTiempo({ c, teams }: { c: Record<string, Camino[]>; teams: Record<string, Team> }) {
  return (
    <section className="card p-5">
      <SectionTitle icon={Timer} tone="cielo" right={<span className="text-xs text-mute">al medio tiempo</span>}>¿Y si va perdiendo o ganando?</SectionTitle>
      <div className="grid gap-6 md:grid-cols-2">
        {Object.entries(c).map(([t, rows]) => (
          <div key={t}>
            <div className="mb-2 flex items-center gap-2"><TeamLogo team={teams[t] ?? { abbr: t }} size={22} /><span className="font-semibold text-ink">{teams[t]?.nick ?? t} al medio tiempo…</span></div>
            <div className="space-y-1.5">
              {rows.map((r) => (
                <div key={r.situacion} className="grid grid-cols-[1fr_44px_1fr] items-center gap-2 text-xs">
                  <span className="text-ink2">{r.situacion} <span className="text-mute">({pct(r.prob_de_estar)} de las veces)</span></span>
                  <span className={clsx("text-right font-semibold tnum", r.gana_desde_ahi >= 0.5 ? "text-good" : r.gana_desde_ahi < 0.25 ? "text-critical" : "text-ink")}>{pct(r.gana_desde_ahi)}</span>
                  <div className="h-2 overflow-hidden rounded-full bg-s3">
                    <div className="h-full rounded-full" style={{ width: `${r.gana_desde_ahi * 100}%`,
                      background: r.gana_desde_ahi >= 0.5 ? "var(--good)" : r.gana_desde_ahi < 0.25 ? "var(--critical)" : "var(--accent)" }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] text-mute">El porcentaje en verde es qué tan seguido gana desde esa situación (modelo en vivo con jugadas reales). Úsalo para decidir si cubrirte en vivo.</p>
    </section>
  );
}

export function InformePanel({ id }: { id: string }) {
  const { data, isLoading } = useApi<Informe>(`/api/informe/${id}`);
  const teams = useTeams();
  if (isLoading || !data) return <Loading label="Armando el informe…" />;
  if (data.aviso) return <div className="card p-5 text-sm text-mute">{data.aviso}</div>;
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3 rounded-2xl bg-s2 px-4 py-3 text-sm text-ink2">
        <Info size={18} className="mt-0.5 shrink-0 text-accent" />
        <p>Lo que un analista revisaría antes de apostar: quién llega mejor, quién falta y a quién le toca su juego, ideas para parlays
          (con qué tan probada está cada una) y qué pasa si el partido se tuerce al medio tiempo.</p>
      </div>
      {data.lectura && <Lectura d={data} teams={teams} />}
      {data.unidades_grid && <Unidades d={data} teams={teams} />}
      <Bajas d={data} teams={teams} />
      <Angulos d={data} />
      {data.caminos && Object.keys(data.caminos).length > 0 && <MedioTiempo c={data.caminos} teams={teams} />}
      {!!data.plan_de_juego?.length && (
        <section className="card p-5">
          <SectionTitle icon={MapTrifold} tone="canela" right={<span className="text-xs text-mute">descriptivo: no mueve las probabilidades</span>}>Plan de juego (esquema)</SectionTitle>
          <ul className="space-y-1.5 text-sm text-ink2">{data.plan_de_juego.map((x) => <li key={x} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-mute" />{x}</li>)}</ul>
        </section>
      )}
    </div>
  );
}
