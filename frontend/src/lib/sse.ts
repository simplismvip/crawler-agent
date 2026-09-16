export type SseHandler = (eventName: string, data: Record<string, unknown>) => void;

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
        let eventName = "message";
        const dataLines: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trim());
          }
        }
        if (!dataLines.length) continue;
        const raw = dataLines.join("\n");
        try {
          onEvent(eventName, JSON.parse(raw) as Record<string, unknown>);
        } catch {
          onEvent(eventName, { raw });
        }
      }
    }
  } finally {
    signal?.removeEventListener("abort", abort);
  }
}
