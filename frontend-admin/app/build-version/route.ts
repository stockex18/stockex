// Which build the server is running. A panel left open across a deploy keeps
// running the JS it loaded — logging in again inside it does not reload it —
// so BuildWatcher compares this with the id compiled into its own bundle.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(
    { build: process.env.NEXT_PUBLIC_BUILD_ID ?? null },
    { headers: { "Cache-Control": "no-store" } },
  );
}
