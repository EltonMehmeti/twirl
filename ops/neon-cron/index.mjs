// Neon Function "vesharun": a schedule trigger POSTs here, and it calls Vesha's
// POST /internal/jobs so bookings expire, no-shows are marked and alerts go out
// even when nobody is using the site. It also wakes the free Render instance.
//
// Only Neon trigger deliveries are accepted: Neon's proxy strips client-supplied
// x-neon-* headers, so the invocation-id header proves the call came from a trigger.
// Env: JOBS_URL (https://<app>/internal/jobs), CRON_SECRET (same as TWIRL_CRON_SECRET).

export default {
  async fetch(request) {
    const headerId = request.headers.get("x-neon-trigger-invocation-id");
    if (request.method !== "POST" || !headerId) {
      return new Response("not a trigger delivery", { status: 401 });
    }
    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("invalid body", { status: 400 });
    }
    if (body?.invocation_id !== headerId) {
      return new Response("invocation id mismatch", { status: 401 });
    }
    // Render's free instance can take up to a minute to wake; allow for it.
    const res = await fetch(process.env.JOBS_URL, {
      method: "POST",
      headers: { Authorization: `Bearer ${process.env.CRON_SECRET}` },
      signal: AbortSignal.timeout(120_000),
    });
    const text = await res.text();
    console.log(`jobs ${res.status} ${text}`);
    return new Response(text, { status: res.ok ? 200 : 502 });
  },
};
