import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View, type ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { color, MIN_TAP, radius, space } from "./theme";

export function Screen({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
        <Text accessibilityRole="header" style={s.h1}>{title}</Text>
        {subtitle ? <Text style={s.muted}>{subtitle}</Text> : null}
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[s.card, style]}>{children}</View>;
}

export function Button({ label, onPress, kind = "default", busy, disabled, accessibilityLabel }: {
  label: string; onPress: () => void; kind?: "primary" | "default" | "ghost"; busy?: boolean; disabled?: boolean; accessibilityLabel?: string;
}) {
  const off = disabled || busy;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel ?? label} accessibilityState={{ disabled: !!off, busy: !!busy }}
      onPress={off ? undefined : onPress}
      style={({ pressed }) => [s.btn, kind === "primary" && s.primary, kind === "ghost" && s.ghost, off && s.off, pressed && !off && s.pressed]}>
      {busy ? <ActivityIndicator color={kind === "primary" ? color.onGreen : color.ink} /> : <Text style={[s.btnText, kind === "primary" && s.primaryText]}>{label}</Text>}
    </Pressable>
  );
}

export function Badge({ label, tone = "info" }: { label: string; tone?: "good" | "info" | "warn" | "bad" }) {
  const bg = { good: color.goodBg, info: color.infoBg, warn: color.warnBg, bad: color.badBg }[tone];
  const fg = { good: color.good, info: color.info, warn: color.warn, bad: color.bad }[tone];
  return <Text style={[s.badge, { backgroundColor: bg, color: fg }]}>{label}</Text>;
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <Text accessibilityRole="alert" style={s.error}>{message}</Text>;
}

export const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: color.canvas },
  scroll: { padding: space(4), gap: space(3), paddingBottom: space(10) },
  h1: { fontSize: 28, fontWeight: "700", color: color.ink, letterSpacing: -0.6 },
  h2: { fontSize: 18, fontWeight: "500", color: color.ink },
  body: { fontSize: 16, color: color.ink, lineHeight: 22 },
  muted: { fontSize: 14, color: color.ink2, lineHeight: 20 },
  card: { backgroundColor: color.glass, borderRadius: radius.lg, padding: space(4), gap: space(2), borderWidth: 1, borderColor: color.edge },
  btn: { minHeight: MIN_TAP, borderRadius: 999, paddingHorizontal: space(4), alignItems: "center", justifyContent: "center",
    backgroundColor: color.glass, borderWidth: 1, borderColor: color.edge, alignSelf: "flex-start" },
  primary: { backgroundColor: color.green, borderColor: color.green },
  primaryText: { color: color.onGreen, fontWeight: "600" },
  ghost: { backgroundColor: "transparent" },
  off: { opacity: 0.5 },
  pressed: { opacity: 0.8 },
  btnText: { fontSize: 16, fontWeight: "500", color: color.ink },
  badge: { alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 2, borderRadius: 999, fontSize: 13, overflow: "hidden" },
  error: { color: color.bad, backgroundColor: color.badBg, padding: space(3), borderRadius: radius.md, fontSize: 14 },
  input: { minHeight: MIN_TAP, borderWidth: 1, borderColor: color.line, borderRadius: radius.md, paddingHorizontal: space(3),
    backgroundColor: "#FFFFFF", fontSize: 16, color: color.ink },
  label: { fontSize: 14, color: color.ink2 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: space(2), alignItems: "center" },
});
