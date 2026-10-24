import { useCallback, useEffect, useState } from "react";
import { Linking, Text, View } from "react-native";
import { api, ApiError, WEB_URL, type StudySession, type TodayPreview, type Week } from "@/api";
import { Badge, Button, Card, ErrorNote, Screen, s } from "@/ui";

const MINUTES = [5, 15, 30] as const;
// Steps that need the full editor (quizzes, interview answers) open in the web app.
const IN_APP = new Set(["review", "plan_item", "learn", "story"]);

export default function Today() {
  const [preview, setPreview] = useState<TodayPreview | null>(null);
  const [week, setWeek] = useState<Week | null>(null);
  const [minutes, setMinutes] = useState<(typeof MINUTES)[number]>(15);
  const [session, setSession] = useState<StudySession | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setErr(null);
    Promise.all([api.today(), api.week()]).then(([p, w]) => { setPreview(p); setWeek(w); })
      .catch((e) => setErr(e instanceof ApiError ? e.message : "Couldn't load Today."));
  }, []);
  useEffect(load, [load]);

  async function start() {
    setBusy(true);
    try { setSession(await api.startSession(minutes)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function mark(stepId: string, status: "done" | "skipped") {
    if (!session) return;
    try { setSession(await api.setStep(session.id, stepId, status)); } catch (e) { setErr((e as Error).message); }
  }
  async function finish() {
    if (!session) return;
    try { await api.completeSession(session.id); setSession(null); load(); } catch (e) { setErr((e as Error).message); }
  }

  const steps = session ? session.steps : preview?.suggestions[String(minutes) as "5" | "15" | "30"] ?? [];
  return (
    <Screen title={preview?.greeting_name ? `Hi, ${preview.greeting_name}` : "Today"}
      subtitle={week ? `${week.done} of ${week.target} sessions this week` : undefined}>
      <ErrorNote message={err} />
      {!session && (
        <View style={s.row} accessibilityRole="radiogroup" accessibilityLabel="Session length">
          {MINUTES.map((m) => (
            <Button key={m} label={`${m} min`} kind={m === minutes ? "primary" : "default"} onPress={() => setMinutes(m)}
              accessibilityLabel={`${m} minutes${m === minutes ? ", selected" : ""}`} />
          ))}
        </View>
      )}
      <Card>
        <Text style={s.h2}>{session ? "Your session" : `A ${minutes}-minute session`}</Text>
        {steps.length === 0 && <Text style={s.muted}>Add a document or a job in the web app to get your first session.</Text>}
        {steps.map((st) => (
          <View key={st.id} style={{ gap: 4, paddingVertical: 6, borderTopWidth: 1, borderTopColor: "rgba(29,35,33,0.08)" }}>
            <View style={s.row}>
              <Text style={[s.body, { flex: 1 }]}>{st.title}</Text>
              <Badge label={`${st.minutes} min`} />
              {st.status === "done" && <Badge label="Done" tone="good" />}
            </View>
            <Text style={s.muted}>{st.detail}</Text>
            {session && st.status === "pending" && (
              <View style={s.row}>
                {IN_APP.has(st.kind)
                  ? <Button label="Mark done" onPress={() => mark(st.id, "done")} />
                  : <Button label="Open in the web app" onPress={() => Linking.openURL(st.target.href ? `${WEB_URL}${st.target.href}` : WEB_URL)} />}
                <Button kind="ghost" label="Skip" onPress={() => mark(st.id, "skipped")} />
              </View>
            )}
          </View>
        ))}
        {!session && steps.length > 0 && <Button kind="primary" label="Start session" onPress={start} busy={busy} />}
        {session && <Button kind="primary" label="Finish session" onPress={finish} />}
      </Card>
    </Screen>
  );
}
