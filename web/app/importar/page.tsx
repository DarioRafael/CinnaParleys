"use client";

import {
  ArrowUpRight, CheckCircle, ClipboardText, Copy, FolderOpen, PuzzlePiece, ShieldCheck, Spinner, WarningCircle, WifiHigh,
} from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { mutate } from "swr";
import { ago, post, useApi } from "@/lib/api";
import { pareceCasa } from "@/components/escaner";
import { SemanaPlaydoit } from "@/components/enviar-cinna";
import { IconTile } from "@/components/icons";
import { Loading, PageHeader } from "@/components/ui";

type Resultado = {
  ok: boolean; casa?: string; game_id?: string; partido?: string; error?: string; aviso?: string | null;
  mercados?: { mercado: string; lineas: string[] }[]; jugadores?: string[]; equipos_vistos?: string[];
};
type Estado = {
  partidos: { nombre: string; at: string; mercados: number; start?: string }[]; ultima?: { nombre: string; at: string } | null;
  actualiza_en?: number | null; actualizando?: boolean; ultima_actualizacion?: string | null;
};

function Paso({ n, titulo, children, hecho }: { n: number; titulo: string; children: ReactNode; hecho?: boolean }) {
  return (
    <li className="flex gap-4 rounded-2xl bg-s2 p-4">
      <span className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-bold",
        hecho ? "bg-[var(--good)] text-white" : "bg-brand-fill text-on-brand")}>{hecho ? <CheckCircle size={18} weight="bold" /> : n}</span>
      <div className="min-w-0 flex-1 text-sm text-ink2"><div className="mb-1 font-semibold text-ink">{titulo}</div>{children}</div>
    </li>
  );
}

function Copiable({ texto, etiqueta }: { texto: string; etiqueta?: string }) {
  const [ok, setOk] = useState(false);
  return (
    <button onClick={async () => { await navigator.clipboard.writeText(texto); setOk(true); setTimeout(() => setOk(false), 2500); }}
      className="mt-2 inline-flex max-w-full items-center gap-2 rounded-xl border border-line bg-s1 px-3 py-2 text-left font-mono text-xs text-ink hover:border-accent">
      <span className="truncate">{etiqueta ?? texto}</span>
      <span className="inline-flex shrink-0 items-center gap-1 font-sans font-semibold text-accent"><Copy size={14} />{ok ? "Copiado" : "Copiar"}</span>
    </button>
  );
}

