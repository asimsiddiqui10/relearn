"use client";

import type {
  DocumentMeta,
  IngestStatus,
  Resource,
  Space,
  StructureNode,
} from "./types";
import type { ChatMessageRow } from "./chat-types";

export interface ChatSession {
  id: string;
  title: string | null;
  visibility: string;
  created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "relearn_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  signup: (email: string, password: string, name?: string) =>
    request<{ access_token: string; user_id: string; email: string }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, name }),
    }),

  login: (email: string, password: string) =>
    request<{ access_token: string; user_id: string; email: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () => request<{ user_id: string; email: string }>("/auth/me"),

  listSpaces: () => request<Space[]>("/spaces"),
  createSpace: (name: string, description?: string) =>
    request<Space>("/spaces", { method: "POST", body: JSON.stringify({ name, description }) }),
  getSpace: (id: string) => request<Space>(`/spaces/${id}`),

  listResources: (spaceId: string) =>
    request<Resource[]>(`/spaces/${spaceId}/resources`),

  uploadResource: (spaceId: string, file: File, docType: string, title?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);
    if (title) form.append("title", title);
    return request<Resource>(`/spaces/${spaceId}/resources`, { method: "POST", body: form });
  },

  ingestStatus: (spaceId: string, resourceId: string) =>
    request<IngestStatus>(`/spaces/${spaceId}/resources/${resourceId}/status`),

  getDocument: (documentId: string) => request<DocumentMeta>(`/documents/${documentId}`),
  getStructure: (documentId: string) =>
    request<StructureNode[]>(`/documents/${documentId}/structure`),

  listChatSessions: (spaceId: string) =>
    request<ChatSession[]>(`/spaces/${spaceId}/chat/sessions`),
  createChatSession: (spaceId: string, title?: string) =>
    request<ChatSession>(`/spaces/${spaceId}/chat/sessions`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  listChatMessages: (sessionId: string) =>
    request<ChatMessageRow[]>(`/chat/sessions/${sessionId}/messages`),
};
