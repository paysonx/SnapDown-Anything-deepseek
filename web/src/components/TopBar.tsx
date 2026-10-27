import type { ProxyStatus } from '../lib/types'

interface TopBarProps {
  proxy: ProxyStatus | null
  connected: boolean
}

function proxyLabel(proxy: ProxyStatus | null): { text: string; tone: string } {
  if (!proxy) return { text: '正在读取网络状态', tone: 'muted' }
  if (proxy.available && proxy.selected) {
    return { text: `代理可用 · ${proxy.selected}`, tone: 'success' }
  }
  if (proxy.mode === 'direct') return { text: '直连模式', tone: 'success' }
  return { text: '代理不可用', tone: 'danger' }
}

export function TopBar({ proxy, connected }: TopBarProps) {
  const { text, tone } = proxyLabel(proxy)

  return (
    <header className="topbar">
      <div className="brand">
        <img className="brand-mark" src="/logo.png" alt="" width={40} height={40} />
        <div className="brand-text">
          <span className="brand-name">SnapDown</span>
          <span className="brand-sub">ANYTHING</span>
        </div>
      </div>

      <div className="topbar-status">
        <span className={`status-chip status-${tone}`}>
          <span className="status-dot" aria-hidden="true" />
          {text}
        </span>
        <span
          className={`status-chip status-${connected ? 'success' : 'muted'}`}
          title={connected ? '进度推送已连接' : '正在重连进度推送'}
        >
          <span className="status-dot" aria-hidden="true" />
          {connected ? '实时连接' : '重连中'}
        </span>
      </div>
    </header>
  )
}
