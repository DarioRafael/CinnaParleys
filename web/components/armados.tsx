"use client";

import {
  ArrowClockwise, ArrowsClockwise, CaretDown, Info, ListChecks, Prohibit, SlidersHorizontal, Sparkle, WarningCircle,
} from "@phosphor-icons/react";
import clsx from "clsx";
import { Check, ImagePlus, Trash2 } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useMemo, useRef, useState } from "react";
import { mutate } from "swr";
import { GameCard, kickoffLabel, pct, post, useApi } from "@/lib/api";
import { CombinarPartidos, TiraPartidos } from "./partidos-picks";
import { Parlay, ParlayCard, Pata } from "./patas";
import { useTeams } from "./teams";
import { Empty, Loading, TeamLogo } from "./ui";

export type PataArmada = Pata;
export type ParlayArmado = Parlay & { variantes?: Parlay[] };
type Cambios = { desde?: string; nada?: boolean; salieron?: string[]; entraron?: string[]; momios?: string[] } | null;
export type PartidoArmado = {
  game_id: string; partido: string; kickoff: string; home?: string; away?: string; plan: string[]; parlays: ParlayArmado[];
  descartadas: { titulo: string; prob: number; por_que: string[] }[]; avisos?: string[]; n_patas_revisadas: number;
  cambios?: Cambios; jugadores?: string[]; hasta_donde?: Escalera[];
};
type Nivel = { nivel: "seguro" | "probable" | "posible" | "techo"; label: string; x: number; prob: number; dec?: number | null;
  precio_real?: boolean; fuente?: string; guion?: { guion: string; prob: number; pasa: number } | null };
type Escalera = { player_id: string; name: string; team: string; position: string; headshot?: string; label: string;
  proyeccion?: number | null; rango80?: number[] | null; rol?: string | null; duda?: string | null; niveles: Nivel[] };
const NIVEL_CLS: Record<Nivel["nivel"], string> = {
  seguro: "bg-good-soft text-good", probable: "bg-accent-soft text-accent",
  posible: "bg-[var(--warning)]/15 text-warning", techo: "bg-critical/12 text-critical",
};
export type ArmadosResp = {
  partidos: PartidoArmado[]; frescura?: { aviso?: string | null }; nota?: string; error?: string;
  record?: Record<string, { n: number; salieron: number; acierto: number; decia: number; retorno_por_peso: number }>;
};
type Prefs = { patas: number | null; pago: number | null; tipos: string[]; excluir: string[] };
const SIN_PREFS: Prefs = { patas: null, pago: null, tipos: [], excluir: [] };

function query(gameId: string | undefined, p: Prefs) {
  const q = new URLSearchParams();
  if (gameId) q.set("game_id", gameId);
  if (p.patas) q.set("patas", String(p.patas));
  if (p.pago) q.set("pago", String(p.pago));
  if (p.tipos.length) q.set("tipos", p.tipos.join(","));
  if (p.excluir.length) q.set("excluir", p.excluir.join(","));
  const s = q.toString();
  return `/api/armados${s ? `?${s}` : ""}`;
}

/** Armados con el botón «Volver a pensar» y el panel «A tu medida». Con gameId: un partido; sin él, la jornada. */
export function ArmadosConBoton({ gameId }: { gameId?: string }) {
  const [prefs, setPrefs] = useState<Prefs>(SIN_PREFS);
  const [abierto, setAbierto] = useState(false);
  const url = query(gameId, prefs);
  const { data, isLoading } = useApi<ArmadosResp>(url);
  const jugadores = useMemo(() => [...new Set((data?.partidos ?? []).flatMap((p) => p.jugadores ?? []))].sort(), [data]);
  const activo = !!(prefs.patas || prefs.pago || prefs.tipos.length || prefs.excluir.length);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Repensar gameId={gameId} />
        <button onClick={() => setAbierto((x) => !x)}
          className={clsx("inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-sm font-semibold",
            abierto || activo ? "border-accent bg-accent-soft text-accent" : "border-line text-ink2 hover:text-ink")}>
          <SlidersHorizontal size={16} weight="bold" /> A tu medida{activo ? " (activo)" : ""}
        </button>
        {activo && (
          <button onClick={() => setPrefs(SIN_PREFS)} className="text-xs font-semibold text-mute hover:text-ink">Quitar filtros</button>
        )}
      </div>
      {abierto && <PanelMedida prefs={prefs} setPrefs={setPrefs} jugadores={jugadores} />}
      <Armados data={data} isLoading={isLoading} solo={!!gameId} />
    </div>
  );
}

