/** Thin line icon set for the Mesh design system (24px grid, 1.6 stroke). */
const PATHS = {
  today: "M4 7h16M4 7v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7M4 7l1-3h14l1 3M9 12h6",
  prep: "M4 20V9l8-5 8 5v11M9 20v-6h6v6",
  library: "M5 4h10l4 4v12H5zM15 4v4h4M8 13h8M8 17h5",
  arrow: "M7 17 17 7M9 7h8v8",
  back: "M15 6l-6 6 6 6",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20a2 2 0 0 0 4 0",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z",
  mic: "M12 3a4 4 0 0 1 4 4v4a4 4 0 0 1-8 0V7a4 4 0 0 1 4-4zM5 11a7 7 0 0 0 14 0M12 18v3",
  upload: "M12 16V4M7 9l5-5 5 5M5 20h14",
  check: "M5 12.5l4.5 4.5L19 7",
  close: "M6 6l12 12M18 6 6 18",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  plus: "M12 5v14M5 12h14",
  flag: "M5 21V4h11l-1.5 4L16 12H5",
  quote: "M7 7h4v4c0 3-1.5 5-4 6M14 7h4v4c0 3-1.5 5-4 6",
  mesh: "M12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM5 7.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM19 7.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM6 20.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM18 20.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM6.2 6.8l3.9 3.6M17.8 6.8l-3.9 3.6M7.2 17.9l3-3.7M16.8 17.9l-3-3.7",
  menu: "M4 7h16M4 12h16M4 17h16",
  send: "M4 12 20 4l-6 16-2.5-6.5zM11.5 13.5 20 4",
  next: "M5 12h14M13 6l6 6-6 6",
  play: "M8 5v14l11-7z",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01",
  book: "M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 5v16M8 7h7",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
} as const;

export type IconName = keyof typeof PATHS;

export default function Icon({ name, size = 20, label }: { name: IconName; size?: number; label?: string }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
