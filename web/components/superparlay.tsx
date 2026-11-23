"use client";

import { CaretDown, ClipboardText, Info, Prohibit, Sparkle, WarningCircle } from "@phosphor-icons/react";
import clsx from "clsx";
import { useMemo, useState } from "react";
import { pct, post, useApi } from "@/lib/api";
import { IconTile } from "./icons";
import { Parlay, ParlayCard, Pata, PataFila } from "./patas";
import { Loading } from "./ui";

type PataSP = Pata & { partido: string; semaforo: "verde" | "amarillo" | "rojo" };
type Resp = {
  error?: string; semana?: number;
  parlays: { n: number; patas: string[]; prob_conjunta: number; pago_estimado: number; partidos: string[] }[];
  patas: PataSP[]; descartadas: { titulo: string; prob: number; por_que: string[] }[];
  planes: { [gid: string]: { partido: string; plan: string[] } }; revisar_antes?: string[];
  frescura?: { aviso?: string | null }; nota?: string;
};

const FILTROS = [["", "Todo"], ["qb", "QB"], ["rb", "Corredores"], ["receptores", "Receptores"]] as const;
const SEM_TXT = { verde: "Sin focos rojos", amarillo: "Con algo en contra", rojo: "Descartada" } as const;
const SEM_COLOR = { verde: "var(--good)", amarillo: "var(--warning)", rojo: "var(--critical)" } as const;
const DESC: Record<number, string> = { 3: "Las tres patas más firmes de la semana.", 4: "Una pata más: paga más, sale un poco menos.",
  5: "Cinco patas: el que más paga." };