/** Trae lo último (lesiones, inactivos, noticias, líneas de Playdoit) y vuelve a armar todo. */
function Repensar({ gameId }: { gameId?: string }) {
  const [estado, setEstado] = useState<"listo" | "pensando" | "error">("listo");
  const [paso, setPaso] = useState<string | null>(null);
  const corriendo = useRef(false);

  async function pensar() {
    if (corriendo.current) return;
    corriendo.current = true;
    setEstado("pensando");
    setPaso("Guardando cómo estaban los armados…");
    try {
      const antes = (await (await fetch("/api/status")).json())?.last_refresh?.at as string | undefined;
      await post(`/api/armados/repensar${gameId ? `?game_id=${gameId}` : ""}`);
      for (let i = 0; i < 120; i++) {                       // hasta ~4 minutos
        await new Promise((r) => setTimeout(r, 2000));
        const s = await (await fetch("/api/status")).json();
        setPaso(s?.state?.running ? (s.state.step ?? "Actualizando…") : "Rearmando…");
        if (!s?.state?.running && s?.last_refresh?.at && s.last_refresh.at !== antes) break;
      }
      await mutate((k) => typeof k === "string" && (k.startsWith("/api/armados") || k.startsWith("/api/picks") || k.startsWith("/api/game")));
      setEstado("listo");
      setPaso(null);
    } catch {
      setEstado("error");
      setPaso("No pude actualizar. Revisa que la app esté prendida y vuelve a intentar.");
    } finally {
      corriendo.current = false;
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button onClick={pensar} disabled={estado === "pensando"}
        className="inline-flex items-center gap-2 rounded-xl bg-brand-fill px-4 py-2 text-sm font-bold text-on-brand shadow-sm disabled:opacity-70">
        {estado === "pensando" ? <ArrowsClockwise size={17} weight="bold" className="animate-spin" /> : <ArrowClockwise size={17} weight="bold" />}
        {estado === "pensando" ? "Pensando…" : "Volver a pensar"}
      </button>
      {paso && <span className={clsx("text-xs", estado === "error" ? "text-critical" : "text-ink2")}>{paso}</span>}
      {estado === "listo" && !paso && (
        <span className="text-xs text-mute">Trae lesiones, inactivos, noticias y las líneas de Playdoit, y vuelve a armar todo.</span>
      )}
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick}
      className={clsx("rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
        on ? "border-accent bg-accent text-on-accent" : "border-line bg-s1 text-ink2 hover:text-ink")}>
      {children}
    </button>
  );
}

