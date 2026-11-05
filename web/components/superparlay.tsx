"use client";

import clsx from "clsx";
import { AlertTriangle, CheckCircle2, ClipboardList, MinusCircle, Sparkles } from "lucide-react";
import { useState } from "react";
import { pct, post, useApi } from "@/lib/api";
import { Loading, SectionTitle } from "./ui";

type Pata = {
  titulo: string; partido: string; prob: number; p_kalshi?: number | null; fuente_minimo?: string; proyeccion?: number;
  linea_casa?: number | null; a_favor: string[]; en_contra: string[]; racha?: string | null; semaforo: "verde" | "amarillo" | "rojo";
};
type Resp = {
  error?: string; semana?: number;
  parlays: { n: number; patas: string[]; prob_conjunta: number; pago_estimado: number; partidos: string[] }[];
  patas: Pata[]; descartadas: { titulo: string; prob: number; por_que: string[] }[];
  planes: { [gid: string]: { partido: string; plan: string[] } }; revisar_antes?: string[];
  frescura?: { aviso?: string | null }; nota?: string;
};

const SEM: Record<string, string> = { verde: "bg-[var(--good)]", amarillo: "bg-[var(--warning)]", rojo: "bg-[var(--critical)]" };
const FILTROS = [["", "Todo"], ["qb", "QB"], ["rb", "Corredores"], ["receptores", "Receptores"]] as const;

