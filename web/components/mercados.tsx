"use client";

import { Calculator, ChartBar, CheckCircle, DiceFive, Football, Ruler, Scales, ShieldCheck, SneakerMove, Target, Timer } from "@phosphor-icons/react";
import clsx from "clsx";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Team, ago, american, pct, useApi } from "@/lib/api";
import { IconTile, PIcon, Tone } from "./icons";
import { Segmented, TeamLogo } from "./ui";

/* Mercados del partido que salen de la simulación: puntos (cualquier línea), touchdowns, goles de campo, pateadores,
   primera mitad, margen de victoria y tiempo extra. Cada uno con su aproximado y su veredicto de validación. */

type Linea = { linea: number; p_mas: number; p_menos: number; momio_mas?: number | null; momio_menos?: number | null;
  ve_mas?: number | null; ve_menos?: number | null; principal: boolean };
type Seguro = { nivel: number | null; linea: number; p: number };
type Opcion = { nombre: string; equipo?: string; p: number; momio?: number | null; ve?: number | null };
type Aprox = { media: number; mediana: number; moda?: number; p10: number; p90: number };
type Mercado = {
  clave: string; titulo: string; equipo?: string | null; familia: string; unidad?: string; veredicto: string; nota: string;
  aprox?: Aprox | null; dist?: { x: number; p: number }[]; lineas?: Linea[]; cierre?: number | null;
  seguros?: { menos: Seguro[]; mas: Seguro[] }; opciones?: Opcion[]; lineas_reales?: boolean;
};
type Grupo = { grupo: string; icono: string; mercados: Mercado[] };
export type MercadosData = {
  partidos_validacion?: number | null; con_momios: boolean; grupos: Grupo[];
  playdoit_pausa?: { desde?: string; horas_restantes?: number; activa?: boolean } | null;
  importado?: { casa?: string; at?: string } | null;
};
type Calc = { linea: number; p_mas: number; p_menos: number; p_exacto: number; justo_mas: number | null; justo_menos: number | null };

const VEREDICTO: Record<string, { label: string; tone: Tone; icon: PIcon; corto: string }> = {
  fiable: { label: "Fiable", tone: "menta", icon: ShieldCheck, corto: "predice mejor que el promedio de la liga" },
  aceptable: { label: "Aceptable", tone: "cielo", icon: CheckCircle, corto: "algo mejor que el promedio; orientación" },
  "igual que la casa": { label: "Igual que la casa", tone: "miel", icon: Scales, corto: "bien calibrado, sin ventaja contra la línea" },
  "casi azar": { label: "Casi azar", tone: "lila", icon: DiceFive, corto: "casi no depende del partido" },
};
const ICONO: Record<string, { icon: PIcon; tone: Tone }> = {
  puntos: { icon: ChartBar, tone: "cielo" }, td: { icon: Football, tone: "canela" }, fg: { icon: Target, tone: "menta" },
  pateador: { icon: SneakerMove, tone: "miel" }, h1: { icon: Timer, tone: "lila" }, margen: { icon: Ruler, tone: "rosa" },
};

const n1 = (x: number) => (Number.isInteger(x) ? `${x}` : x.toFixed(1));
const justo = (p: number) => (p <= 0 || p >= 1 ? null : p >= 0.5 ? Math.round((-100 * p) / (1 - p)) : Math.round((100 * (1 - p)) / p));
const aDecimal = (o: number) => (o > 0 ? 1 + o / 100 : 1 + 100 / Math.abs(o));

function Veredicto({ v }: { v: string }) {
  const d = VEREDICTO[v] ?? VEREDICTO.aceptable;
  return (
    <span className={clsx("inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", `tone-${d.tone}`)}
      style={{ background: "var(--tb)", color: "var(--ti)" }} title={d.corto}>
      <d.icon size={12} weight="fill" aria-hidden="true" />{d.label}
    </span>
  );
}

function Ve({ ve }: { ve?: number | null }) {
  if (ve == null) return null;
  return (
    <span className={clsx("rounded px-1 text-[10px] font-semibold tnum", ve >= 0.02 ? "bg-good-soft text-good" : "bg-s3 text-mute")}>
      {ve > 0 ? "+" : ""}{(ve * 100).toFixed(0)}%
    </span>
  );
}