function PanelMedida({ prefs, setPrefs, jugadores }: { prefs: Prefs; setPrefs: (p: Prefs) => void; jugadores: string[] }) {
  const [p, setP] = useState<Prefs>(prefs);
  const tipo = (t: string) => setP({ ...p, tipos: p.tipos.includes(t) ? p.tipos.filter((x) => x !== t) : [...p.tipos, t] });
  const fuera = (n: string) => setP({ ...p, excluir: p.excluir.includes(n) ? p.excluir.filter((x) => x !== n) : [...p.excluir, n] });
  return (
    <div className="card space-y-4 p-4">
      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-mute">Patas</div>
          <div className="flex flex-wrap gap-1.5">
            <Chip on={!p.patas} onClick={() => setP({ ...p, patas: null })}>Las que convengan</Chip>
            {[2, 3, 4, 5, 6].map((n) => <Chip key={n} on={p.patas === n} onClick={() => setP({ ...p, patas: n })}>{n}</Chip>)}
          </div>
        </div>
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-mute">Que pague al menos</div>
          <div className="flex flex-wrap gap-1.5">
            <Chip on={!p.pago} onClick={() => setP({ ...p, pago: null })}>Lo que sea</Chip>
            {[2, 3, 5, 8, 12].map((n) => <Chip key={n} on={p.pago === n} onClick={() => setP({ ...p, pago: n })}>{n}x</Chip>)}
          </div>
        </div>
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-mute">Con qué patas</div>
          <div className="flex flex-wrap gap-1.5">
            <Chip on={p.tipos.includes("jugadores")} onClick={() => tipo("jugadores")}>Jugadores</Chip>
            <Chip on={p.tipos.includes("partido")} onClick={() => tipo("partido")}>Del partido</Chip>
            <Chip on={p.tipos.includes("td")} onClick={() => tipo("td")}>Anota TD</Chip>
          </div>
          <div className="mt-1 text-[11px] text-mute">Sin marcar: jugadores y del partido. «Anota TD» sola se suma a esos dos.</div>
        </div>
      </div>
      {jugadores.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-mute">Sacar jugadores (toca para quitar)</div>
          <div className="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">
            {jugadores.map((n) => (
              <button key={n} onClick={() => fuera(n)}
                className={clsx("rounded-full border px-2.5 py-0.5 text-xs", p.excluir.includes(n)
                  ? "border-[var(--critical)] bg-[var(--critical)]/10 text-critical line-through" : "border-line text-ink2 hover:text-ink")}>{n}</button>
            ))}
          </div>
        </div>
      )}
      <div className="flex items-center gap-3 border-t border-line pt-3">
        <button onClick={() => setPrefs(p)} className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-on-accent">Armar así</button>
        <span className="text-xs text-mute">Aparece primero un perfil «A tu medida» con hasta 3 opciones. Los demás perfiles también quitan a los jugadores que saques.</span>
      </div>
    </div>
  );
}

/** Lista de partidos con sus armados. */
export function Armados({ gameId, data: dataProp, isLoading: loadingProp, solo }: {
  gameId?: string; data?: ArmadosResp; isLoading?: boolean; solo?: boolean;
}) {
  const propio = useApi<ArmadosResp>(dataProp === undefined && loadingProp === undefined ? query(gameId, SIN_PREFS) : null);
  const data = dataProp ?? propio.data;
  const isLoading = loadingProp ?? propio.isLoading;
  if (isLoading && !data) return <Loading label="Armando parlays partido por partido…" />;
  if (!data || data.error || !data.partidos.length) return <Empty>{data?.error ?? "Todavía no hay parlays armados para esta jornada."}</Empty>;
  return (
    <div className="space-y-8">
      {data.frescura?.aviso && (
        <div className="card flex items-start gap-2 px-4 py-3 text-sm text-warning">
          <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0" /> {data.frescura.aviso}
        </div>
      )}
      {data.partidos.map((p) => <PartidoArmados key={p.game_id} p={p} solo={solo ?? !!gameId} />)}
      {data.nota && (
        <p className="flex gap-2 text-xs text-mute"><Info size={15} className="mt-px shrink-0" />{data.nota}</p>
      )}
    </div>
  );
}

/** Un perfil con sus opciones: «Opción 1 · 2 · 3». */
function ConOpciones({ pz }: { pz: ParlayArmado }) {
  const ops = [pz, ...(pz.variantes ?? [])];
  const [i, setI] = useState(0);
  const actual = ops[Math.min(i, ops.length - 1)];
  return (
    <div className="space-y-1.5">
      {ops.length > 1 && (
        <div className="flex items-center gap-1 pl-1 text-[11px] font-semibold text-mute">
          {ops.map((o, k) => (
            <button key={k} onClick={() => setI(k)}
              className={clsx("rounded-lg px-2 py-0.5", k === i ? "bg-ink text-page" : "hover:bg-s2 hover:text-ink")}
              title={`${pct(o.prob_conjunta)} · ~${o.pago_estimado.toFixed(2)}x`}>
              Opción {k + 1}
            </button>
          ))}
        </div>
      )}
      <ParlayCard pz={actual} />
    </div>
  );
}

