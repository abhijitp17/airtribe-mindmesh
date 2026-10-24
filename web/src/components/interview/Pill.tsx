import type { LabelCls } from "./labels";

/** A .badge from a [label, class] pair. Colour always comes with a text label. */
export default function Pill({ pair, title, prefix }: { pair: LabelCls; title?: string; prefix?: string }) {
  const [label, cls] = pair;
  return (
    <span className={`badge ${cls}`} title={title}>
      {prefix ? <span className="sr-only">{prefix} </span> : null}
      {label}
    </span>
  );
}
