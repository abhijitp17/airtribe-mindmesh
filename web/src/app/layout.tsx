import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata, Viewport } from "next";
import { Caveat, DM_Mono, DM_Sans, Manrope } from "next/font/google";
import { isClerk } from "@/lib/auth-mode";
import "./globals.css";

// Mesh type, self-hosted at build time (no request to Google from the visitor's browser).
const sans = DM_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-dm-sans", display: "swap" });
const display = Manrope({ subsets: ["latin"], weight: ["600", "700", "800"], variable: "--font-manrope", display: "swap" });
const mono = DM_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-dm-mono", display: "swap" });
// One handwritten accent: the next-step note on the notebook cover. Decorative; the words are plain text.
const hand = Caveat({ subsets: ["latin"], weight: ["500", "600"], variable: "--font-caveat", display: "swap" });

// Clerk's sign-in screens in Mesh: teal-charcoal text on paper, the one deep-green action.
const CLERK_APPEARANCE = {
  variables: {
    colorPrimary: "#194D43",
    colorPrimaryForeground: "#FAF8F0",
    colorForeground: "#1D3338",
    colorMutedForeground: "#4F5F62",
    colorBackground: "#FFFDF7",
    colorInputForeground: "#1D3338",
    colorDanger: "#9B2C2C",
    fontFamily: '"DM Sans", "Avenir Next", "Segoe UI", system-ui, -apple-system, sans-serif',
    borderRadius: "16px",
  },
};

export const metadata: Metadata = {
  title: "Mindmesh: your learning, finally connected",
  description: "Turn the books, papers and courses you study into a connected map of what you know, then use it to show what you can do.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#F5F2E9",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable} ${mono.variable} ${hand.variable}`} suppressHydrationWarning>
      <head>
        <script
          // Applies the "Reduce transparency" preference before first paint (set in Profile).
          dangerouslySetInnerHTML={{
            __html: "try{if(localStorage.getItem('mindmesh_solid')==='true'){document.documentElement.dataset.solid='true'}}catch(e){}",
          }}
        />
      </head>
      <body>{isClerk ? <ClerkProvider appearance={CLERK_APPEARANCE}>{children}</ClerkProvider> : children}</body>
    </html>
  );
}
