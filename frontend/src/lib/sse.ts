export type SseHandler = (eventName: string, data: Record<string, unknown>) => void;

function parseBlock(block: string): { eventName: string; data: Record<string, unknown> } | null {
  let eventName = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (!dataLines.length) return null;
  const raw = dataLines.join("\n");
  try {
    return { eventName, data: JSON.parse(raw) as Record<string, unknown> };
  } catch {
    return { eventName, data: { raw } };
  }
}

export async function readSse(
  response: Response,
  onEvent: SseHandler,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) {
    throw new Error("missing response body");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const abort = () => {
    reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener("abort", abort);

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const block of parts) {
        if (!block.trim()) continue;
        const parsed = parseBlock(block);
        if (!parsed) continue;
        onEvent(parsed.eventName, parsed.data);
        if (parsed.eventName === "token") {
          await new Promise<void>((resolve) => {
            requestAnimationFrame(() => resolve());
          });
        }
      }
    }
  } finally {
    signal?.removeEventListener("abort", abort);
  }
}
