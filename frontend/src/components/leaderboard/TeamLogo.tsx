import MercedesLogo from '../../assets/logos/mercedes.svg?react'
import FerrariLogo from '../../assets/logos/ferrari.svg?react'
import RedBullLogo from '../../assets/logos/redbull.svg?react'
import McLarenLogo from '../../assets/logos/mclaren.svg?react'
import AstonMartinLogo from '../../assets/logos/astonmartin.svg?react'
import AlpineLogo from '../../assets/logos/alpine.svg?react'
import WilliamsLogo from '../../assets/logos/williams.svg?react'
import AlphaTauriLogo from '../../assets/logos/alphatauri.svg?react'
import AlfaRomeoLogo from '../../assets/logos/alfaromeo.svg?react'
import HaasLogo from '../../assets/logos/haas.svg?react'
import RBLogo from '../../assets/logos/rb_2024.svg?react'
import KickSauberLogo from '../../assets/logos/kicksauber.svg?react'
import RacingBullsLogo from '../../assets/logos/racingbulls.svg?react'
import AudiLogo from '../../assets/logos/audi.svg?react'
import CadillacLogo from '../../assets/logos/cadillac.svg?react'
import type { SVGProps } from 'react'

type SVGComponent = React.FC<SVGProps<SVGSVGElement>>

const LOGO_MAP: Record<string, SVGComponent> = {
  'Mercedes': MercedesLogo,
  'Ferrari': FerrariLogo,
  'Red Bull Racing': RedBullLogo,
  'McLaren': McLarenLogo,
  'Aston Martin': AstonMartinLogo,
  'Alpine': AlpineLogo,
  'Williams': WilliamsLogo,
  'AlphaTauri': AlphaTauriLogo,
  'Alfa Romeo': AlfaRomeoLogo,
  'Haas F1 Team': HaasLogo,
  'RB': RBLogo,
  'Kick Sauber': KickSauberLogo,
  'Racing Bulls': RacingBullsLogo,
  'Audi': AudiLogo,
  'Cadillac': CadillacLogo,
}

export default function TeamLogo({ team, size = 20 }: { team: string, size?: number }) {
  const Logo = LOGO_MAP[team]
  if (!Logo) return (
    <span style={{ color:'white', fontSize:9, fontWeight:'bold',
      width:size, display:'inline-block', textAlign:'center' }}>
      {team?.slice(0,3).toUpperCase()}
    </span>
  )
  return <Logo width={size} height={size}
    style={{ flexShrink:0, filter:'brightness(0) invert(1)' }} />
}