/** Lo que Cinna espera: el número grande, lo más probable y el rango normal. */
function Aproximado({ a, unidad }: { a: Aprox; unidad?: string }) {
  return (
    <div className="flex items-end justify-between gap-3">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wide text-mute">Cinna espera</div>
        <div className="font-display text-3xl font-semibold leading-none tracking-tight text-ink tnum">
          ≈ {n1(a.media)}{unidad ? <span className="ml-1 text-base font-medium text-ink2">{unidad}</span> : null}
        </div>
      </div>
      <div className="text-right text-xs text-ink2">
        {a.moda != null && <div>Lo más probable: <b className="text-ink tnum">{a.moda}</b></div>}
        <div>Lo normal (8 de cada 10): <b className="text-ink tnum">{n1(a.p10)} a {n1(a.p90)}</b></div>
      </div>
    </div>
  );
}

/** Distribución de un conteo (touchdowns, goles de campo…): una barra por resultado exacto. */
function Distribucion({ dist, moda }: { dist: { x: number; p: number }[]; moda?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...dist.map((d) => d.p), 0.01);
  const sel = dist.find((d) => d.x === (hover ?? moda));
  return (
    <div>
      <div className="mb-1 h-4 text-[11px] text-ink2 tnum">
        {sel && <>Exactamente <b className="text-ink">{sel.x}</b>: <b className="text-ink">{pct(sel.p, 0)}</b></>}
      </div>
      <div className="flex h-16 items-end gap-0.5" onMouseLeave={() => setHover(null)}>
        {dist.map((d) => (
          <div key={d.x} className="flex h-full min-w-0 flex-1 cursor-default items-end" onMouseEnter={() => setHover(d.x)}
            title={`Exactamente ${d.x}: ${pct(d.p, 0)}`}>
            <div className={clsx("w-full rounded-t transition-opacity", d.x === (hover ?? moda) ? "bg-accent" : "bg-accent/40")}
              style={{ height: `${Math.max(3, (d.p / max) * 100)}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-0.5 border-t border-line pt-1 text-center text-[10px] text-mute tnum">
        {dist.map((d) => <div key={d.x} className="min-w-0 flex-1">{d.x}</div>)}
      </div>
    </div>
  );
}

function Lado({ p, momio, ve }: { p: number; momio?: number | null; ve?: number | null }) {
  const j = justo(p);
  return (
    <div className="flex items-baseline justify-end gap-1.5">
      <span className={clsx("font-semibold tnum", p >= 0.7 ? "text-good" : p >= 0.5 ? "text-ink" : "text-mute")}>{pct(p, 0)}</span>
      <span className="w-11 text-right text-[11px] text-mute tnum" title="Momio justo: si te pagan mejor que esto, hay valor">{american(j)}</span>
      {momio != null && <span className="text-[11px] font-semibold text-ink2 tnum" title="Momio de Playdoit">{american(momio)}</span>}
      <Ve ve={ve} />
    </div>
  );
}

function Lineas({ lineas }: { lineas: Linea[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <div className="grid grid-cols-[4.5rem_1fr_1fr] gap-2 bg-s2 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-mute">
        <div>Línea</div><div className="text-right">Más de</div><div className="text-right">Menos de</div>
      </div>
      {lineas.map((l) => (
        <div key={l.linea} className={clsx("grid grid-cols-[4.5rem_1fr_1fr] items-baseline gap-2 border-t border-line px-3 py-1.5 text-sm",
          l.principal && "bg-brand-soft/40")}>
          <div className="font-semibold tnum text-ink">{n1(l.linea)}{l.principal && <span className="ml-1 text-[10px] font-medium text-mute">casa</span>}</div>
          <Lado p={l.p_mas} momio={l.momio_mas} ve={l.ve_mas} />
          <Lado p={l.p_menos} momio={l.momio_menos} ve={l.ve_menos} />
        </div>
      ))}
    </div>
  );
}

/** «¿Menos de cuántos puntos?»: la línea más ajustada para cada nivel de seguridad. */
function Seguros({ s }: { s: { menos: Seguro[]; mas: Seguro[] } }) {
  const col = (titulo: string, palabra: string, filas: Seguro[]) => (
    <div className="min-w-0 flex-1">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-mute">{titulo}</div>
      <ul className="space-y-1">
        {filas.map((f) => (
          <li key={f.linea} className="flex items-baseline justify-between gap-2 text-sm">
            <span className="whitespace-nowrap text-ink2">{palabra} <b className="text-ink tnum">{n1(f.linea)}</b></span>
            <span className={clsx("font-semibold tnum", f.p >= 0.8 ? "text-good" : "text-ink")}>{pct(f.p, 0)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
  return (
    <div className="rounded-xl bg-s2 p-3">
      <div className="flex flex-wrap gap-x-5 gap-y-3">
        {col("Se queda corto", "Menos de", s.menos)}
        {col("Seguro pasa", "Más de", s.mas)}
      </div>
    </div>
  );
}

/** Cualquier línea que veas en tu casa: probabilidad, momio justo y, si escribes lo que te pagan, si conviene. */
function Calculadora({ gameId, clave, veredicto }: { gameId: string; clave: string; veredicto: string }) {
  const sinVentaja = veredicto === "casi azar" || veredicto === "igual que la casa";
  const [txt, setTxt] = useState("");
  const [linea, setLinea] = useState<number | null>(null);
  const [lado, setLado] = useState<"mas" | "menos">("mas");
  const [momioTxt, setMomioTxt] = useState("");
  useEffect(() => {
    const t = setTimeout(() => {
      const v = parseFloat(txt.replace(",", "."));
      setLinea(Number.isFinite(v) && v >= 0 && v <= 150 ? v : null);
    }, 350);
    return () => clearTimeout(t);
  }, [txt]);
  const { data, error } = useApi<Calc>(linea != null ? `/api/mercados/${gameId}/calc?clave=${clave}&linea=${linea}` : null);
  const p = data ? (lado === "mas" ? data.p_mas : data.p_menos) : null;
  const j = data ? (lado === "mas" ? data.justo_mas : data.justo_menos) : null;
  const momio = parseFloat(momioTxt.replace("+", ""));
  const hayMomio = Number.isFinite(momio) && Math.abs(momio) >= 100;
  const ve = p != null && hayMomio ? p * aDecimal(momio) - 1 : null;
  const input = "h-8 w-full rounded-lg border border-line bg-s1 px-2 text-sm text-ink outline-none tnum focus:border-accent";
  return (
    <div className="rounded-xl border border-dashed border-line p-3">
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-mute">
        <Calculator size={14} weight="duotone" aria-hidden="true" />¿Otra línea en tu casa?
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <input className={input} inputMode="decimal" placeholder="línea, ej. 4.5" value={txt} onChange={(e) => setTxt(e.target.value)}
          aria-label="Línea" />
        <div className="inline-flex rounded-lg border border-line bg-s2 p-0.5 text-xs font-semibold">
          {(["mas", "menos"] as const).map((l) => (
            <button key={l} onClick={() => setLado(l)}
              className={clsx("rounded-md px-2 py-1", lado === l ? "bg-s1 text-ink shadow-sm" : "text-ink2 hover:text-ink")}>
              {l === "mas" ? "Más" : "Menos"}
            </button>
          ))}
        </div>
        <input className={input} inputMode="numeric" placeholder="te pagan, ej. -120" value={momioTxt}
          onChange={(e) => setMomioTxt(e.target.value.replace(/[^0-9+-]/g, ""))} aria-label="Momio que te pagan (opcional)" />
      </div>
      {error && linea != null && <div className="mt-2 text-xs text-mute">No pude calcular esa línea.</div>}
      {data && p != null && linea != null && (
        <div className="mt-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
          <span className="text-ink2">{lado === "mas" ? "Más" : "Menos"} de <b className="text-ink tnum">{n1(linea)}</b></span>
          <span><b className={clsx("text-base tnum", p >= 0.7 ? "text-good" : "text-ink")}>{pct(p, 0)}</b>
            <span className="ml-2 text-xs text-mute">justo <span className="tnum">{american(j)}</span></span></span>
          {ve != null && (
            <span className={clsx("w-full text-xs font-semibold", ve >= 0.02 && !sinVentaja ? "text-good" : "text-ink2")}>
              {ve >= 0.02 && sinVentaja
                ? `Paga mejor que el justo de Cinna (+${(ve * 100).toFixed(0)}%), pero en este mercado Cinna no le gana a la casa: no lo tomes como ventaja.`
                : ve >= 0.02 ? `Te pagan mejor que el justo: valor esperado +${(ve * 100).toFixed(0)}%`
                : ve > -0.02 ? "Te pagan casi lo justo: sin ventaja" : `Te pagan menos que el justo: valor esperado ${(ve * 100).toFixed(0)}%`}
            </span>
          )}
          {data.p_exacto > 0.001 && <span className="w-full text-[11px] text-mute">Cae exacto en {n1(linea)} (se devuelve): {pct(data.p_exacto, 0)}</span>}
        </div>
      )}
    </div>
  );
}

function Opciones({ ops }: { ops: Opcion[] }) {
  const max = Math.max(...ops.map((o) => o.p), 0.01);
  return (
    <ul className="space-y-2">
      {ops.map((o) => (
        <li key={o.nombre}>
          <div className="flex items-baseline justify-between gap-2 text-sm">
            <span className="min-w-0 truncate text-ink2">{o.nombre}</span>
            <span className="flex shrink-0 items-baseline gap-1.5">
              <b className="tnum text-ink">{pct(o.p, 0)}</b>
              <span className="w-11 text-right text-[11px] text-mute tnum" title="Momio justo">{american(justo(o.p))}</span>
              {o.momio != null && <span className="text-[11px] font-semibold text-ink2 tnum" title="Momio de Playdoit">{american(o.momio)}</span>}
              <Ve ve={o.ve} />
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-s3">
            <div className="h-full rounded-full bg-accent/70" style={{ width: `${(o.p / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Tarjeta({ m, gameId, teams }: { m: Mercado; gameId: string; teams: Record<string, Partial<Team>> }) {
  const esConteo = !!m.dist?.length;
  return (
    <div className="card flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {m.equipo && teams[m.equipo] && <TeamLogo team={teams[m.equipo]} size={24} />}
          <h3 className="min-w-0 text-[15px] font-semibold leading-tight text-ink">{m.titulo}</h3>
        </div>
        <Veredicto v={m.veredicto} />
      </div>
      {m.aprox && <Aproximado a={m.aprox} unidad={m.unidad} />}
      {esConteo && <Distribucion dist={m.dist!} moda={m.aprox?.moda} />}
      {m.seguros && <Seguros s={m.seguros} />}
      {m.lineas && m.lineas.length > 0 && <Lineas lineas={m.lineas} />}
      {m.lineas && m.lineas.length > 0 && m.lineas_reales === false && (
        <p className="-mt-1 text-[11px] text-mute">Líneas que Playdoit publica para un partido así (su patrón en 60 partidos reales). Si tu casa muestra otra, usa la calculadora.</p>
      )}
      {m.opciones && <Opciones ops={m.opciones} />}
      {m.lineas && <Calculadora gameId={gameId} clave={m.clave} veredicto={m.veredicto} />}
    </div>
  );
}

export function MercadosPanel({ gameId, data, home, away }: { gameId: string; data: MercadosData; home: Partial<Team>; away: Partial<Team> }) {
  const [grupo, setGrupo] = useState(data.grupos[0]?.grupo ?? "");
  const g = data.grupos.find((x) => x.grupo === grupo) ?? data.grupos[0];
  const teams = useMemo(() => ({ [home.abbr ?? "H"]: home, [away.abbr ?? "A"]: away }), [home, away]);
  const veredictos = useMemo(() => [...new Set(g?.mercados.map((m) => m.veredicto) ?? [])], [g]);
  if (!g) return null;
  const ic = ICONO[g.icono] ?? ICONO.puntos;
  return (
    <div className="space-y-4">
      <div className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <IconTile icon={ic.icon} tone={ic.tone} size={40} />
          <div className="text-sm text-ink2">
            <b className="text-ink">Todo lo que se puede apostar del partido, además de los jugadores.</b> De cada mercado: cuánto espera
            Cinna, la probabilidad de cada línea y su <b className="text-ink">momio justo</b> (si tu casa paga mejor, hay valor).
            {data.partidos_validacion ? <> Probado con {data.partidos_validacion.toLocaleString("es-MX")} partidos reales.</> : null}
            {data.importado ? (
              <span className="mt-1 block text-xs font-semibold text-good">Con las líneas y momios que mandaste de {data.importado.casa}
                {data.importado.at ? ` (${ago(data.importado.at)})` : ""}.</span>
            ) : !data.con_momios && (
              <span className="mt-1 block text-xs text-mute">Líneas típicas de Playdoit (su patrón). Para usar las de tu casa exactas,
                mándalas con el marcador <Link href="/importar" className="font-semibold text-accent hover:underline">«Enviar a Cinna»</Link>.</span>
            )}
          </div>
        </div>
      </div>
      <Segmented value={g.grupo} onChange={setGrupo} options={data.grupos.map((x) => ({ value: x.grupo, label: x.grupo }))} />
      <div className="space-y-1.5">
        {veredictos.map((v) => {
          const mk = g.mercados.find((m) => m.veredicto === v)!;
          return (
            <div key={v} className="flex items-start gap-2 text-xs text-ink2"><Veredicto v={v} /><span className="pt-0.5">{mk.nota}</span></div>
          );
        })}
      </div>
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {g.mercados.map((m) => <Tarjeta key={m.clave} m={m} gameId={gameId} teams={teams} />)}
      </div>
    </div>
  );
}
