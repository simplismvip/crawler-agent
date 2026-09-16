import { NextRequest } from "next";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND = "http://127.0.0.1:8000";

export async function POST(request: NextRequest) {
  const upstream = await fetch(`${BACKEND}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: await request.text(),
    cache: "no-store",
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
