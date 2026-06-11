export interface Space {
  id: string;
  name: string;
  description: string | null;
  role: string | null;
  created_at: string;
}

export interface Resource {
  id: string;
  type: string;
  title: string;
  status: "pending" | "ingesting" | "ready" | "failed";
  document_id: string | null;
  created_at: string;
}

export interface IngestStatus {
  resource_id: string;
  status: string;
  stage: string | null;
  error: string | null;
}

export interface StructureNode {
  id: string;
  parent_node_id: string | null;
  depth: number;
  heading_text: string | null;
  node_type: string;
  page_start: number | null;
  page_end: number | null;
  subtree_chunk_count: number;
}

export interface DocumentMeta {
  id: string;
  doc_type: string;
  status: string;
  page_dimensions: Record<string, [number, number]>;
  pdf_url: string;
}

export interface AuthUser {
  user_id: string;
  email: string;
}

export type DocType = "textbook" | "notes" | "question_paper" | "slides";