export function SuperParlay() {
  const [solo, setSolo] = useState<string>("");
  const [sem, setSem] = useState<"todas" | "verde" | "amarillo">("todas");
  const [abiertas, setAbiertas] = useState(false);
  const [texto, setTexto] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const { data, isLoading, mutate } = useApi<Resp>(`/api/super_parlay${solo ? `?solo=${solo}` : ""}`, { revalidateOnFocus: false });
  const byT = useMemo(() => Object.fromEntries((data?.patas ?? []).map((p) => [p.titulo, p])), [data]);
  const parlays: Parlay[] = useMemo(() => (data?.parlays ?? []).map((p) => {
    const patas = p.patas.map((t) => byT[t] ?? ({ titulo: t, prob: 0 } as Pata));
    const pago = p.pago_estimado;
    return { perfil: p.n === 3 ? "seguro" : p.n === 4 ? "balanceado" : "buen_pago", label: `${p.n} patas`,
      desc: `${DESC[p.n] ?? ""} De ${p.partidos.length} partido${p.partidos.length === 1 ? "" : "s"}.`,
      prob_conjunta: p.prob_conjunta, pago_estimado: pago, pago_justo: p.prob_conjunta ? 1 / p.prob_conjunta : null, patas };
  }), [data, byT]);
  const patas = (data?.patas ?? []).filter((l) => sem === "todas" || l.semaforo === sem);
  const cuenta = (s: string) => (data?.patas ?? []).filter((l) => l.semaforo === s).length;

  async function guardar() {
    if (!texto.trim()) return;
    const r = await post<{ guardados: string[]; no_entendi: string[] }>("/api/draftea/minimos", { texto });
    setMsg(`Guardados: ${r.guardados.join(", ") || "ninguno"}${r.no_entendi.length ? ` · No entendí: ${r.no_entendi.join(", ")}` : ""}`);
    setTexto("");
    mutate();
  }

  return (
    <section className="space-y-4">
      <div className="card flex flex-col gap-4 p-5 lg:flex-row lg:items-center">
        <IconTile icon={Sparkle} tone="rosa" size={48} />
        <div className="min-w-0 flex-1">
          <div className="font-display text-xl font-semibold text-ink">Súper parlay{data?.semana ? ` · semana ${data.semana}` : ""}</div>
          <p className="mt-1 text-sm text-ink2">
            Cada pata es el <b className="text-ink">escalón más bajo de la casa</b>, revisado contra el rival, Kalshi, el guion del partido,
            la salud del jugador, el viento y las historias trampa. La probabilidad de que salga todo viene de la simulación de cada partido.
          </p>
        </div>
        <div className="inline-flex shrink-0 rounded-2xl border border-line bg-s2 p-1 text-sm">
          {FILTROS.map(([v, l]) => (
            <button key={v} onClick={() => setSolo(v)}
              className={clsx("rounded-xl px-3 py-1.5 font-semibold", solo === v ? "bg-s1 text-ink shadow-sm" : "text-ink2 hover:text-ink")}>{l}</button>
          ))}
        </div>
      </div>
      {data?.frescura?.aviso && (
        <div className="card flex items-start gap-2 px-4 py-3 text-sm text-warning">
          <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0" />{data.frescura.aviso}
        </div>
      )}
      {isLoading || !data ? <Loading /> : data.error ? <div className="card p-5 text-sm text-mute">{data.error}</div> : (
        <>
          <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
            {parlays.map((p) => <ParlayCard key={p.label} pz={p} mostrarPartido />)}
          </div>

          <div className="card p-4 sm:p-5">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <div className="font-display text-base font-semibold text-ink">Por qué cada pata</div>
              <span className="text-xs text-mute">Toca una pata para ver qué la ayuda, qué la complica y en qué caso se cae.</span>
              <div className="ml-auto inline-flex rounded-xl border border-line bg-s2 p-0.5 text-xs font-semibold">
                {(["todas", "verde", "amarillo"] as const).map((v) => (
                  <button key={v} onClick={() => setSem(v)}
                    className={clsx("inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1", sem === v ? "bg-s1 text-ink shadow-sm" : "text-ink2 hover:text-ink")}>
                    {v !== "todas" && <span className="h-2 w-2 rounded-full" style={{ background: SEM_COLOR[v] }} />}
                    {v === "todas" ? "Todas" : SEM_TXT[v]}
                    <span className="tnum text-mute">{v === "todas" ? data.patas.length : cuenta(v)}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-1 items-start gap-2 lg:grid-cols-2">
              {(abiertas ? patas : patas.slice(0, 10)).map((l) => <PataFila key={l.titulo} l={l} mostrarPartido />)}
            </div>
            {patas.length > 10 && (
              <button onClick={() => setAbiertas((x) => !x)}
                className="mt-3 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-ink2 hover:bg-s2 hover:text-ink">
                <CaretDown size={14} className={clsx("transition-transform", abiertas && "rotate-180")} />
                {abiertas ? "Ver menos" : `Ver las ${patas.length} patas`}
              </button>
            )}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {data.descartadas.length > 0 && (
              <div className="card p-4">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink"><Prohibit size={18} className="text-critical" />Descartadas (foco rojo)</div>
                <ul className="space-y-2">
                  {data.descartadas.map((d) => (
                    <li key={d.titulo} className="text-xs">
                      <div className="flex justify-between gap-2"><b className="text-ink">{d.titulo}</b><span className="tnum text-mute">{pct(d.prob)}</span></div>
                      <div className="text-ink2">{d.por_que.join(" · ")}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="card p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink"><ClipboardText size={18} className="text-accent" />Plan de juego de cada partido</div>
              <div className="max-h-72 space-y-3 overflow-y-auto pr-1">
                {Object.values(data.planes).map((g) => (
                  <div key={g.partido} className="text-xs">
                    <div className="mb-0.5 font-semibold text-ink">{g.partido}</div>
                    {g.plan.map((t) => <div key={t} className="text-ink2">· {t}</div>)}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
      <div className="card p-4">
        <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-ink"><ClipboardText size={18} className="text-brand" />Mínimos que ves en Draftea</div>
        <p className="mb-2 text-xs text-mute">Escríbelos como quieras (uno por línea): «Herbert 16 pases completos», «Henry 70 yardas por tierra». El súper parlay usará esos números.</p>
        <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={3}
          className="w-full rounded-xl border border-line bg-s1 p-2.5 text-sm text-ink outline-none focus:border-accent" />
        <div className="mt-2 flex items-center gap-3">
          <button onClick={guardar} className="rounded-xl bg-accent px-3.5 py-1.5 text-sm font-semibold text-on-accent">Guardar</button>
          {msg && <span className="text-xs text-ink2">{msg}</span>}
        </div>
      </div>
      {data?.nota && <p className="flex gap-2 text-[11px] text-mute"><Info size={14} className="mt-px shrink-0" />{data.nota}</p>}
    </section>
  );
}