function QueCambio({ c }: { c: NonNullable<Cambios> }) {
  if (c.nada) {
    return <div className="flex items-center gap-2 rounded-xl bg-s2 px-3 py-2 text-xs text-ink2"><Check size={14} className="text-good" /> Nada cambió desde la última vez: las mismas patas y los mismos momios.</div>;
  }
  return (
    <div className="card space-y-2 p-4 text-xs">
      <div className="flex items-center gap-2 text-sm font-semibold text-ink"><Sparkle size={16} weight="fill" className="text-brand" />Qué cambió desde la última vez</div>
      {!!c.salieron?.length && <ul className="space-y-0.5">{c.salieron.map((t) => <li key={t} className="flex gap-1.5 text-ink2"><Prohibit size={13} className="mt-px shrink-0 text-critical" />Salió: {t}</li>)}</ul>}
      {!!c.momios?.length && <ul className="space-y-0.5">{c.momios.map((t) => <li key={t} className="flex gap-1.5 text-ink2"><ArrowsClockwise size={13} className="mt-px shrink-0 text-accent" />{t}</li>)}</ul>}
      {!!c.entraron?.length && <ul className="space-y-0.5">{c.entraron.map((t) => <li key={t} className="flex gap-1.5 text-ink2"><Check size={13} className="mt-px shrink-0 text-good" />Entró: {t}</li>)}</ul>}
    </div>
  );
}

