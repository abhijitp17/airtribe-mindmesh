import { useState } from "react";
import { Text, TextInput, View } from "react-native";
import { useAuth } from "@/auth";
import { Button, Card, ErrorNote, Screen, s } from "@/ui";

export default function SignIn() {
  const { signIn } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await signIn(email, password, mode);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Mindmesh" subtitle="Prepare for your next role from your own material.">
      <Card>
        <Text style={s.h2}>{mode === "login" ? "Sign in" : "Create your account"}</Text>
        <View style={{ gap: 4 }}>
          <Text nativeID="email-label" style={s.label}>Email</Text>
          <TextInput accessibilityLabelledBy="email-label" accessibilityLabel="Email" style={s.input} value={email} onChangeText={setEmail}
            autoCapitalize="none" autoComplete="email" keyboardType="email-address" textContentType="emailAddress" />
        </View>
        <View style={{ gap: 4 }}>
          <Text nativeID="pw-label" style={s.label}>Password{mode === "signup" ? " (at least 10 characters)" : ""}</Text>
          <TextInput accessibilityLabelledBy="pw-label" accessibilityLabel="Password" style={s.input} value={password} onChangeText={setPassword}
            secureTextEntry autoComplete={mode === "login" ? "current-password" : "new-password"} onSubmitEditing={submit} />
        </View>
        <ErrorNote message={err} />
        <Button kind="primary" label={mode === "login" ? "Sign in" : "Create account"} onPress={submit} busy={busy}
          disabled={!email.includes("@") || password.length < 8} />
        <Button kind="ghost" label={mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
          onPress={() => setMode(mode === "login" ? "signup" : "login")} />
      </Card>
    </Screen>
  );
}
