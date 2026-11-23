import './Card.css'

export function Card({ className, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={['ui-card', className].filter(Boolean).join(' ')} {...rest} />
}

export function Tile({
  tone = 'neutral',
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { tone?: 'neutral' | 'accent' }) {
  return (
    <div className={['ui-tile', `ui-tile--${tone}`, className].filter(Boolean).join(' ')} {...rest} />
  )
}

export function Banner({
  tone = 'danger',
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { tone?: 'danger' | 'success' | 'warning' }) {
  return (
    <div className={['ui-banner', `ui-banner--${tone}`, className].filter(Boolean).join(' ')} {...rest} />
  )
}
