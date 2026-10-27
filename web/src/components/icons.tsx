import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function base(props: IconProps) {
  return {
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.7,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
    focusable: false,
    ...props,
  }
}

export const IconLink = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M10 13.5a4.5 4.5 0 0 0 6.36 0l1.77-1.77a4.5 4.5 0 1 0-6.36-6.36L10.7 6.44" />
    <path d="M14 10.5a4.5 4.5 0 0 0-6.36 0l-1.77 1.77a4.5 4.5 0 1 0 6.36 6.36l1.07-1.07" />
  </svg>
)

export const IconArrowRight = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M4.5 12h14" />
    <path d="m13 6.5 5.5 5.5L13 17.5" />
  </svg>
)

export const IconDownload = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M12 3.5v11" />
    <path d="m7.5 10 4.5 4.5 4.5-4.5" />
    <path d="M4.5 19.5h15" />
  </svg>
)

export const IconClock = (props: IconProps) => (
  <svg {...base(props)}>
    <circle cx="12" cy="12" r="8.25" />
    <path d="M12 7.75V12l2.75 1.75" />
  </svg>
)

export const IconAlert = (props: IconProps) => (
  <svg {...base(props)}>
    <circle cx="12" cy="12" r="8.25" />
    <path d="M12 7.75v5" />
    <path d="M12 16.1h.01" />
  </svg>
)

export const IconCheck = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="m5 12.5 4.5 4.5L19 6.5" />
  </svg>
)

export const IconRetry = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M20 11.5A8 8 0 1 0 18 17" />
    <path d="M20 4.5v7h-7" />
  </svg>
)

export const IconFilm = (props: IconProps) => (
  <svg {...base(props)}>
    <rect x="3.25" y="4.75" width="17.5" height="14.5" rx="2.5" />
    <path d="M3.25 8.5h17.5" />
    <path d="M3.25 15.5h17.5" />
    <path d="M8 4.75v14.5" />
    <path d="M16 4.75v14.5" />
  </svg>
)

export const IconClose = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="m6.5 6.5 11 11" />
    <path d="m17.5 6.5-11 11" />
  </svg>
)

export const IconPlay = (props: IconProps) => (
  <svg {...base(props)} fill="currentColor" stroke="none">
    <path d="M8.5 5.6a1 1 0 0 1 1.52-.86l8.2 6.4a1 1 0 0 1 0 1.72l-8.2 6.4a1 1 0 0 1-1.52-.86Z" />
  </svg>
)

// 尺寸由调用方的类决定（btn-icon / inline-icon…），这里只补旋转动画，
// 不能覆盖调用方传入的 className，否则 SVG 没有尺寸约束会撑满容器。
export const IconSpinner = ({ className, ...props }: IconProps) => (
  <svg
    {...base(props)}
    className={className ? `spin ${className}` : 'spin'}
    role="presentation"
  >
    <path d="M12 3.5a8.5 8.5 0 1 0 8.5 8.5" />
  </svg>
)

export const IconShield = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M12 3.5c2.6 1.4 4.7 1.9 7 2v6c0 4-2.9 7.2-7 9-4.1-1.8-7-5-7-9v-6c2.3-.1 4.4-.6 7-2Z" />
    <path d="m9 12 2.2 2.2L15.5 10" />
  </svg>
)
