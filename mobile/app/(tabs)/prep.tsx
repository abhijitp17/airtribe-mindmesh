import { useEffect, useState } from "react";
import { Linking, Text } from "react-native";
import { api, WEB_URL, type PrepSummary } from "@/api";
import { Badge, Button, Card, ErrorNote, Screen, s } from "@/ui";

export default function Prep() {
  const [preps, setPreps] = useState<PrepSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.preps().then(setPreps).catch((e) => setErr((e as Error).message)); }, []);
  return (
    <Screen title="Prep" subtitle="Your interview preparation.">
      <ErrorNote message={err} />
      {preps?.length === 0 && <Text style={s.muted}>No preps yet. Start one from a job ad in the web app.</Text>}
      {preps?.map((p) => (
        <Card key={p.id}>
          <Text style={s.h2}>{p.role_title}{p.company ? `, ${p.company}` : ""}</Text>
          {p.interview_date && <Text style={s.muted}>Interview on {p.interview_date}</Text>}
          <Badge label={p.critical_gaps ? `${p.critical_gaps} critical gap${p.critical_gaps === 1 ? "" : "s"}` : "No critical gaps"}
            tone={p.critical_gaps ? "warn" : "good"} />
          <Button kind="ghost" label="Practise in the web app" onPress={() => Linking.openURL(`${WEB_URL}/interview/${p.id}`)} />
        </Card>
      ))}
    </Screen>
  );
}
