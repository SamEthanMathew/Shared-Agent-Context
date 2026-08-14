/* A ~40-line router.
 *
 * The app has three routes. Pulling in a routing library for that would add a
 * dependency whose API surface dwarfs the problem, so this wraps the History
 * API directly: real URLs that can be linked and refreshed, nothing more.
 */
import { useCallback, useEffect, useState } from 'react'

const BASE = '/app'

/* Where we are: the path we route on, and the query that came with it.
 *
 * The query is not decoration. Accepting an invite and joining by link both
 * finish server-side and redirect to /app/c/{id}?joined=1 (app/auth/web.py),
 * and that flag is the only thing telling the SPA someone has just arrived
 * rather than come back — read the pathname alone and every new joiner lands on
 * a screen that says nothing about connecting a client.
 */
function currentRoute() {
  const { pathname, search } = window.location
  return {
    path: pathname.startsWith(BASE) ? pathname.slice(BASE.length) || '/' : '/',
    query: new URLSearchParams(search),
  }
}

export function useRoute() {
  const [route, setRoute] = useState(currentRoute)

  useEffect(() => {
    const onPop = () => setRoute(currentRoute())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((to, { replace = false } = {}) => {
    const url = BASE + (to === '/' ? '' : to)
    if (replace) window.history.replaceState({}, '', url)
    else window.history.pushState({}, '', url)
    // Split rather than store `to` whole: a caller passing "/c/x?joined=1" must
    // not end up with the query glued onto the path every route test matches.
    const [path, search = ''] = to.split('?')
    setRoute({ path: path || '/', query: new URLSearchParams(search) })
    window.scrollTo(0, 0)
  }, [])

  return { path: route.path, query: route.query, navigate }
}

/** Match /c/:id, returning the id or null. */
export function contextIdFrom(path) {
  const match = /^\/c\/([^/?]+)/.exec(path)
  return match ? match[1] : null
}

/** An <a> that navigates without a full page load. */
export function Link({ to, navigate, children, ...rest }) {
  return (
    <a
      href={BASE + (to === '/' ? '' : to)}
      onClick={(event) => {
        // Let the browser handle modified clicks (new tab, etc).
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0)
          return
        event.preventDefault()
        navigate(to)
      }}
      {...rest}
    >
      {children}
    </a>
  )
}
