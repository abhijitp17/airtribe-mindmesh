# Mindmesh mobile (Expo, SDK 57)

Today (timed sessions), **Ask my notes** (answers from your material at no AI cost), Library, Prep
and Settings (reminders and push notifications), on the same API as the web app. Aura design tokens
in `src/theme.ts`. Dependencies are pinned to releases at least two weeks old.

```bash
cd mobile && npm install
EXPO_PUBLIC_API_URL=http://localhost:8300 npx expo start      # i = iOS simulator, a = Android, w = web
```

- **API address:** simulators reach your Mac at `localhost`; an Android emulator at `10.0.2.2`; a phone
  needs your Mac's LAN address (and `CORS_ORIGINS` doesn't apply to native apps, only to the web build).
- **Push notifications:** need a development or store build with an Expo project id
  (`EXPO_PUBLIC_EAS_PROJECT_ID`) and `PUSH_BACKEND=expo` on the API. Expo Go and the web build can't
  receive them; the app explains why when you turn reminders on.
- **Sign-in:** email and password (the API's local mode). Clerk on mobile comes with the Clerk keys.
- **Checks:** `npm run typecheck`, `npm test`, `npm run export:web` (CI runs all three).