function PartidoArmados({ p, solo }: { p: PartidoArmado; solo: boolean }) {
  const [plan, setPlan] = useState(false);
  const teams = useTeams();
  const [away, home] = [p.away ?? p.partido.split(" @ ")[0], p.home ?? p.partido.split(" @ ")[1]];
  return (
    <section className="space-y-4">
      {!solo && (
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5">
            <TeamLogo team={teams[away] ?? { abbr: away }} size={30} />
            <span className="text-xs font-semibold text-mute">@</span>
            <TeamLogo team={teams[home] ?? { abbr: home }} size={30} />
          </div>
          <Link href={`/partido/${p.game_id}`} className="font-display text-lg font-semibold text-ink hover:text-accent">
            {teams[away]?.nick ?? away} @ {teams[home]?.nick ?? home}
          </Link>
          <span className="text-xs text-mute">{kickoffLabel(p.kickoff)} · {p.n_patas_revisadas} patas revisadas</span>
        </div>
      )}
      {p.cambios && <QueCambio c={p.cambios} />}
      {(p.avisos ?? []).map((a, i) => (
        <div key={i} className="flex items-start gap-2 rounded-xl bg-s2 px-3 py-2 text-xs text-ink2">
          <Info size={15} className="mt-px shrink-0 text-accent" /> {a}
        </div>
      ))}
      {(p.hasta_donde ?? []).length > 0 && <HastaDonde lista={p.hasta_donde!} />}
      {p.parlays.length ? (
        <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {p.parlays.map((pz) => <ConOpciones key={pz.perfil} pz={pz} />)}
        </div>
      ) : <Empty>Sin parlays que cumplan los filtros en este partido.</Empty>}
      <button onClick={() => setPlan((x) => !x)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-semibold text-ink2 hover:bg-s2 hover:text-ink">
        <CaretDown size={14} className={clsx("transition-transform", plan && "rotate-180")} /> Plan de juego y patas descartadas
      </button>
      {plan && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink"><ListChecks size={18} className="text-accent" />Plan de juego</div>
            <ul className="space-y-1.5 text-sm text-ink2">{p.plan.map((x, i) => <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-mute" />{x}</li>)}</ul>
          </div>
          <div className="card p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink"><Prohibit size={18} className="text-critical" />Patas descartadas</div>
            {p.descartadas.length ? (
              <ul className="space-y-2">
                {p.descartadas.map((d) => (
                  <li key={d.titulo} className="text-xs">
                    <div className="flex justify-between gap-2"><b className="text-ink">{d.titulo}</b><span className="tnum text-mute">{pct(d.prob)}</span></div>
                    <div className="text-ink2">{d.por_que.join(" · ")}</div>
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-mute">Ninguna pata quedó en rojo.</p>}
          </div>
        </div>
      )}
    </section>
  );
}

/** Juntar varios partidos en un solo armado (la misma herramienta que en Picks). */
export function JuntarPartidos() {
  const { data: wk } = useApi<{ games: GameCard[] }>("/api/week");
  const juegos = useMemo(() => (wk?.games ?? []).filter((g) => g.status === "pre"), [wk]);
  const [sel, setSel] = useState<string[]>([]);
  if (!juegos.length) return null;
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="font-display text-[17px] font-bold tracking-tight text-ink">Juntar varios partidos</h2>
        <span className="text-xs text-mute">Elige 2 o más y te armo el súper pick entre ellos.</span>
      </div>
      <TiraPartidos juegos={juegos} sel={sel} onToggle={(id) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))} />
      {sel.length > 0 && <CombinarPartidos sel={sel} juegos={juegos} onClear={() => setSel([])} />}
    </section>
  );
}

// ---------------------------------------------------------------- líneas de tu casa (captura o texto)
type Linea = { clave: string; game_id: string; name: string; stat: string; label?: string; casa: string; at: string;
  escalones: Record<string, number | null>; ou: { line?: number; over?: number | null; under?: number | null } };
type LineasResp = { lineas: Linea[]; patron: Record<string, { capturas: number; acierta_exacto: number; error_medio: number; ajuste_aplicado: number }> };

/** Cargar los mercados reales de Playdoit/Draftea: captura de la lista de escalones o texto pegado. */
export function LineasCasa() {
  const { data } = useApi<LineasResp>("/api/lineas-casa");
  const [casa, setCasa] = useState("Playdoit");
  const [texto, setTexto] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: string[]; avisos: string[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const listo = (d: { guardados?: string[]; avisos?: string[] }) => {
    setMsg({ ok: d.guardados ?? [], avisos: d.avisos ?? [] });
    mutate("/api/lineas-casa");
    mutate((k) => typeof k === "string" && k.startsWith("/api/armados"));
  };
  const subir = async (b: Blob) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await fetch(`/api/lineas-casa/escanear?casa=${casa}`, { method: "POST", body: b, headers: { "Content-Type": b.type || "image/png" } });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? "No se pudo leer la captura.");
      listo(await r.json());
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const guardarTexto = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try { listo(await post("/api/lineas-casa/texto", { texto, casa })); setTexto(""); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const borrar = async (clave?: string) => {
    await fetch(`/api/lineas-casa${clave ? `?clave=${encodeURIComponent(clave)}` : ""}`, { method: "DELETE" });
    mutate("/api/lineas-casa");
    mutate((k) => typeof k === "string" && k.startsWith("/api/armados"));
  };
  const lineas = data?.lineas ?? [];

  return (
    <div className="card space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-display text-base font-semibold">Líneas de tu casa</div>
        <select value={casa} onChange={(e) => setCasa(e.target.value)} className="rounded-lg border border-line bg-s1 px-2 py-1 text-xs">
          <option>Playdoit</option><option>Draftea</option><option>Caliente</option>
        </select>
        <span className="text-xs text-mute">{lineas.length} mercados guardados</span>
        {lineas.length > 0 && (
          <button onClick={() => borrar()} className="ml-auto inline-flex items-center gap-1 text-xs text-mute hover:text-critical">
            <Trash2 size={13} /> Borrar todas
          </button>
        )}
      </div>
      <p className="text-xs text-ink2">
        Para Draftea u otra casa (Playdoit ya llega solo con la extensión): toma captura de la lista de escalones de un jugador
        (con su nombre y la estadística visibles) o pega el texto, y los armados usan esos números y momios.
      </p>
      <div className="flex flex-wrap gap-2">
        <button disabled={busy} onClick={() => file.current?.click()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand-fill px-3 py-2 text-xs font-bold text-on-brand disabled:opacity-60">
          <ImagePlus size={15} /> {busy ? "Leyendo…" : "Subir captura de mercados"}
        </button>
        <input ref={file} type="file" accept="image/*" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) subir(f); e.target.value = ""; }} />
      </div>
      <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={3}
        placeholder={"James Cook yds por tierra 55+ 1.25, 65+ 1.45, 75+ 1.80\nHockenson recepciones Más de 4.5 1.95 Menos de 4.5 1.80"}
        className="w-full rounded-lg border border-line bg-s1 px-3 py-2 text-xs outline-none focus:border-accent" />
      {texto.trim() && (
        <button disabled={busy} onClick={guardarTexto} className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold hover:border-accent">
          Guardar texto
        </button>
      )}
      {err && <p className="text-xs text-critical">{err}</p>}
      {msg && (
        <div className="space-y-1 text-xs">
          {msg.ok.map((x) => <div key={x} className="flex items-center gap-1 text-good"><Check size={12} /> {x}</div>)}
          {msg.avisos.map((x) => <div key={x} className="text-warning">{x}</div>)}
        </div>
      )}
      {lineas.length > 0 && (
        <ul className="max-h-48 space-y-1 overflow-y-auto text-xs">
          {lineas.map((l) => (
            <li key={l.clave} className="flex items-center gap-2 rounded bg-s2 px-2 py-1">
              <span className="min-w-0 flex-1 truncate">
                <b>{l.name}</b> · {l.label ?? l.stat} · {Object.keys(l.escalones).sort((a, b) => +a - +b).map((x) => `${x}+`).join(" ")}
                {l.ou.line != null ? ` · Más/Menos ${l.ou.line}` : ""} <span className="text-mute">({l.casa})</span>
              </span>
              <button onClick={() => borrar(l.clave)} className="text-mute hover:text-critical"><Trash2 size={12} /></button>
            </li>
          ))}
        </ul>
      )}
      {data?.patron && Object.keys(data.patron).length > 0 && (
        <div className="text-[11px] text-mute">
          Qué tanto atinaba el mínimo estimado: {Object.entries(data.patron).map(([k, v]) =>
            `${k}: exacto ${pct(v.acierta_exacto)} de ${v.capturas}${v.ajuste_aplicado ? ` (ajuste ${v.ajuste_aplicado > 0 ? "+" : ""}${v.ajuste_aplicado})` : ""}`).join(" · ")}
        </div>
      )}
    </div>
  );
}

/** Por jugador clave: hasta dónde es seguro, qué es probable, qué es posible y qué es arriesgado (y en qué guion pasa). */
function HastaDonde({ lista }: { lista: Escalera[] }) {
  const [abierto, setAbierto] = useState(true);
  return (
    <div className="card p-4">
      <button onClick={() => setAbierto((x) => !x)} className="flex w-full items-center gap-2 text-left">
        <ListChecks size={18} className="text-accent" />
        <span className="font-display text-base font-semibold">Hasta dónde llega cada jugador</span>
        <CaretDown size={14} className={clsx("ml-auto transition-transform", abierto && "rotate-180")} />
      </button>
      <p className="mt-1 text-xs text-mute">
        Los escalones de la casa en cuatro niveles. Lo alto no es imposible: dice en qué guion del partido sube.
      </p>
      {abierto && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {lista.map((e) => (
            <div key={e.player_id} className="rounded-xl border border-line p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-semibold">{e.name} <span className="text-xs font-normal text-mute">{e.team} · {e.label}</span></span>
                {e.proyeccion != null && <span className="text-xs text-mute tnum">proyecta {Math.round(e.proyeccion)}</span>}
              </div>
              {e.duda && (
                <div className="mt-1 flex items-center gap-1 text-[11px] text-warning"><WarningCircle size={13} /> {e.duda}</div>
              )}
              <div className="mt-2 space-y-1.5">
                {e.niveles.map((n) => (
                  <div key={n.nivel} className="text-xs">
                    <div className="flex items-center gap-2">
                      <span className={clsx("w-[150px] shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold", NIVEL_CLS[n.nivel])}>{n.label}</span>
                      <b className="tnum">{n.x}+</b>
                      <span className="tnum text-ink2">{pct(n.prob)}</span>
                      {n.dec ? <span className="ml-auto tnum text-mute">{n.precio_real ? "" : "~"}{n.dec.toFixed(2)}x</span> : null}
                    </div>
                    {n.guion && (
                      <div className="ml-[158px] text-[11px] text-ink2">sube a <b>{pct(n.guion.prob)}</b> si {n.guion.guion} (pasa {pct(n.guion.pasa)})</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
