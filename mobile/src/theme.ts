// Mesh design tokens, shared with the web app (web/src/app/globals.css, DECISIONS #64): teal-charcoal
// ink on warm parchment, one deep-green action per screen (green always carries light text),
// coral for what needs attention (coral always carries ink text).
export const color = {
  ink: "#1D3338",
  ink2: "#4F5F62",
  ink3: "#8E9992",
  canvas: "#F5F2E9",
  glass: "#FDFBF5",
  line: "rgba(29,51,56,0.10)",
  edge: "#E3DFD4",
  green: "#194D43",
  onGreen: "#FAF8F0",
  coral: "#E78363",
  orange: "#E78363", // legacy alias for coral
  good: "#2F5D3A", goodBg: "#DCE9D6",
  info: "#234C5C", infoBg: "#E3EBEC",
  warn: "#7A4A12", warnBg: "#F6E7C8",
  bad: "#9B2C2C", badBg: "#F7DDD3",
};
export const radius = { md: 14, lg: 22 };
export const space = (n: number) => n * 4;
export const MIN_TAP = 44; // tap targets, as on the web
