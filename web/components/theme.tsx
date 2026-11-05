"use client";

import { Duo } from "./icons";
import { MoonStars, Sun } from "@phosphor-icons/react";
import clsx from "clsx";
import { useEffect, useState } from "react";

type Theme = "light" | "dark";
const EVT = "cinna-theme";

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>("light");
  useEffect(() => {
    const read = () => setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    read();
    window.addEventListener(EVT, read);
    return () => window.removeEventListener(EVT, read);
  }, []);
  const toggle = () => {
    const t: Theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("cinna_theme", t); } catch { /* ignorar */ }
    window.dispatchEvent(new Event(EVT));
  };
  return [theme, toggle];
}

/** Interruptor Crema / Chocolate: el sol y la luna se deslizan. */
export function ThemeSwitch({ compact }: { compact?: boolean }) {
  const [theme, toggle] = useTheme();
  const dark = theme === "dark";
  return (
    <button onClick={toggle} role="switch" aria-checked={dark} aria-label={dark ? "Cambiar a modo crema" : "Cambiar a modo chocolate"}
      title={dark ? "Modo crema" : "Modo chocolate"} className="group flex items-center gap-2">
      <span className={clsx("relative h-[30px] w-[58px] shrink-0 overflow-hidden rounded-full border border-line transition-colors duration-500",
        dark ? "bg-[linear-gradient(135deg,#2a1d33,#4a2b3a)]" : "bg-[linear-gradient(135deg,#bfe3ff,#ffe8cf)]")}>
        {/* estrellitas de noche / nubecita de día */}
        <span className={clsx("absolute left-2 top-1.5 h-1 w-1 rounded-full bg-white transition-opacity duration-500", dark ? "opacity-90" : "opacity-0")} />
        <span className={clsx("absolute left-4 top-4 h-0.5 w-0.5 rounded-full bg-white transition-opacity duration-500", dark ? "opacity-80" : "opacity-0")} />
        <span className={clsx("absolute right-2 top-2.5 h-2 w-4 rounded-full bg-white/90 transition-opacity duration-500", dark ? "opacity-0" : "opacity-100")} />
        <span className={clsx("absolute top-[2px] grid h-[24px] w-[24px] place-items-center rounded-full bg-white/90 shadow transition-all duration-500 [transition-timing-function:cubic-bezier(.34,1.6,.64,1)]",
          dark ? "left-[30px]" : "left-[2px]")}>
          <Duo icon={dark ? MoonStars : Sun} tone={dark ? "lila" : "miel"} size={17} className="transition-transform duration-500 group-hover:rotate-[20deg]" />
        </span>
      </span>
      {!compact && <span className="font-hand text-[17px] font-semibold leading-none text-ink2">{dark ? "Chocolate" : "Crema"}</span>}
    </button>
  );
}
