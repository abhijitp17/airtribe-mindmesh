// Push notifications (P3): ask the OS for permission, get this device's Expo push token and
// register it with the API, which then sends reminders (counts only). Needs a development or
// store build and an Expo project id (EXPO_PUBLIC_EAS_PROJECT_ID); Expo Go and the web build can't.
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";

export type PushResult = { ok: true; token: string } | { ok: false; reason: string };

export async function enablePush(projectId = process.env.EXPO_PUBLIC_EAS_PROJECT_ID): Promise<PushResult> {
  if (Platform.OS === "web") return { ok: false, reason: "Notifications work in the iPhone and Android apps." };
  if (!Device.isDevice) return { ok: false, reason: "Notifications need a real device, not a simulator." };
  if (!projectId) return { ok: false, reason: "This build has no Expo project id (EXPO_PUBLIC_EAS_PROJECT_ID), so it can't receive notifications." };
  const current = await Notifications.getPermissionsAsync();
  const granted = current.granted || (await Notifications.requestPermissionsAsync()).granted;
  if (!granted) return { ok: false, reason: "Notifications are turned off for Mindmesh in Settings." };
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("reminders", { name: "Reminders", importance: Notifications.AndroidImportance.DEFAULT });
  }
  const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });
  await api.registerPush(token, Platform.OS === "ios" ? "ios" : "android");
  return { ok: true, token };
}

export async function disablePush(token: string): Promise<void> {
  await api.removePush(token, Platform.OS === "ios" ? "ios" : "android");
}
