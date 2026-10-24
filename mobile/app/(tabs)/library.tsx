import { useEffect, useState } from "react";
import { Linking, Text, View } from "react-native";
import { api, WEB_URL, type Doc } from "@/api";
import { Badge, Button, Card, ErrorNote, Screen, s } from "@/ui";

const STATUS: Record<string, [string, "good" | "info" | "warn" | "bad"]> = {
  ready: ["Ready", "good"], processing: ["Processing", "info"], uploaded: ["Processing", "info"],
  needs_attention: ["Check", "warn"], failed: ["Failed", "bad"],
};

export default function Library() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.documents().then(setDocs).catch((e) => setErr((e as Error).message)); }, []);
  return (
    <Screen title="Library" subtitle="Your documents. Upload new ones in the web app.">
      <ErrorNote message={err} />
      {docs?.length === 0 && <Text style={s.muted}>No documents yet.</Text>}
      {docs?.map((d) => (
        <Card key={d.id}>
          <View style={s.row}>
            <Text style={[s.body, { flex: 1 }]}>{d.title || d.filename}</Text>
            <Badge label={STATUS[d.status]?.[0] ?? d.status} tone={STATUS[d.status]?.[1] ?? "info"} />
          </View>
          {d.page_count ? <Text style={s.muted}>{d.pages_done && d.status === "processing" ? `${d.pages_done} of ` : ""}{d.page_count} pages</Text> : null}
          <Button kind="ghost" label="Open in the web app" onPress={() => Linking.openURL(`${WEB_URL}/documents/${d.id}`)} />
        </Card>
      ))}
    </Screen>
  );
}
