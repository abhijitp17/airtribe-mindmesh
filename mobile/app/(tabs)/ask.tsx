import { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";
import { api, type NotesAnswer, type NotesStats } from "@/api";
import { Badge, Button, Card, ErrorNote, Screen, s } from "@/ui";

const BADGE: Record<string, [string, "good" | "info"]> = {
  graph: ["From your progress · no AI used", "good"],
  reused: ["Your earlier verified answer · no AI used", "good"],
  notes: ["Quoted from your notes · no AI used", "good"],
  ai: ["AI answer, cited from your notes", "info"],
  general: ["General AI answer · not from your notes", "info"],
};
const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

/** Ask my notes: answers from your material first, at no AI cost; the AI only when you choose it. */
export default function Ask() {
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState("");
  const [res, setRes] = useState<NotesAnswer | null>(null);
  const [stats, setStats] = useState<NotesStats | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const loadStats = () => api.notesStats().then(setStats).catch(() => setStats(null));
  useEffect(() => { void loadStats(); }, []);

  async function run(question: string, useAi: "explain" | "general" | null) {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.ask(question, useAi));
      setAsked(question);
      void loadStats();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Ask my notes" subtitle="Answers come from your own material first, at no AI cost.">
      {stats && stats.from_notes + stats.with_ai > 0 && (
        <Text accessibilityLabel="Savings" style={s.muted}>
          Last 30 days: {stats.from_notes} from your notes, {stats.with_ai} with the AI · about {fmt(stats.tokens_saved_estimate)} tokens saved
        </Text>
      )}
      <Card>
        <TextInput accessibilityLabel="Your question" style={s.input} value={q} onChangeText={setQ} placeholder="What is Little's Law?"
          onSubmitEditing={() => q.trim().length > 1 && run(q.trim(), null)} returnKeyType="search" />
        <Button kind="primary" label="Ask my notes" onPress={() => run(q.trim(), null)} busy={busy} disabled={q.trim().length < 2} />
      </Card>
      <ErrorNote message={err} />
      {res && (
        <Card>
          {BADGE[res.mode] && <Badge label={BADGE[res.mode][0]} tone={BADGE[res.mode][1]} />}
          {!!res.answer && <Text style={s.body}>{res.answer}</Text>}
          {res.citations.filter((c, i, all) => all.findIndex((x) => x.label === c.label) === i).map((c) => (
            <Text key={c.label} style={s.muted}>[{c.label}] p. {c.page_start}</Text>
          ))}
          {res.mode === "needs_ai" && (
            <View style={{ gap: 8 }}>
              <Text style={s.muted}>{res.reason} Here&apos;s what your notes say, free:</Text>
              {res.passages.map((p) => <Text key={p.chunk_id} style={s.muted}>p. {p.page_start}: {p.text}</Text>)}
              <Button label={`Explain with AI (about ${fmt(res.ai_tokens_estimate)} tokens)`} onPress={() => run(asked, "explain")} busy={busy} />
            </View>
          )}
          {res.mode === "not_found" && (
            <View style={{ gap: 8 }}>
              <Text style={s.body}>Your notes don&apos;t cover this yet.</Text>
              <Button label={`Ask the AI: general knowledge (about ${fmt(res.ai_tokens_estimate)} tokens)`} onPress={() => run(asked, "general")} busy={busy} />
            </View>
          )}
        </Card>
      )}
    </Screen>
  );
}
