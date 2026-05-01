import { useRef, useCallback } from 'react'

/* ── types ────────────────────────────────────────────────────────────── */

export interface TelemetryPoint {
  t: number       // timestamp (Date.now())
  speed: number
  throttle: number
  brake: number
  gear: number
}

const MAX_BUFFER = 300

/* ── shared singleton buffer (lives outside React) ───────────────────── */

let _buffer: Map<string, TelemetryPoint[]> = new Map()

/**
 * Push a telemetry point for a driver.
 * Called from useLiveSocket's frame handler.
 */
export function pushTelemetryPoint(code: string, point: TelemetryPoint) {
  let buf = _buffer.get(code)
  if (!buf) {
    buf = []
    _buffer.set(code, buf)
  }
  buf.push(point)
  if (buf.length > MAX_BUFFER) buf.shift()
}

/**
 * Clear all telemetry buffers (e.g. on disconnect).
 */
export function clearTelemetryBuffers() {
  _buffer = new Map()
}

/**
 * Hook: returns the rolling telemetry buffer for a specific driver.
 * Returns a stable ref that updates in place (no re-renders triggered).
 */
export function useLiveTelemetry(driverCode: string | null): TelemetryPoint[] {
  if (!driverCode) return []
  return _buffer.get(driverCode) ?? []
}