export default function ImportarPage() {
  const { data: est } = useApi<Estado>("/api/playdoit/estado", { refreshInterval: 4000, dedupingInterval: 2000 });
  const [carpeta, setCarpeta] = useState<string | null>(null);
  const [errCarpeta, setErrCarpeta] = useState<string | null>(null);
  const conectado = (est?.partidos.length ?? 0) > 0;

  // al terminar la actualización que dispararon las capturas, refrescar armados y mercados
  const antes = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (antes.current !== undefined && est?.ultima_actualizacion && est.ultima_actualizacion !== antes.current) {
      mutate((k) => typeof k === "string" && (k.startsWith("/api/armados") || k.startsWith("/api/mercados") || k.startsWith("/api/game")));
    }
    antes.current = est?.ultima_actualizacion;
  }, [est?.ultima_actualizacion]);

  async function abrirCarpeta() {
    setErrCarpeta(null);
    try { const r = await post<{ carpeta: string }>("/api/abrir_extension"); setCarpeta(r.carpeta); }
    catch (e) { setErrCarpeta(e instanceof Error ? e.message : String(e)); }
  }

  return (
    <div className="space-y-6">
      <PageHeader duo={PuzzlePiece} tone="canela" kicker="a jugar" title="Conectar Playdoit">
        <p>Para que los armados usen las líneas y momios <b>reales</b> de Playdoit. Instalas una vez la extensión «Cinna» en tu navegador
          y desde ahí <b>cada partido que abras en Playdoit se manda solo</b>: entras, revisas y listo.</p>
      </PageHeader>

      {/* ---------- estado en vivo ---------- */}
      <section className={clsx("card flex flex-col gap-4 p-5 sm:flex-row sm:items-start", conectado && "ring-2 ring-[var(--good)]/40")}>
        <IconTile icon={conectado ? WifiHigh : PuzzlePiece} tone={conectado ? "menta" : "miel"} size={46} />
        <div className="min-w-0 flex-1">
          <div className="font-display text-lg font-semibold text-ink">
            {conectado ? `Conectado: ${est!.partidos.length} partido${est!.partidos.length === 1 ? "" : "s"} de Playdoit` : "Esperando partidos de Playdoit…"}
          </div>
          <p className="text-sm text-ink2">
            {conectado ? "Abajo ves cuáles de la semana ya llegaron y cuáles faltan." : "Cuando instales la extensión y abras un partido en Playdoit, aparece aquí en segundos."}
          </p>
          {(est?.actualiza_en != null || est?.actualizando) && (
            <p className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-s2 px-2.5 py-1 text-xs font-semibold text-ink2">
              <Spinner size={13} className="animate-spin" />
              {est?.actualizando ? "Recalculando armados con las líneas de Playdoit…" : `Recalculo los armados en ${est?.actualiza_en} s (por si abres más partidos)`}
            </p>
          )}
        </div>
        {conectado && (
          <Link href="/armados" className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-on-accent">
            Ver armados <ArrowUpRight size={14} weight="bold" /></Link>
        )}
      </section>

      <SemanaPlaydoit />

      {/* ---------- instalar la extensión ---------- */}
      <section className="card space-y-4 p-5">
        <div>
          <div className="font-display text-lg font-semibold text-ink">Instalar la extensión (una sola vez, 1 minuto)</div>
          <p className="text-xs text-mute">En Brave o Chrome. No se instala nada en Windows: es una carpeta que tu navegador carga.</p>
        </div>
        <ol className="space-y-3">
          <Paso n={1} titulo="Abre la página de extensiones de tu navegador">
            Copia esto y pégalo en la barra de direcciones (donde escribes las páginas), luego Enter:
            <div><Copiable texto="brave://extensions" /></div>
            <div className="mt-1 text-xs text-mute">En Chrome es <b>chrome://extensions</b>.</div>
          </Paso>
          <Paso n={2} titulo="Activa «Modo de desarrollador»">
            Es un interruptor arriba a la derecha de esa página. Al activarlo aparecen botones nuevos arriba a la izquierda.
          </Paso>
          <Paso n={3} titulo="Toca «Cargar extensión sin empaquetar» y elige la carpeta" hecho={!!carpeta}>
            Este botón te abre la carpeta en el Explorador para que sepas cuál es:
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button onClick={abrirCarpeta}
                className="inline-flex items-center gap-1.5 rounded-xl bg-brand-fill px-3 py-2 text-sm font-semibold text-on-brand">
                <FolderOpen size={16} weight="fill" /> Abrir la carpeta «extension»
              </button>
              {carpeta && <Copiable texto={carpeta} />}
            </div>
            {errCarpeta && <p className="mt-1 text-xs text-critical">{errCarpeta}</p>}
            <div className="mt-2 text-xs text-mute">En la ventana que abre el navegador, ve a esa carpeta, entra a ella y toca «Seleccionar carpeta».
              Aparece «Cinna · Playdoit» en tu lista de extensiones.</div>
          </Paso>
          <Paso n={4} titulo="Abre Playdoit y entra a los partidos" hecho={conectado}>
            <div className="mb-1 rounded-lg bg-s1 px-2 py-1 text-xs text-ink2">¿Ya la tenías instalada? En <b>brave://extensions</b> toca el
              ícono de recargar (la flecha circular) de «Cinna · Playdoit» para usar la versión nueva (1.1).</div>
            Recarga la página de Playdoit (F5) y entra a cada partido que quieras. El ícono de Cinna en tu navegador cuenta los partidos
            enviados, y arriba en esta página los ves llegar. Un minuto después, los armados ya usan esas líneas.
          </Paso>
        </ol>
        <ul className="space-y-1.5 border-t border-line pt-4 text-xs text-ink2">
          <li className="flex gap-2"><ShieldCheck size={15} className="mt-px shrink-0 text-good" />No pide nada a Playdoit por su cuenta: sólo copia los datos que Playdoit ya le mandó a tu navegador para mostrarte el partido. No toca tu sesión, tu saldo ni tus apuestas.</li>
          <li className="flex gap-2"><ShieldCheck size={15} className="mt-px shrink-0 text-good" />Sólo se activa en Playdoit y Team Mexico, y sólo manda datos a esta app en tu compu.</li>
          <li className="flex gap-2"><WarningCircle size={15} className="mt-px shrink-0 text-warning" />Las casas pueden prohibir copiar sus momios en sus términos: úsalo para ti.</li>
        </ul>
      </section>

      <OtrasCasas />
    </div>
  );
}

