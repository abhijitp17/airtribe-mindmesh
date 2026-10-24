import { Tabs } from "expo-router";
import { color } from "@/theme";

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: color.ink, tabBarInactiveTintColor: color.ink3,
      tabBarStyle: { backgroundColor: "#FFFFFF", borderTopColor: color.line }, tabBarIconStyle: { display: "none" },
      tabBarLabelStyle: { fontSize: 15, fontWeight: "500", marginBottom: 10 } }}>
      <Tabs.Screen name="index" options={{ title: "Today" }} />
      <Tabs.Screen name="ask" options={{ title: "Ask" }} />
      <Tabs.Screen name="library" options={{ title: "Library" }} />
      <Tabs.Screen name="prep" options={{ title: "Prep" }} />
      <Tabs.Screen name="settings" options={{ title: "Settings" }} />
    </Tabs>
  );
}
