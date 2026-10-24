import { useEffect, useState } from "react";
import { Switch, Text, View } from "react-native";
import { api, type Prefs } from "@/api";
import { useAuth } from "@/auth";
import { enablePush } from "@/push";
import { Button, Card, ErrorNote, Screen, s } from "@/ui";

export default function Settings() {
  const { user, signOut } = useAuth();
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.prefs().then(setPrefs).catch((e) => setErr((e as Error).message)); }, []);

  async function toggleReminders(on: boolean) {
    setErr(null);
    setNote(null);
    try {
      setPrefs(await api.setPrefs({ reminders: on }));
      if (on) {
        const r = await enablePush();
        setNote(r.ok ? "Reminders will also come to this device." : `Email reminders are on. ${r.reason}`);
      }
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <Screen title="Settings" subtitle={user?.email}>
      <ErrorNote message={err} />
      <Card>
        <View style={s.row}>
          <Text nativeID="rem" style={[s.body, { flex: 1 }]}>Daily reminders</Text>
          <Switch accessibilityLabelledBy="rem" accessibilityLabel="Daily reminders" value={!!prefs?.reminders}
            onValueChange={toggleReminders} disabled={!prefs} />
        </View>
        <Text style={s.muted}>One short reminder in the evening when something is ready and you haven&apos;t practised yet. Never your notes or answers.</Text>
        {note && <Text accessibilityLiveRegion="polite" style={s.muted}>{note}</Text>}
      </Card>
      <Button label="Sign out" onPress={signOut} />
    </Screen>
  );
}
