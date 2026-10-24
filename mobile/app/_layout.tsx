import { Redirect, Slot, usePathname } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AuthProvider, useAuth } from "@/auth";
import { color } from "@/theme";

function Gate() {
  const { user, ready } = useAuth();
  const path = usePathname();
  if (!ready) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: color.canvas }}>
        <ActivityIndicator accessibilityLabel="Loading" color={color.ink} />
      </View>
    );
  }
  if (!user && path !== "/sign-in") return <Redirect href="/sign-in" />;
  if (user && path === "/sign-in") return <Redirect href="/" />;
  return <Slot />;
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="dark" />
        <Gate />
      </AuthProvider>
    </SafeAreaProvider>
  );
}
