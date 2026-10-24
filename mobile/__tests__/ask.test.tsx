jest.mock("expo-secure-store", () => ({ getItemAsync: async () => "tok", setItemAsync: async () => {}, deleteItemAsync: async () => {} }));

import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import Ask from "../app/(tabs)/ask";

const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
const STATS = { from_notes: 3, with_ai: 1, tokens_saved_estimate: 10500, tokens_per_ai_answer: 3500 };

test("answers from notes for free, and offers the AI only for a not-found question", async () => {
  const fetchMock = jest.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/notes/stats")) return ok(STATS);
    const body = JSON.parse(String(init?.body));
    if (body.question === "What is WIP?") {
      return ok({ mode: "notes", answer: "Work in process is the inventory of started jobs. [S1]", reason: "", ai_tokens_estimate: 0,
        citations: [{ label: "S1", page_start: 2, document_id: "d", quote: "..." }], passages: [] });
    }
    return ok(body.use_ai === "general"
      ? { mode: "general", answer: "Leonardo da Vinci.", reason: "", ai_tokens_estimate: 0, citations: [], passages: [] }
      : { mode: "not_found", answer: "", reason: "", ai_tokens_estimate: 3500, citations: [], passages: [] });
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  render(<Ask />);
  expect(await screen.findByText(/about 10.5k tokens saved/)).toBeTruthy();

  fireEvent.changeText(screen.getByLabelText("Your question"), "What is WIP?");
  fireEvent.press(screen.getByRole("button", { name: "Ask my notes" }));
  expect(await screen.findByText("Quoted from your notes · no AI used")).toBeTruthy();
  expect(screen.getByText("[S1] p. 2")).toBeTruthy();

  fireEvent.changeText(screen.getByLabelText("Your question"), "Who painted the Mona Lisa?");
  fireEvent.press(screen.getByRole("button", { name: "Ask my notes" }));
  const ai = await screen.findByRole("button", { name: "Ask the AI: general knowledge (about 3.5k tokens)" });
  const before = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/notes/ask")).length;
  fireEvent.press(ai);
  expect(await screen.findByText("General AI answer · not from your notes")).toBeTruthy();
  await waitFor(() => expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/notes/ask")).length).toBe(before + 1));
});
