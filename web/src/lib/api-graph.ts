// Knowledge map (P4): GET /api/me/graph, the learner's own concepts and how they connect.
import { request } from "./api";

export type Level = "unverified" | "weak" | "developing" | "strong";
export type MapSource = { document_id: string; page: number | null; quote: string };
export type MapNode = {
  id: string; name: string; level: Level; evidence: number; due_for_review: boolean;
  skill: string | null; sources: MapSource[]; source_count: number; degree: number;
};
export type MapEdge = { source: string; target: string; verified: boolean };
export type KnowledgeMap = { nodes: MapNode[]; edges: MapEdge[]; documents: { id: string; title: string }[]; total_concepts: number };

export const graphApi = {
  map: (limit = 150) => request<KnowledgeMap>(`/me/graph?limit=${limit}`),
};
