/* A ~40-line router.
 *
 * The app has three routes. Pulling in a routing library for that would add a
 * dependency whose API surface dwarfs the problem, so this wraps the History
 * API directly: real URLs that can be linked and refreshed, nothing more.
 */
import { useCallback, useEffect, useState } from 'react'

const BASE = '/app'

function currentPath() {
  const path = window.location.pathname
  return path.startsWith(BASE) ? path.slice(BASE.length) || '/' : '/'
}

export function useRoute() {
  const [path, setPath] = useState(currentPath)

  useEffect(() => {
    const onPop = () => setPath(currentPath())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((to, { replace = false } = {}) => {
    const url = BASE + (to === '/' ? '' : to)
    if (replace) window.history.replaceState({}, '', url)
    else window.history.pushState({}, '', url)
    setPath(to)
    window.scrollTo(0, 0)
  }, [])

  return { path, navigate }
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
