"use client";

import clsx from "clsx";
import { AlertTriangle, BookOpenText, CheckCircle2, History, MinusCircle, XCircle } from "lucide-react";
import { useState } from "react";
import { american, pct, useApi } from "@/lib/api";
import { Loading, SectionTitle } from "./ui";

type Pata = { titulo: string; prob: number; odds?: number | null; p_kalshi?: number | null; fuente?: string };
type Guion = {
  tipo: string; titulo: string; partido: string; semana?: number; porque: string[]; en_contra?: string[]; se_cae_si: string[];
  evidencia: string; patas: Pata[]; prob_conjunta: number; prob_si_fueran_independientes: number; pago_estimado: number;
  veredicto?: string; historial?: string[];
};
type Contra = {
  titulo: string; prob: number; odds?: number | null; elite?: boolean; partido?: string; semana?: number; historia: string;
  historial: string; por_temporada?: { [s: string]: string };
};
type Resp = {
  guiones: Guion[]; contra_la_narrativa?: Contra[]; nota?: string;
  frescura?: { aviso?: string | null };
  record?: { [k: string]: { n: number; ganados: number; patas: number; patas_ganadas: number } };
};

const TIPO: Record<string, string> = {
  pocos_puntos: "Pocos puntos", volumen: "Volumen liberado", dominio: "Dominio", tiroteo: "Tiroteo", duelo: "Duelo favorable",
  persecucion: "Persecución",
};
const VER: Record<string, { txt: string; cls: string }> = {
  a_favor: { txt: "le ha ganado a la casa", cls: "bg-[var(--good)]/15 text-good" },
  neutral: { txt: "sin ventaja contra la casa", cls: "bg-s3 text-ink2" },
  sin_datos: { txt: "sin historial medido", cls: "bg-s3 text-mute" },
};
const NIVELES = [[0.65, "Normal"], [0.72, "Más seguro"], [0.6, "Paga más"]] as const;

function PataRow({ l }: { l: Pata }) {
  const est = l.fuente && l.fuente.startsWith("estimado");
  return (
    <li className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-ink">{l.titulo}{est && <span className="ml-1.5 rounded bg-s3 px-1 py-px text-[10px] text-mute">estimado</span>}</span>
      <span className="shrink-0 tnum">
        <b>{pct(l.prob, 0)}</b>
        {l.odds != null && <span className="ml-1 text-xs text-mute">{american(l.odds)}</span>}
        {l.p_kalshi != null && <span className={clsx("ml-1.5 text-[10px]", l.p_kalshi < l.prob - 0.03 ? "text-warning" : "text-mute")}>K {pct(l.p_kalshi, 0)}</span>}
      </span>
    </li>
  );
}

