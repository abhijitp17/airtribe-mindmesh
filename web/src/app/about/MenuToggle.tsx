"use client";

import { useState } from "react";
import Icon from "@/components/Icon";

/** Phone menu for the public front page (the only interactive part of it). */
export default function MenuToggle({ links }: { links: (readonly [string, string])[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="icon-btn lp-menu-btn" aria-expanded={open} aria-controls="lp-menu" aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen(!open)}>
        <Icon name={open ? "close" : "menu"} size={19} />
      </button>
      {open && (
        <nav id="lp-menu" className="lp-menu" aria-label="Menu">
          {links.map(([href, label]) => <a key={href} href={href} onClick={() => setOpen(false)}>{label}</a>)}
        </nav>
      )}
    </>
  );
}
