// Edge middleware — host-scoped allowlist for reports.casacalda.com.
// Any path outside `/casa-calda/*` and `/` returns 404 as if it never existed,
// so the domain looks like a single-purpose Casa Calda service. Other hosts
// (martivi-presentations.vercel.app etc.) pass through untouched — this is
// intentional: the multi-client content still lives in this project, only
// exposure on the client-branded host is what we want to lock down.

export const config = {
  matcher: [
    // Skip Vercel internals + favicon so they always resolve normally.
    '/((?!_vercel/|favicon\\.ico$).*)',
  ],
};

export default function middleware(request: Request): Response | undefined {
  const host = (request.headers.get('host') || '').toLowerCase();

  // All other hosts pass through — no behavior change.
  if (host !== 'reports.casacalda.com') return;

  const path = new URL(request.url).pathname;

  // Allow list — everything the Casa Calda subdomain is allowed to serve.
  // `/` is included so the `redirects` in vercel.json can send it → /casa-calda.
  const allowed =
    path === '/' ||
    path === '/casa-calda' ||
    path === '/casa-calda/' ||
    path.startsWith('/casa-calda/');

  if (allowed) return;

  // Everything else is a 404 — same status a nonexistent path would return,
  // no hint that the path exists on another host.
  return new Response('Not Found', {
    status: 404,
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      'cache-control': 'public, max-age=0, must-revalidate',
    },
  });
}
