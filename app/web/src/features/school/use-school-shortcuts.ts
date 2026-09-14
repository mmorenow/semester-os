import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

/** The keys the rail advertises next to their nav items, keyed by the key. */
export const SCHOOL_SHORTCUTS: Record<string, string> = {
  t: '/',
  w: '/week',
  a: '/assignments',
  c: '/courses',
  n: '/notes',
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  return target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT'
}

/** School hotkeys (t, w, a, c, n). Ignored while typing; never shadow browser or system chords. */
export function useSchoolShortcuts() {
  const navigate = useNavigate()

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return
      if (event.defaultPrevented || isTyping(event.target)) return

      const to = SCHOOL_SHORTCUTS[event.key.toLowerCase()]
      if (!to) return

      event.preventDefault()
      void navigate(to)
    }

    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [navigate])
}
