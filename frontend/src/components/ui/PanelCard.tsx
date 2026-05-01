/* ── PanelCard — reusable dark panel wrapper ──────────────────────────── */

interface Props {
  title: string
  children: React.ReactNode
  className?: string
}

export default function PanelCard({ title, children, className = '' }: Props) {
  return (
    <div
      className={`rounded-lg overflow-hidden ${className}`}
      style={{ background: '#12121A', border: '1px solid #1E1E2E' }}
    >
      {/* header with red accent bar */}
      <div
        className="flex items-center gap-2 px-3 py-1.5"
        style={{ borderBottom: '1px solid #1E1E2E' }}
      >
        <div className="w-1 self-stretch rounded-full" style={{ background: '#E10600' }} />
        <span className="text-[10px] font-extrabold tracking-widest text-gray-400">
          {title}
        </span>
      </div>

      {/* content */}
      {children}
    </div>
  )
}