/** Otras casas: copiar el texto de la página y pegarlo (sirve donde los mercados no están en un marco aparte). */
function OtrasCasas() {
  const [estado, setEstado] = useState<"espera" | "leyendo" | "listo" | "error">("espera");
  const [res, setRes] = useState<Resultado | null>(null);
  const ocupado = useRef(false);

  const enviar = useCallback(async (texto: string) => {
    if (ocupado.current) return;
    ocupado.current = true;
    setEstado("leyendo");
    try {
      const r = await post<Resultado>("/api/importar_casa", { texto, titulo: "", url: "" });
      setRes(r);
      setEstado(r.ok ? "listo" : "error");
      mutate((k) => typeof k === "string" && (k.startsWith("/api/armados") || k.startsWith("/api/mercados")));
    } catch (err) {
      setRes({ ok: false, error: err instanceof Error ? err.message : String(err) });
      setEstado("error");
    } finally {
      ocupado.current = false;
    }
  }, []);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("pegado") === "1") {
      let t = "";
      try { t = sessionStorage.getItem("cinna_pegado") ?? ""; sessionStorage.removeItem("cinna_pegado"); } catch { /* nada */ }
      if (t) enviar(t);
    }
    function onPaste(e: ClipboardEvent) {
      const t = e.clipboardData?.getData("text") ?? "";
      if (!t) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      if (pareceCasa(t)) enviar(t);
      else { setRes({ ok: false, error: "Lo que pegaste no trae mercados (renglones «Más de / Menos de» con momio)." }); setEstado("error"); }
    }
    window.addEventListener("paste", onPaste, true);
    return () => window.removeEventListener("paste", onPaste, true);
  }, [enviar]);

  return (
    <details className="card p-5" open={estado !== "espera"}>
      <summary className="flex cursor-pointer list-none items-center gap-3">
        <IconTile icon={ClipboardText} tone="lila" size={38} />
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-ink">Otras casas: copiar y pegar</div>
          <div className="text-xs text-mute">Para casas cuya página sí se deja copiar (en Playdoit no funciona: usa la extensión).</div>
        </div>
      </summary>
      <div className="mt-4 space-y-3">
        <p className="text-sm text-ink2">En la página del partido: <b>Ctrl + A</b> y <b>Ctrl + C</b>. Aquí: <b>Ctrl + V</b>.</p>
        {estado === "leyendo" && <Loading label="Leyendo…" />}
        {estado !== "leyendo" && res && <ResultadoCard r={res} />}
      </div>
    </details>
  );
}

function ResultadoCard({ r }: { r: Resultado }) {
  if (!r.ok) {
    return (
      <div className="flex items-start gap-3 rounded-xl bg-s2 p-4 text-sm text-ink2">
        <WarningCircle size={20} className="shrink-0 text-warning" />
        <div><div className="font-semibold text-ink">No pude leerlo</div><p>{r.error ?? r.aviso}</p></div>
      </div>
    );
  }
  return (
    <div className="space-y-3 rounded-xl bg-s2 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <CheckCircle size={22} weight="fill" className="text-good" />
        <div className="min-w-0 flex-1 font-semibold text-ink">Listo: {r.partido} <span className="text-xs font-normal text-mute">({r.casa})</span></div>
        {r.game_id && <Link href={`/partido/${r.game_id}?tab=armados`} className="text-sm font-semibold text-accent hover:underline">Ver armados</Link>}
      </div>
      {!!r.mercados?.length && (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {r.mercados.map((m) => (
            <div key={m.mercado} className="rounded-lg bg-s1 px-3 py-2">
              <div className="text-xs font-semibold text-ink">{m.mercado}</div>
              <div className="text-[11px] text-ink2 tnum">{m.lineas.join(" · ")}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