export function SuperParlay() {
  const [solo, setSolo] = useState<string>("");
  const [texto, setTexto] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const { data, isLoading, mutate } = useApi<Resp>(`/api/super_parlay${solo ? `?solo=${solo}` : ""}`, { revalidateOnFocus: false });
  const byT = Object.fromEntries((data?.patas ?? []).map((p) => [p.titulo, p]));

  async function guardar() {
    if (!texto.trim()) return;
    const r = await post<{ guardados: string[]; no_entendi: string[] }>("/api/draftea/minimos", { texto });
    setMsg(`Guardados: ${r.guardados.join(", ") || "ninguno"}${r.no_entendi.length ? ` · No entendí: ${r.no_entendi.join(", ")}` : ""}`);
    setTexto("");
    mutate();
  }

  return (
    <section className="card space-y-4 border-accent/40 p-5">
      <SectionTitle right={
        <div className="flex rounded-lg bg-s2 p-0.5 text-xs">
          {FILTROS.map(([v, l]) => (
            <button key={v} onClick={() => setSolo(v)}
              className={clsx("rounded-md px-2.5 py-1", solo === v ? "bg-s3 font-semibold text-ink" : "text-ink2")}>{l}</button>
          ))}
        </div>}>
        <span className="inline-flex items-center gap-1.5"><Sparkles size={14} />Súper parlay{data?.semana ? ` · semana ${data.semana}` : ""}</span>
      </SectionTitle>
      <p className="text-xs text-mute">
        Cada pata es el <b className="text-ink2">escalón más bajo de la casa</b> y se revisa contra el rival, Kalshi, el guion del partido,
        la salud (en duda, regresa de lesión, compañeros fuera), el viento y las historias trampa. La racha se muestra pero no sube la
        probabilidad (no predice nada extra). Probabilidad conjunta de la simulación de cada partido.
      </p>
      {data?.frescura?.aviso && (
        <div className="flex items-start gap-2 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-3 py-2 text-sm text-warning">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />{data.frescura.aviso}
        </div>
      )}
      {isLoading || !data ? <Loading /> : data.error ? <p className="text-sm text-mute">{data.error}</p> : (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            {data.parlays.map((p) => (
              <div key={p.n} className="rounded-xl border border-line bg-s1 p-4">
                <div className="mb-2 flex items-baseline justify-between">
                  <b className="text-ink">{p.n} patas</b>
                  <span className="tnum text-sm"><b className="text-ink">{pct(p.prob_conjunta, 0)}</b> <span className="text-xs text-mute">· ~{p.pago_estimado}x</span></span>
                </div>
                <ul className="space-y-1 text-sm">
                  {p.patas.map((t) => (
                    <li key={t} className="flex items-baseline justify-between gap-2">
                      <span className="text-ink">{t}{byT[t]?.fuente_minimo && byT[t].fuente_minimo !== "Draftea" &&
                        <span className="ml-1 rounded bg-s3 px-1 py-px text-[10px] text-mute">{byT[t].fuente_minimo === "Playdoit" ? "Playdoit" : "mínimo estimado"}</span>}</span>
                      <span className="tnum text-xs text-ink2">{pct(byT[t]?.prob, 0)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <details className="rounded-xl border border-line p-3" open>
            <summary className="cursor-pointer text-sm font-semibold text-ink">Por qué cada pata</summary>
            <ul className="mt-2 space-y-2">
              {data.patas.slice(0, 14).map((l) => (
                <li key={l.titulo} className="text-sm">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-ink"><span className={clsx("mr-1.5 inline-block h-2 w-2 rounded-full", SEM[l.semaforo])} />{l.titulo}
                      <span className="ml-1.5 text-[11px] text-mute">{l.partido}</span></span>
                    <span className="tnum shrink-0"><b>{pct(l.prob, 0)}</b>{l.p_kalshi != null && <span className="ml-1 text-[10px] text-mute">K {pct(l.p_kalshi, 0)}</span>}</span>
                  </div>
                  <div className="ml-4 space-y-0.5 text-xs">
                    {l.a_favor.map((t) => <div key={t} className="flex gap-1.5 text-ink2"><CheckCircle2 size={12} className="mt-0.5 shrink-0 text-good" />{t}</div>)}
                    {l.en_contra.map((t) => <div key={t} className="flex gap-1.5 text-warning"><MinusCircle size={12} className="mt-0.5 shrink-0" />{t}</div>)}
                    {l.racha && <div className="text-[11px] text-mute">Racha (sólo contexto): lo pasó {l.racha} · proyección {l.proyeccion}{l.linea_casa != null ? ` · línea ${l.linea_casa}` : ""}</div>}
                  </div>
                </li>
              ))}
            </ul>
          </details>
          {data.descartadas.length > 0 && (
            <details className="rounded-xl border border-line p-3">
              <summary className="cursor-pointer text-sm font-semibold text-ink">Descartadas (foco rojo)</summary>
              <ul className="mt-2 space-y-1 text-xs text-ink2">
                {data.descartadas.map((d) => <li key={d.titulo}><b>{d.titulo}</b> ({pct(d.prob, 0)}): {d.por_que.join(" · ")}</li>)}
              </ul>
            </details>
          )}
          <details className="rounded-xl border border-line p-3">
            <summary className="cursor-pointer text-sm font-semibold text-ink">Plan de juego de cada partido</summary>
            <div className="mt-2 grid gap-3 lg:grid-cols-2">
              {Object.values(data.planes).map((g) => (
                <div key={g.partido} className="text-xs">
                  <div className="mb-0.5 font-semibold text-ink2">{g.partido}</div>
                  {g.plan.map((t) => <div key={t} className="text-mute">· {t}</div>)}
                </div>
              ))}
            </div>
          </details>
        </>
      )}
      <div className="rounded-xl border border-line p-3">
        <div className="mb-1 inline-flex items-center gap-1.5 text-sm font-semibold text-ink"><ClipboardList size={14} />Mínimos que ves en Draftea</div>
        <p className="mb-2 text-xs text-mute">Escríbelos como quieras (uno por línea): «Herbert 16 pases completos», «Henry 70 yardas por tierra». El súper parlay usará esos números.</p>
        <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={3}
          className="w-full rounded-lg border border-line bg-s1 p-2 text-sm text-ink outline-none focus:border-accent" />
        <div className="mt-2 flex items-center gap-3">
          <button onClick={guardar} className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-on-accent">Guardar</button>
          {msg && <span className="text-xs text-ink2">{msg}</span>}
        </div>
      </div>
      {data?.nota && <p className="text-[11px] text-mute">{data.nota}</p>}
    </section>
  );
}
