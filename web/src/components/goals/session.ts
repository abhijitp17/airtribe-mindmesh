import { api } from "@/lib/api";
import { goalsApi, type PlanItem } from "@/lib/api-goals";

/** Practice and review sessions open a quiz focused on the item's concept. */
export function isQuizActivity(item: PlanItem): boolean {
  return item.activity_type === "practice" || item.activity_type === "review";
}

export function itemDocumentIds(item: PlanItem): string[] {
  return Array.from(new Set(item.sources.map((s) => s.document_id)));
}

/**
 * Create a short quiz for a plan item, mark the item done once the quiz exists,
 * and return the quiz id so the caller can route to /quiz/{id}.
 */
export async function startQuizSession(documentIds: string[], item: PlanItem): Promise<string> {
  if (!documentIds.length) throw new Error("This goal has no documents to build a quiz from.");
  const quiz = await api.createQuiz(documentIds, 5, "medium", item.concept || item.topic);
  await goalsApi.updateItem(item.id, { status: "done" });
  return quiz.id;
}
