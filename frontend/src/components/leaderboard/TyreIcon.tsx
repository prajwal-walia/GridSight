import type { TyreCompound } from '../../store/driverStore'

interface Props {
  compound: TyreCompound
  age?: number
  size?: number
}

export const TYRE_COLORS: Record<TyreCompound, string> = {
  S: '#E8002D',
  M: '#FFF200',
  H: '#FFFFFF',
  I: '#39B54A',
  W: '#0067FF',
}

export default function TyreIcon({ compound, age, size = 28 }: Props) {
  const color = TYRE_COLORS[compound] || '#888'
  const isWet = compound === 'W'
  const isInter = compound === 'I'

  const dots = []
  if (!isWet && !isInter) {
    for (let i = 0; i < 8; i++) {
      const angle = (i * 45 * Math.PI) / 180
      const cx = 14 + 11.5 * Math.cos(angle)
      const cy = 14 + 11.5 * Math.sin(angle)
      dots.push(<circle key={i} cx={cx} cy={cy} r={1.2} fill={color} />)
    }
  }

  const treads = []
  if (isInter) {
    for (let i = 0; i < 12; i++) {
        const angle = (i * 30 * Math.PI) / 180
        const x1 = 14 + 10 * Math.cos(angle)
        const y1 = 14 + 10 * Math.sin(angle)
        const x2 = 14 + 13 * Math.cos(angle + 0.3)
        const y2 = 14 + 13 * Math.sin(angle + 0.3)
        treads.push(<line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={1} />)
    }
  } else if (isWet) {
    for (let i = 0; i < 6; i++) {
        const angle = (i * 60 * Math.PI) / 180
        const x1 = 14 + 8.5 * Math.cos(angle)
        const y1 = 14 + 8.5 * Math.sin(angle)
        const x2 = 14 + 13.5 * Math.cos(angle)
        const y2 = 14 + 13.5 * Math.sin(angle)
        treads.push(<line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={1.5} />)
    }
  }

  // Determine center letter color
  const letterIsBlack = compound === 'M' || compound === 'H'

  return (
    <div className="flex flex-col items-center justify-center gap-0.5">
      <svg width={size} height={size} viewBox="0 0 28 28" className="shrink-0 block">
        {/* Outer tyre block */}
        <circle cx="14" cy="14" r="14" fill="#1A1A1A" />
        
        {/* Color band */}
        <circle cx="14" cy="14" r="11" fill="none" stroke={color} strokeWidth="3" />
        
        {/* Tread details */}
        {dots}
        {treads}

        {/* Center dot so the letter is visible against the dark tyre */}
        {letterIsBlack && (
           <circle cx="14" cy="14" r="7.5" fill={color} />
        )}
        {(!letterIsBlack && !isInter && !isWet) && (
           <circle cx="14" cy="14" r="7.5" fill={color} />
        )}

        {/* Center letter */}
        <text 
          x="14" y="18.5" 
          fontSize="13" 
          fontWeight="900" 
          fontFamily="Arial, sans-serif" 
          textAnchor="middle" 
          fill={letterIsBlack ? '#000000' : '#FFFFFF'}
        >
          {compound}
        </text>
      </svg>
      {age != null && (
        <span className="text-[9px] font-bold leading-none" style={{ color }}>{age}</span>
      )}
    </div>
  )
}
