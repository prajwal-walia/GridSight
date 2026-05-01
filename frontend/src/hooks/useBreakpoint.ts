import { useState, useEffect } from 'react'

export function useBreakpoint() {
  const [deviceType, setDeviceType] = useState<'mobile' | 'desktop'>('desktop')

  useEffect(() => {
    // Initial check
    const mql = window.matchMedia('(max-width: 767px)')
    setDeviceType(mql.matches ? 'mobile' : 'desktop')

    const handleChange = (e: MediaQueryListEvent) => {
      setDeviceType(e.matches ? 'mobile' : 'desktop')
    }

    if (mql.addEventListener) {
      mql.addEventListener('change', handleChange)
    } else {
      // Fallback for older browsers
      mql.addListener(handleChange)
    }

    return () => {
      if (mql.removeEventListener) {
        mql.removeEventListener('change', handleChange)
      } else {
        mql.removeListener(handleChange)
      }
    }
  }, [])

  return deviceType
}
