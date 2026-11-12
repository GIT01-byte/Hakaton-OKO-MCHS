export interface Toast {
  id: number
  title: string
  body: string
}

export default function Toasts({ toasts, onPick }: { toasts: Toast[]; onPick: (t: Toast) => void }) {
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <button key={t.id} className="toast" onClick={() => onPick(t)}>
          <b>{t.title}</b>
          <span>{t.body}</span>
        </button>
      ))}
    </div>
  )
}
