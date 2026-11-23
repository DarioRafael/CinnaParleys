"use client";

import { Scan } from "@phosphor-icons/react";
import clsx from "clsx";
import { ChevronDown, ImagePlus, RotateCcw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { mutate } from "swr";
import { pct, post } from "@/lib/api";
import { SwirlSpinner } from "./brand";
import { Duo } from "./icons";
import { Meter } from "./ui";

type Pata = {
  titulo: string; prob: number | null; semaforo?: "verde" | "amarillo" | "rojo"; a_favor?: string[]; en_contra?: string[];
  name: string; team?: string;
};
type Resultado = {
  lineas?: string[]; texto?: string; monto?: number | null; pago?: number | null; avisos?: string[]; no_entendi?: string[];
  error?: string; patas?: Pata[]; prob_conjunta?: number | null; pago_justo?: number; valor_esperado?: number;
  veredicto?: "con valor" | "justo" | "caro";
  mas_debil?: { indice: number; titulo: string; prob: number; prob_sin_ella: number; sube_veces: number };
};

type Ctx = { abrir: (img?: Blob) => void };

/** ¿El texto pegado es la página de un partido de una casa? (varios «Más de 41.5» / «Menos de…») */
export function pareceCasa(t: string) {
  return t.length > 80 && (t.match(/(m[aá]s|menos) de \d/gi) ?? []).length >= 2;
}
const EscCtx = createContext<Ctx>({ abrir: () => undefined });
export const useEscaner = () => useContext(EscCtx);

const SEM = {
  verde: { cls: "bg-good-soft text-good", dot: "var(--good)", txt: "Verde" },
  amarillo: { cls: "bg-[var(--warning)]/15 text-warning", dot: "var(--warning)", txt: "Amarillo" },
  rojo: { cls: "bg-critical/12 text-critical", dot: "var(--critical)", txt: "Rojo" },
} as const;

/** Escáner de parlays: el botón de la barra superior o pegar una captura (Ctrl+V) en cualquier pantalla lo abre. */
export function EscanerProvider({ children }: { children: ReactNode }) {
  const [abierto, setAbierto] = useState(false);
  const [inicial, setInicial] = useState<Blob | null>(null);
  const abrir = useCallback((img?: Blob) => { setInicial(img ?? null); setAbierto(true); }, []);
  const router = useRouter();

  // pegar una imagen en cualquier lugar (que no sea un campo de texto) abre el escáner con ella
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      const f = [...(e.clipboardData?.files ?? [])].find((x) => x.type.startsWith("image/"));
      if (f) { e.preventDefault(); abrir(f); return; }
      const txt = e.clipboardData?.getData("text") ?? "";
      if (pareceCasa(txt)) {
        e.preventDefault();
        try { sessionStorage.setItem("cinna_pegado", txt); } catch { /* sin almacenamiento: no pasa nada */ }
        router.push("/importar?pegado=1");
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [abrir, router]);

  return (
    <EscCtx.Provider value={{ abrir }}>
      {children}
      {abierto && <EscanerModal inicial={inicial} onClose={() => setAbierto(false)} />}
    </EscCtx.Provider>
  );
}

export function BotonEscanear({ className }: { className?: string }) {
  const { abrir } = useEscaner();
  return (
    <button onClick={() => abrir()} title="Escanear la captura de un parlay (también puedes pegarla con Ctrl+V)"
      className={clsx("inline-flex items-center gap-1.5 rounded-full bg-brand-fill px-3.5 py-2 text-xs font-bold text-on-brand shadow-[0_6px_14px_-8px_var(--brand)] transition-transform hover:-translate-y-px", className)}>
      <Scan size={16} weight="bold" /> <span className="hidden sm:inline">Escanear parlay</span>
    </button>
  );
}

function EscanerModal({ inicial, onClose }: { inicial: Blob | null; onClose: () => void }) {
  const [img, setImg] = useState<string | null>(null);
  const [res, setRes] = useState<Resultado | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [texto, setTexto] = useState("");
  const [pago, setPago] = useState("");
  const [monto, setMonto] = useState("");
  const [guardado, setGuardado] = useState<string | null>(null);
  const [verTexto, setVerTexto] = useState(false);
  const [drag, setDrag] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const escanear = useCallback(async (b: Blob) => {
    setErr(null); setRes(null); setGuardado(null); setBusy(true);
    setImg((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(b); });
    try {
      const r = await fetch("/api/escanear", { method: "POST", body: b, headers: { "Content-Type": b.type || "image/png" } });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? "No se pudo leer la captura.");
      const d: Resultado = await r.json();
      setRes(d);
      setTexto(d.texto ?? "");
      setPago(d.pago ? String(d.pago) : "");
      setMonto(d.monto ? String(d.monto) : "");
      if (d.error) setVerTexto(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { if (inicial) escanear(inicial); }, [inicial, escanear]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [onClose]);

  const reanalizar = async () => {
    setErr(null); setBusy(true); setGuardado(null);
    try {
      const d = await post<Resultado>("/api/analizar_parlay", { texto, pago: parseFloat(pago) || null });
      setRes((r) => ({ ...r, ...d }));
      if (d.texto) setTexto(d.texto);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const registrar = async () => {
    try {
      const d = await post<{ registrada?: string; error?: string }>("/api/mis_apuestas",
        { texto, monto: parseFloat(monto) || null, pago: parseFloat(pago) || null });
      if (d.error) throw new Error(d.error);
      setGuardado(d.registrada ?? "ok");
      mutate("/api/mis_apuestas");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const pj = res?.prob_conjunta ?? null;
  const pagoN = parseFloat(pago);
  const ve = pj && pagoN > 1 ? pj * pagoN - 1 : null;
  const veredicto = ve == null ? null : ve > 0.03 ? "con valor" : ve > -0.08 ? "justo" : "caro";

  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto p-3 sm:p-6" role="dialog" aria-modal="true" aria-label="Escanear parlay">
      <button className="fixed inset-0 bg-[rgba(20,14,10,0.6)] backdrop-blur-[2px]" aria-label="Cerrar" onClick={onClose} />
      <div className="enter relative my-auto w-full max-w-4xl overflow-hidden rounded-3xl border border-line bg-s1 shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-soft"><Duo icon={Scan} tone="canela" size={24} /></span>
            <div>
              <div className="font-display text-lg font-semibold leading-tight">Escanear parlay</div>
              <div className="text-xs text-mute">La captura se lee en tu computadora: no se sube a ningún lado.</div>
            </div>
          </div>
          <button onClick={onClose} className="rounded-full p-2 text-ink2 hover:bg-s2" aria-label="Cerrar"><X size={18} /></button>
        </div>

        <div className="grid gap-5 p-5 md:grid-cols-[260px_1fr]">
          {/* captura */}
          <div>
            <input ref={file} type="file" accept="image/*" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) escanear(f); e.target.value = ""; }} />
            {img ? (
              <div className="space-y-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={img} alt="Captura del parlay" className="max-h-[420px] w-full rounded-2xl border border-line object-contain" />
                <button onClick={() => file.current?.click()} className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-line py-2 text-xs font-bold text-ink2 hover:text-ink">
                  <RotateCcw size={13} /> Escanear otra captura
                </button>
              </div>
            ) : (
              <button onClick={() => file.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
                onDrop={(e) => { e.preventDefault(); setDrag(false); const f = [...e.dataTransfer.files].find((x) => x.type.startsWith("image/")); if (f) escanear(f); }}
                className={clsx("dropzone grid h-[300px] w-full place-items-center rounded-2xl border-2 border-dashed px-4 text-center transition-colors",
                  drag ? "border-brand bg-brand-soft" : "border-line-strong hover:border-brand")}>
                <span>
                  <ImagePlus size={30} className="mx-auto text-brand" />
                  <span className="mt-2 block text-sm font-bold text-ink">Arrastra la captura aquí</span>
                  <span className="mt-1 block text-xs text-mute">o pégala con Ctrl+V, o toca para elegirla</span>
                </span>
              </button>
            )}
          </div>

          {/* resultado */}
          <div className="min-w-0">
            {busy && (
              <div className="grid h-full min-h-[260px] place-items-center text-sm font-semibold text-mute">
                <span className="flex flex-col items-center gap-3"><SwirlSpinner size={34} />Leyendo y calculando…</span>
              </div>
            )}
            {!busy && err && <div className="rounded-xl bg-critical/10 px-4 py-3 text-sm text-critical">{err}</div>}
            {!busy && !res && !err && (
              <div className="grid h-full min-h-[260px] place-items-center text-center text-sm text-ink2">
                <div className="max-w-sm space-y-2">
                  <p><b className="text-ink">Toma captura de tu parlay</b> en Draftea, Playdoit o la casa que sea, y pásala aquí.</p>
                  <p className="text-mute">Cinna lee cada pata, te dice la probabilidad real de cada una, la de que salgan todas, si el pago vale la pena y cuál pata te conviene quitar.</p>
                </div>
              </div>
            )}
            {!busy && res && (
              <div className="space-y-4">
                {res.error && <div className="rounded-xl bg-[var(--warning)]/12 px-4 py-3 text-sm text-warning">{res.error}</div>}
                {res.patas && res.patas.length > 0 && (
                  <>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <Dato titulo="Salgan todas" valor={pj != null ? pct(pj, 1) : "—"} fuerte />
                      <Dato titulo="Pago justo" valor={res.pago_justo ? `${res.pago_justo}x` : "—"} />
                      <label className="rounded-2xl border border-line bg-s2/60 px-3 py-2.5">
                        <span className="block text-[11px] font-bold uppercase tracking-wider text-mute">Te pagan</span>
                        <span className="flex items-baseline gap-1">
                          <input value={pago} onChange={(e) => setPago(e.target.value)} inputMode="decimal" placeholder="9.5"
                            className="w-full min-w-0 bg-transparent font-display text-xl font-semibold tnum outline-none" />
                          <span className="text-sm font-bold text-mute">x</span>
                        </span>
                      </label>
                      <div className={clsx("rounded-2xl px-3 py-2.5", veredicto === "con valor" ? "bg-good-soft" : veredicto === "caro" ? "bg-critical/10" : "bg-s2/60")}>
                        <span className="block text-[11px] font-bold uppercase tracking-wider text-mute">Veredicto</span>
                        <span className={clsx("font-display text-lg font-semibold", veredicto === "con valor" ? "text-good" : veredicto === "caro" ? "text-critical" : "text-ink")}>
                          {veredicto ? veredicto[0].toUpperCase() + veredicto.slice(1) : "Pon el pago"}
                        </span>
                        {ve != null && <span className="block text-[11px] text-ink2 tnum">valor esperado {ve > 0 ? "+" : ""}{Math.round(ve * 100)}%</span>}
                      </div>
                    </div>

                    <ul className="space-y-2">
                      {res.patas.map((p, i) => {
                        const s = p.semaforo ? SEM[p.semaforo] : null;
                        const debil = res.mas_debil?.indice === i;
                        return (
                          <li key={i} className={clsx("rounded-2xl border px-3.5 py-2.5", debil ? "border-[var(--warning)]/60 bg-[var(--warning)]/5" : "border-line")}>
                            <div className="flex items-center gap-3">
                              <div className="min-w-0 flex-1">
                                <div className="truncate text-sm font-bold text-ink">{p.titulo}</div>
                                <div className="mt-1"><Meter value={p.prob ?? 0} color={s?.dot ?? "var(--accent)"} height={5} /></div>
                              </div>
                              <div className="text-right">
                                <div className="font-display text-lg font-semibold tnum">{p.prob != null ? pct(p.prob) : "—"}</div>
                                {s && <span className={clsx("rounded-full px-2 py-0.5 text-[10.5px] font-bold", s.cls)}>{s.txt}</span>}
                              </div>
                            </div>
                            {(p.en_contra?.length || p.a_favor?.length) ? (
                              <div className="mt-1.5 text-[12px] leading-snug text-ink2">
                                {p.a_favor?.[0] && <div><b className="text-good">A favor:</b> {p.a_favor[0]}</div>}
                                {p.en_contra?.[0] && <div><b className="text-critical">En contra:</b> {p.en_contra[0]}</div>}
                              </div>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>

                    {res.mas_debil && res.patas.length > 1 && (
                      <div className="rounded-2xl bg-s2/70 px-4 py-3 text-sm text-ink2">
                        <b className="text-ink">La pata que más pesa:</b> {res.mas_debil.titulo}. Sin ella, la probabilidad de que salga
                        todo sube a <b className="text-ink tnum">{pct(res.mas_debil.prob_sin_ella, 1)}</b>
                        {" "}(<span className="tnum">×{res.mas_debil.sube_veces}</span>).
                      </div>
                    )}
                  </>
                )}

                {(res.avisos?.length || res.no_entendi?.length) ? (
                  <div className="text-xs text-warning">
                    {[...(res.avisos ?? []), ...(res.no_entendi ?? []).map((x) => `No entendí: "${x}"`)].map((a, i) => <div key={i}>· {a}</div>)}
                  </div>
                ) : null}

                <div className="rounded-2xl border border-line">
                  <button onClick={() => setVerTexto((x) => !x)} className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-bold text-ink2">
                    Lo que leí (corrígelo si algo salió mal) <ChevronDown size={14} className={clsx("transition-transform", verTexto && "rotate-180")} />
                  </button>
                  {verTexto && (
                    <div className="space-y-2 border-t border-line p-3">
                      <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={Math.max(3, texto.split("\n").length)}
                        placeholder="Una pata por renglón, ej.: Bryce Young 220 yds de pase"
                        className="w-full rounded-xl border border-line bg-s2/40 px-3 py-2 font-mono text-[13px] outline-none focus:border-brand" />
                      <button onClick={reanalizar} disabled={!texto.trim()}
                        className="rounded-xl bg-accent px-3.5 py-2 text-xs font-bold text-on-accent disabled:opacity-50">Volver a calcular</button>
                    </div>
                  )}
                </div>

                {res.patas && res.patas.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
                    <label className="flex items-center gap-1.5 text-xs font-bold text-ink2">
                      Monto $
                      <input value={monto} onChange={(e) => setMonto(e.target.value)} inputMode="decimal" placeholder="100"
                        className="w-20 rounded-lg border border-line bg-s1 px-2 py-1.5 text-sm tnum outline-none focus:border-brand" />
                    </label>
                    <button onClick={registrar} disabled={!!guardado}
                      className="ml-auto rounded-full bg-brand-fill px-4 py-2 text-xs font-bold text-on-brand disabled:opacity-60">
                      {guardado ? "Guardada en Mis apuestas" : "Guardar en Mis apuestas"}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Dato({ titulo, valor, fuerte }: { titulo: string; valor: string; fuerte?: boolean }) {
  return (
    <div className={clsx("rounded-2xl px-3 py-2.5", fuerte ? "bg-brand-soft" : "border border-line bg-s2/60")}>
      <span className="block text-[11px] font-bold uppercase tracking-wider text-mute">{titulo}</span>
      <span className={clsx("font-display text-xl font-semibold tnum", fuerte ? "text-brand" : "text-ink")}>{valor}</span>
    </div>
  );
}
