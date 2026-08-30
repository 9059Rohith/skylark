import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const UPSTREAM_TIMEOUT_MS = 120_000;

export async function POST(request: NextRequest) {
  const backendUrl = process.env.BACKEND_URL;
  if (!backendUrl) {
    return NextResponse.json(
      { error: "The backend service is not configured." },
      { status: 503 },
    );
  }

  const timeout = AbortSignal.timeout(UPSTREAM_TIMEOUT_MS);
  const signal = AbortSignal.any([request.signal, timeout]);

  try {
    const upstream = await fetch(new URL("/chat", backendUrl), {
      method: "POST",
      headers: {
        "Content-Type": request.headers.get("content-type") ?? "application/json",
        Accept: "text/event-stream",
      },
      body: request.body,
      duplex: "half",
      signal,
      cache: "no-store",
    } as RequestInit & { duplex: "half" });

    const headers = new Headers();
    headers.set("Content-Type", upstream.headers.get("content-type") ?? "text/event-stream");
    headers.set("Cache-Control", "no-cache, no-transform");
    headers.set("X-Accel-Buffering", "no");

    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    const timedOut = timeout.aborted;
    return NextResponse.json(
      { error: timedOut ? "The analysis service timed out." : "The analysis service is unavailable." },
      { status: timedOut ? 504 : 502 },
    );
  }
}