export function ParlaysGuion() {
  const [nivel, setNivel] = useState<number>(0.65);
  const { data, isLoading } = useApi<Resp>(`/api/guiones?n=8&nivel=${nivel}`, { revalidateOnFocus: false });
  const rec = Object.entries(data?.record ?? {});
  return (
    <section className="card space-y-4 p-5">
      <SectionTitle right={
        <div className="flex rounded-lg bg-s2 p-0.5 text-xs">
          {NIVELES.map(([v, l]) => (
            <button key={v} onClick={() => setNivel(v)}
              className={clsx("rounded-md px-2.5 py-1", nivel === v ? "bg-s3 font-semibold text-ink" : "text-ink2")}>{l}</button>
          ))}
        </div>}>
        <span className="inline-flex items-center gap-1.5"><BookOpenText size={14} />Parlays con guion</span>
      </SectionTitle>
      <p className="text-xs text-mute">
        Cada parlay cuenta <b className="text-ink2">una historia del partido</b> y trae su <b className="text-ink2">récord contra líneas reales</b> de las casas (2024-2026).
        Las historias que apuesta todo el mundo ya vienen infladas: ésas van abajo, al revés, en «contra la narrativa».
      </p>
      {data?.frescura?.aviso && (
        <div className="flex items-start gap-2 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-3 py-2 text-sm text-warning">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />{data.frescura.aviso}
        </div>
      )}
      {isLoading || !data ? <Loading /> : data.guiones.length === 0 ? (
        <p className="text-sm text-mute">Todavía no hay guiones con patas suficientemente firmes (las casas publican los escalones de martes a jueves).</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.guiones.map((g) => {
            const v = VER[g.veredicto ?? "sin_datos"] ?? VER.sin_datos;
            return (
              <article key={g.titulo + g.partido} className="rounded-xl border border-line bg-s1 p-4">
                <div className="mb-1 flex items-center justify-between gap-2 text-[11px] uppercase tracking-wider text-mute">
                  <span>{TIPO[g.tipo] ?? g.tipo} · {g.partido}{g.semana ? ` · sem ${g.semana}` : ""}</span>
                  <span className="normal-case tracking-normal tnum"><b className="text-ink">{pct(g.prob_conjunta, 0)}</b> · paga ~{g.pago_estimado}x</span>
                </div>
                <h3 className="mb-1 text-sm font-semibold text-ink">{g.titulo}</h3>
                <span className={clsx("mb-2 inline-block rounded px-1.5 py-0.5 text-[11px]", v.cls)}>Esta historia: {v.txt}</span>
                <ul className="mb-2 space-y-1">{g.patas.map((l) => <PataRow key={l.titulo} l={l} />)}</ul>
                <div className="space-y-1 text-xs">
                  <div className="font-semibold text-ink2">Va a pasar porque</div>
                  {g.porque.map((t) => <div key={t} className="flex gap-1.5 text-ink2"><CheckCircle2 size={12} className="mt-0.5 shrink-0 text-good" />{t}</div>)}
                  {(g.en_contra?.length ?? 0) > 0 && <>
                    <div className="pt-1 font-semibold text-ink2">En contra</div>
                    {g.en_contra!.map((t) => <div key={t} className="flex gap-1.5 text-warning"><MinusCircle size={12} className="mt-0.5 shrink-0" />{t}</div>)}
                  </>}
                  <div className="pt-1 font-semibold text-ink2">Se cae si</div>
                  {g.se_cae_si.map((t) => <div key={t} className="flex gap-1.5 text-mute"><XCircle size={12} className="mt-0.5 shrink-0" />{t}</div>)}
                  {(g.historial?.length ?? 0) > 0 && <>
                    <div className="pt-1 font-semibold text-ink2">Récord de esta historia</div>
                    {g.historial!.map((t) => <div key={t} className="flex gap-1.5 text-ink2"><History size={12} className="mt-0.5 shrink-0 text-mute" />{t}</div>)}
                  </>}
                  <div className="pt-1 text-[11px] text-mute">{g.evidencia}. Si las patas fueran independientes saldría {pct(g.prob_si_fueran_independientes, 0)}.</div>
                </div>
              </article>
            );
          })}
        </div>
      )}
      {(data?.contra_la_narrativa?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-line p-4">
          <div className="mb-1 text-sm font-semibold text-ink">Contra la narrativa (sencillas al Menos)</div>
          <p className="mb-2 text-xs text-mute">Lo que «todos saben» ya está en la línea. En estos casos lo que ha ganado es apostar al revés, y aquí Cinna también se inclina al Menos.</p>
          <ul className="space-y-2">
            {data!.contra_la_narrativa!.map((c) => (
              <li key={c.titulo} className="text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-ink">{c.titulo}{c.elite && <span className="ml-1.5 text-[11px] text-good">élite</span>}
                    <span className="ml-1.5 text-[11px] text-mute">{c.partido}{c.semana ? ` · sem ${c.semana}` : ""}</span></span>
                  <span className="shrink-0 tnum"><b>{pct(c.prob, 0)}</b>{c.odds != null && <span className="ml-1 text-xs text-mute">{american(c.odds)}</span>}</span>
                </div>
                <div className="text-xs text-ink2">{c.historia}.</div>
                <div className="text-[11px] text-mute">Récord: {c.historial}{c.por_temporada ? ` · ${Object.entries(c.por_temporada).map(([s, v]) => `${s}: ${v}`).join(" · ")}` : ""}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {rec.length > 0 && (
        <div className="text-xs text-ink2">
          <b>Cómo han salido de verdad</b> (los que publicó Cinna esta temporada):{" "}
          {rec.map(([k, r]) => `${TIPO[k.replace("Contra: ", "")] ? (k.startsWith("Contra: ") ? "Contra · " : "") + TIPO[k.replace("Contra: ", "")] : k} ${r.ganados} de ${r.n}`).join(" · ")}
        </div>
      )}
      {data?.nota && <p className="text-[11px] text-mute">{data.nota}</p>}
    </section>
  );
}
