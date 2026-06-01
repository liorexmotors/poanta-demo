const PROTECTED_PATHS = new Set([
  '/feedback-dashboard.html',
  '/rss-dashboard.html',
  '/rss-viewer.html',
  '/dashboard_ops_snapshot.json',
]);

function isProtectedPath(pathname) {
  if (PROTECTED_PATHS.has(pathname)) return true;
  if (pathname === '/feedback-dashboard') return true;
  if (pathname === '/rss-dashboard') return true;
  if (pathname === '/rss-viewer') return true;
  if (pathname === '/dashboard') return true;
  if (pathname === '/dashboard/') return true;
  if (pathname.startsWith('/dashboard/')) return true;
  return false;
}

function unauthorized(message = 'Authentication required') {
  return new Response(message, {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Poenta Dashboard", charset="UTF-8"',
      'Cache-Control': 'no-store',
      'X-Robots-Tag': 'noindex, nofollow',
    },
  });
}

function constantTimeEqual(a, b) {
  const left = String(a || '');
  const right = String(b || '');
  let diff = left.length ^ right.length;
  const max = Math.max(left.length, right.length);
  for (let i = 0; i < max; i += 1) {
    diff |= (left.charCodeAt(i) || 0) ^ (right.charCodeAt(i) || 0);
  }
  return diff === 0;
}

function readBasicAuth(request) {
  const header = request.headers.get('Authorization') || '';
  const match = header.match(/^Basic\s+(.+)$/i);
  if (!match) return null;
  try {
    const decoded = atob(match[1]);
    const separator = decoded.indexOf(':');
    if (separator < 0) return null;
    return {
      username: decoded.slice(0, separator),
      password: decoded.slice(separator + 1),
    };
  } catch {
    return null;
  }
}

export async function onRequest(context) {
  const { request, env, next } = context;
  const url = new URL(request.url);

  if (!isProtectedPath(url.pathname)) {
    return next();
  }

  const expectedUser = env.POENTA_DASHBOARD_USER || 'poenta';
  const expectedPassword = env.POENTA_DASHBOARD_PASSWORD;

  if (!expectedPassword) {
    return new Response('Dashboard authentication is not configured', {
      status: 503,
      headers: {
        'Cache-Control': 'no-store',
        'X-Robots-Tag': 'noindex, nofollow',
      },
    });
  }

  const auth = readBasicAuth(request);
  const ok = auth &&
    constantTimeEqual(auth.username, expectedUser) &&
    constantTimeEqual(auth.password, expectedPassword);

  if (!ok) {
    return unauthorized();
  }

  const response = await next();
  const secured = new Response(response.body, response);
  secured.headers.set('Cache-Control', 'no-store');
  secured.headers.set('X-Robots-Tag', 'noindex, nofollow');
  return secured;
}

export const __test__ = { isProtectedPath, constantTimeEqual, readBasicAuth };
