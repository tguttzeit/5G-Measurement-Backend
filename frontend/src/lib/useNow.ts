import { useEffect, useState } from 'react'

const TICK_MS = 1000

type Listener = (nowMs: number) => void

// One interval for the whole app, however many labels show a live time: it starts with the first
// subscriber and stops with the last.
const listeners = new Set<Listener>()
let intervalId: ReturnType<typeof setInterval> | undefined

function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  if (listeners.size === 1) {
    intervalId = setInterval(() => {
      const nowMs = Date.now()
      listeners.forEach((notify) => notify(nowMs))
    }, TICK_MS)
  }
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) {
      clearInterval(intervalId)
      intervalId = undefined
    }
  }
}

// Re-renders only the calling component once a second. Pass enabled=false to pause ticking.
export function useNow(enabled = true): number {
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return
    setNowMs(Date.now())
    return subscribe(setNowMs)
  }, [enabled])
  return nowMs
}
