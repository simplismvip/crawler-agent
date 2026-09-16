export type ModelInfo = {
  id: string;
  context: number;
  blurb: string;
};

export type ToolCard = {
  id?: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error";
  preview?: string;
  error?: string | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolCard[];
};

export type ConversationSummary = {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
};

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchModels(): Promise<{ default: string; models: ModelInfo[] }> {
  return readJson(await fetch("/api/models"));
}

export async function fetchConversations(query = ""): Promise<ConversationSummary[]> {
  const suffix = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
  const payload = await readJson<{ conversations: ConversationSummary[] }>(
    await fetch(`/api/conversations${suffix}`),
  );
  return payload.conversations;
}

export async function fetchConversation(id: string): Promise<ConversationSummary & { messages: ChatMessage[] }> {
  return readJson(await fetch(`/api/conversations/${id}`));
}

export async function createConversation(model?: string): Promise<ConversationSummary> {
  return readJson(
    await fetch("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    }),
  );
}

export async function renameConversation(id: string, title: string): Promise<ConversationSummary> {
  return readJson(
    await fetch(`/api/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  );
}

export async function deleteConversation(id: string): Promise<void> {
  const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
  if (!response.ok && response.status !== 204) {
    throw new Error(`HTTP ${response.status}`);
  }
}
