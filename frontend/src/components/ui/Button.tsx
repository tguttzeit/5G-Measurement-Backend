import { forwardRef } from 'react'
import './Button.css'

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'
type ButtonSize = 'sm' | 'md'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', className, type = 'button', ...rest },
  ref,
) {
  const classes = ['ui-button', `ui-button--${variant}`, `ui-button--${size}`, className]
    .filter(Boolean)
    .join(' ')

  return <button ref={ref} type={type} className={classes} {...rest} />
})
