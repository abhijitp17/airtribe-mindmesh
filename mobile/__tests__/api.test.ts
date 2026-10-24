jest.mock("expo-secure-store", () => {
  let v: string | null = null;
  return { getItemAsync: jest.fn(async () => v), setItemAsync: jest.fn(async (_k: string, x: string) => { v = x; }),
    deleteItemAsync: jest.fn(async () => { v = null; }) };
});

import { api, ApiError, request, setUnauthorizedHandler, tokenStore } from "../src/api";

const json = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

beforeEach(() => { global.fetch = jest.fn(); });

test("sends the bearer token and JSON body to the 8300 API", async () => {
  await tokenStore.set("tok-1");
  (global.fetch as jest.Mock).mockReturnValueOnce(json(200, { mode: "notes" }));
  await api.ask("What is WIP?");
  const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
  expect(url).toBe("http://localhost:8300/api/notes/ask");
  expect(init.headers.Authorization).toBe("Bearer tok-1");
  expect(JSON.parse(init.body)).toEqual({ question: "What is WIP?", use_ai: null });
});

test("shows the server's message, signs out on 401, and explains a network failure", async () => {
  (global.fetch as jest.Mock).mockReturnValueOnce(json(429, { detail: "Daily AI usage limit reached." }));
  await expect(request("/x")).rejects.toThrow("Daily AI usage limit reached.");
  const out = jest.fn();
  setUnauthorizedHandler(out);
  (global.fetch as jest.Mock).mockReturnValueOnce(json(401, {}));
  await expect(request("/x")).rejects.toBeInstanceOf(ApiError);
  expect(out).toHaveBeenCalled();
  (global.fetch as jest.Mock).mockRejectedValueOnce(new TypeError("Network request failed"));
  await expect(request("/x")).rejects.toThrow(/Can't reach Mindmesh/);
});

test("204 responses resolve without a body", async () => {
  (global.fetch as jest.Mock).mockReturnValueOnce(Promise.resolve(new Response(null, { status: 204 })));
  await expect(api.registerPush("ExponentPushToken[abc]", "ios")).resolves.toBeUndefined();
});
