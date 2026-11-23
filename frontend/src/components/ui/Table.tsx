import './Table.css'

export function Table({ className, ...rest }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="ui-table-scroll">
      <table className={['ui-table', className].filter(Boolean).join(' ')} {...rest} />
    </div>
  )
}
