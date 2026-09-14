import { useEffect, useState } from 'react'

/**
 * OS reduced-motion preference, live. index.css collapses CSS motion; this covers JS-driven motion
 * (grade settle tween, graded-row wash, now-line transition), which CSS can't stop.
 */
const QUERY = '(prefers-reduced-motion: reduce)'

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(QUERY).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const media = window.matchMedia(QUERY)
    const onChange = (event: MediaQueryListEvent) => { setReduced(event.matches) }
    setReduced(media.matches)
    media.addEventListener('change', onChange)
    return () => { media.removeEventListener('change', onChange) }
  }, [])

  return reduced
}
