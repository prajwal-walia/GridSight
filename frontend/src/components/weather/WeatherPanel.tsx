import { useUIStore } from '../../store/uiStore'
import { Droplets, Wind, Thermometer, Sun, CloudRain } from 'lucide-react'

/* ── helpers ──────────────────────────────────────────────────────────── */

function getCompassDirection(degrees: number): string {
  if (degrees == null || isNaN(degrees)) return ''
  // 360 / 8 = 45 degree sectors. Offset by 22.5 to center the sectors on the cardinal points.
  const val = Math.floor((degrees / 45) + 0.5)
  const arr = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return arr[(val % 8)]
}

/* ── component ────────────────────────────────────────────────────────── */

export default function WeatherPanel() {
  const weather = useUIStore(s => s.weather)

  return (
    <div className="overflow-hidden" style={{ background: '#12121A' }}>
      {/* header */}
      <div
        className="px-3 py-1.5 text-[10px] font-extrabold tracking-widest"
        style={{ color: '#8E8EA0', borderBottom: '1px solid #1E1E2E' }}
      >
        ☁ WEATHER
      </div>

      <div className="p-3 grid grid-cols-2 gap-3">
        {/* air temp */}
        <Stat
          icon={<Thermometer size={13} className="text-orange-400" />}
          label="AIR TEMP"
          value={weather.air_temp != null ? `${weather.air_temp.toFixed(1)}°C` : '—'}
        />

        {/* track temp */}
        <Stat
          icon={<Sun size={13} className="text-yellow-400" />}
          label="TRACK TEMP"
          value={weather.track_temp != null ? `${weather.track_temp.toFixed(1)}°C` : '—'}
        />

        {/* humidity */}
        <Stat
          icon={<Droplets size={13} className="text-cyan-400" />}
          label="HUMIDITY"
          value={weather.humidity != null ? `${weather.humidity.toFixed(0)}%` : '—'}
        />

        {/* wind speed */}
        <Stat
          icon={<Wind size={13} className="text-teal-400" />}
          label="WIND"
          value={weather.wind_speed != null 
            ? `${weather.wind_speed.toFixed(0)} km/h${weather.wind_direction != null ? ` / ${getCompassDirection(weather.wind_direction)}` : ''}` 
            : '—'}
        />
      </div>

      {/* rainfall status */}
      <div
        className="flex items-center justify-center gap-2 px-3 py-2"
        style={{ borderTop: '1px solid #1E1E2E' }}
      >
        {weather.rainfall ? (
          <>
            <CloudRain size={16} className="text-blue-400 gs-rain-icon" />
            <span className="text-[10px] font-bold text-blue-400 tracking-wider">RAIN ACTIVE</span>
          </>
        ) : (
          <>
            <Sun size={16} className="text-amber-400" />
            <span className="text-[10px] font-bold text-gray-500 tracking-wider">DRY</span>
          </>
        )}
      </div>
    </div>
  )
}

/* ── stat cell ────────────────────────────────────────────────────────── */

function Stat(
  { icon, label, value }:
  { icon: React.ReactNode; label: string; value: string },
) {
  return (
    <div className="flex items-center gap-2">
      {icon}
      <div>
        <div className="text-[9px] text-gray-500 leading-none">{label}</div>
        <div
          className="text-xs font-bold leading-tight"
          style={{ color: '#e2e2e2' }}
        >
          {value}
        </div>
      </div>
    </div>
  )
}
