import type { CSSProperties } from "react";

/**
 * globals.css (Mesh) now styles date and number inputs too, so these only add layout.
 * Kept as exports because goal screens import them.
 */
export const fieldStyle: CSSProperties = { width: "100%" };

export const compactField: CSSProperties = { width: "auto", padding: ".45rem .6rem" };
