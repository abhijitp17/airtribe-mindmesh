"use client";

import type { Minutes } from "@/lib/api-engagement";
import { MINUTE_CHOICES } from "./labels";

/** 5 / 15 / 30 minute segmented control. Toggle buttons with aria-pressed. */
export default function TimePicker({ value, onChange, disabled = false }: { value: Minutes; onChange: (m: Minutes) => void; disabled?: boolean }) {
  return (
    <div className="segmented" role="group" aria-label="How much time do you have?">
      {MINUTE_CHOICES.map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={value === m}
          onClick={() => onChange(m)}
          disabled={disabled}
          style={{ minHeight: 44 }}
        >
          {m} min
        </button>
      ))}
    </div>
  );
}
