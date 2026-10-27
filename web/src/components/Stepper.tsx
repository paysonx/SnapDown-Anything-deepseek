import { Fragment } from 'react'

import { IconCheck } from './icons'

export interface Step {
  id: string
  label: string
  state: 'todo' | 'active' | 'done'
  percent?: number | null
}

export function Stepper({ steps }: { steps: Step[] }) {
  if (steps.length === 0) return null

  return (
    <ol className="steps" aria-label="下载阶段">
      {steps.map((step, index) => (
        <Fragment key={step.id}>
          {index > 0 ? (
            <li
              className={`step-line ${steps[index - 1]?.state === 'done' ? 'is-done' : ''}`}
              aria-hidden="true"
            />
          ) : null}
          <li
            className={`step step-${step.state}`}
            aria-current={step.state === 'active' ? 'step' : undefined}
          >
            <span className="step-dot" aria-hidden="true">
              {step.state === 'done' ? <IconCheck /> : index + 1}
            </span>
            <span className="step-label">{step.label}</span>
            {step.percent !== null && step.percent !== undefined && step.state === 'active' ? (
              <span className="step-percent">{Math.floor(step.percent)}%</span>
            ) : null}
          </li>
        </Fragment>
      ))}
    </ol>
  )
}
