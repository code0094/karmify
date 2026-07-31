import { useEffect } from "react";

export type ToastKind = "info" | "success" | "error";

export interface ToastMsg {
  id: number;
  kind: ToastKind;
  text: string;
}

export type PushToast = (kind: ToastKind, text: string) => void;

interface ToastStackProps {
  toasts: ToastMsg[];
  onDismiss: (id: number) => void;
}

export function ToastStack({ toasts, onDismiss }: ToastStackProps) {
  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function Toast({ toast, onDismiss }: { toast: ToastMsg; onDismiss: (id: number) => void }) {
  useEffect(() => {
    // Errors linger longer: they carry the "what went wrong" the user must read.
    const timer = setTimeout(() => onDismiss(toast.id), toast.kind === "error" ? 8000 : 4000);
    return () => clearTimeout(timer);
  }, [toast.id, toast.kind, onDismiss]);

  return (
    <div className={`toast toast-${toast.kind}`} onClick={() => onDismiss(toast.id)}>
      {toast.text}
    </div>
  );
}
