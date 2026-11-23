import { forwardRef, useId } from 'react'
import './TextInput.css'

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, id, className, children, ...rest },
  ref,
) {
  const generatedId = useId()
  const selectId = id ?? generatedId

  return (
    <div className="ui-field">
      {label && (
        <label className="ui-field__label" htmlFor={selectId}>
          {label}
        </label>
      )}
      <select
        ref={ref}
        id={selectId}
        className={['ui-field__input', className].filter(Boolean).join(' ')}
        {...rest}
      >
        {children}
      </select>
    </div>
  )
})
