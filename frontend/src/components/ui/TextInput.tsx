import { forwardRef, useId } from 'react'
import './TextInput.css'

export interface TextInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
}

// Renders the label/input pair with shared styling. All native input props
// (type, autocomplete, aria-*, etc.) pass straight through to the <input> -
// callers migrating auth forms must not lose those semantics.
export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { label, id, className, ...rest },
  ref,
) {
  const generatedId = useId()
  const inputId = id ?? generatedId

  return (
    <div className="ui-field">
      {label && (
        <label className="ui-field__label" htmlFor={inputId}>
          {label}
        </label>
      )}
      <input ref={ref} id={inputId} className={['ui-field__input', className].filter(Boolean).join(' ')} {...rest} />
    </div>
  )
})
