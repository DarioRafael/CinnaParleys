"use client";

import { Duo } from "./icons";
import { MoonStars, Sun } from "@phosphor-icons/react";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

type Theme = "light" | "dark";
const EVT = "cinna-theme";
const COOLDOWN = 450;          // ms: después de un cambio, el botón descansa (no se puede picar como loco)

type VTDoc = Document & { startViewTransition?: (cb: () => void) => { finished: Promise<void> } };

function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("cinna_theme", t); } catch { /* ignorar */ }
  window.dispatchEvent(new Event(EVT));
}

export function useTheme(): [Theme, () => void, boolean] {
  const [theme, setTheme] = useState<Theme>("light");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  useEffect(() => {
    const read = () => setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    read();
    window.addEventListener(EVT, read);
    return () => window.removeEventListener(EVT, read);
  }, []);
  const toggle = () => {
    if (lock.current) return;                       // ignora los clics mientras está cambiando
    lock.current = true;
    setBusy(true);
    const next: Theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    const release = () => setTimeout(() => { lock.current = false; setBusy(false); }, COOLDOWN);
    const doc = document as VTDoc;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (doc.startViewTransition && !reduce) {
      // el navegador toma una "foto" y funde de un tema al otro en la tarjeta gráfica: suave y sin trabarse
      doc.startViewTransition(() => applyTheme(next)).finished.finally(release);
    } else {
      applyTheme(next);
      release();
    }
  };
  return [theme, toggle, busy];
}

/** Interruptor modo claro / modo oscuro. */
export function ThemeSwitch({ compact }: { compact?: boolean }) {
  const [theme, toggle, busy] = useTheme();
  const dark = theme === "dark";
  return (
    <button onClick={toggle} role="switch" aria-checked={dark} aria-busy={busy}
      aria-label={dark ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
      title={dark ? "Modo claro" : "Modo oscuro"} className={clsx("group flex items-center gap-2", busy && "cursor-wait")}>
      <span className={clsx("relative h-[26px] w-[48px] shrink-0 overflow-hidden rounded-full border border-line transition-colors duration-300",
        dark ? "bg-s3" : "bg-s2")}>
        <span className={clsx("absolute top-[2px] grid h-[20px] w-[20px] place-items-center rounded-full bg-s1 shadow-sm ring-1 ring-[var(--border)] transition-[left] duration-200",
          dark ? "left-[24px]" : "left-[2px]")}>
          <Duo icon={dark ? MoonStars : Sun} tone="neutro" size={14} />
        </span>
      </span>
      {!compact && <span className="text-[12.5px] font-medium leading-none text-ink2">{dark ? "Oscuro" : "Claro"}</span>}
    </button>
  );
}
