import type { Metadata, Viewport } from "next";
import { Caveat, Fredoka, JetBrains_Mono, Nunito } from "next/font/google";
import { Shell } from "@/components/shell";
import "./globals.css";

// Fredoka: redonda y con carácter para títulos y la marca. Nunito: suave y muy legible para el cuerpo y los números.
const fredoka = Fredoka({ variable: "--font-fredoka", subsets: ["latin"], weight: ["400", "500", "600", "700"] });
const nunito = Nunito({ variable: "--font-nunito", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-mono-face", subsets: ["latin"] });
// Caveat: letra a mano para notitas (secciones del menú, consejos de Cinna)
const caveat = Caveat({ variable: "--font-caveat", subsets: ["latin"], weight: ["500", "600", "700"] });

export const metadata: Metadata = {
  title: { default: "CinnaParleys", template: "%s · CinnaParleys" },
  description: "Parlays y picks de la NFL horneados con datos: ganador, props de jugadores, escalones y parlays con su probabilidad real.",
  applicationName: "CinnaParleys",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbf5ec" },
    { media: "(prefers-color-scheme: dark)", color: "#1b1311" },
  ],
  width: "device-width",
  initialScale: 1,
};

// Aplica el tema guardado antes de pintar (sin parpadeo).
const THEME_INIT = `try{var t=localStorage.getItem("cinna_theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t;}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${fredoka.variable} ${nunito.variable} ${mono.variable} ${caveat.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
