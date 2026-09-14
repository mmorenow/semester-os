import { useEffect, useState } from 'react'

/** The current time, re-read on a fixed tick (30s default). Drives the now-line, countdowns and due bands. */
export function useNow(intervalMs = 30_000): Date {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(new Date())
    }, intervalMs)
    return () => {
      window.clearInterval(id)
    }
  }, [intervalMs])

  return now
}
