import { useId, useState, type FormEvent } from 'react'

import { IconAlert, IconArrowRight, IconLink, IconSpinner } from './icons'

interface ComposerProps {
  busy: boolean
  error: string | null
  onSubmit: (text: string) => void
}

const PLATFORMS = [
  { name: 'B站', route: '直连' },
  { name: '抖音', route: '直连' },
  { name: 'YouTube', route: '代理' },
]

export function Composer({ busy, error, onSubmit }: ComposerProps) {
  const [text, setText] = useState('')
  const inputId = useId()
  const errorId = useId()

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    const value = text.trim()
    if (!value || busy) return
    onSubmit(value)
  }

  return (
    <form className="composer" onSubmit={handleSubmit} noValidate>
      <div className="field-row">
        <div className="field">
          <IconLink className="field-icon" />
          <label className="sr-only" htmlFor={inputId}>
            视频链接
          </label>
          <input
            id={inputId}
            className="field-input"
            type="text"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            placeholder="粘贴视频链接，或直接粘贴抖音分享文案"
            value={text}
            onChange={(event) => setText(event.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            disabled={busy}
          />
        </div>
        <button className="btn btn-primary btn-parse" type="submit" disabled={busy || !text.trim()}>
          {busy ? <IconSpinner className="btn-icon" /> : null}
          {busy ? '解析中' : '解析'}
          {!busy ? <IconArrowRight className="btn-icon" /> : null}
        </button>
      </div>

      {error ? (
        <p className="form-error" id={errorId} role="alert">
          <IconAlert className="form-error-icon" />
          <span>{error}</span>
        </p>
      ) : null}

      <div className="composer-foot">
        <div className="chip-row" aria-label="支持的平台">
          <span className="chip-label">支持</span>
          {PLATFORMS.map((item) => (
            <span className="chip" key={item.name}>
              {item.name}
              <span className={`chip-route chip-route-${item.route === '代理' ? 'proxy' : 'direct'}`}>
                {item.route}
              </span>
            </span>
          ))}
        </div>
      </div>
    </form>
  )
}
