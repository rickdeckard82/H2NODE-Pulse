import { forwardRef, useCallback, useEffect, useState } from "react";
import { actions, api, date } from "./api";

type Item = {
  id: string;
  ticket_id: string;
  number: number;
  subject: string;
  action: string;
  actor_name: string;
  created_at: string;
};
type Inbox = { muted: boolean; results: Item[] };

const labels: Record<string, string> = {
  created: "Novo chamado",
  claimed: "Chamado assumido",
  "comment.added": "Novo comentário",
  "requester.replied": "Resposta do solicitante",
  "comment.corrected": "Comentário corrigido",
  transferred: "Chamado transferido",
  "sla.breached": "Alerta de SLA",
  close: "Chamado encerrado pelo solicitante",
  confirm: "Solução confirmada",
  cancel: "Chamado cancelado",
  reopen: "Chamado reaberto",
  resolve: "Chamado resolvido",
  request_information: "Informações solicitadas",
  request_test: "Teste solicitado",
  return_queue: "Chamado devolvido à fila",
  "participant.joined": "Novo participante",
};

export const Notifications = forwardRef<
  HTMLDetailsElement,
  { onOpen: (ticket: string) => void }
>(function Notifications({ onOpen }, ref) {
  const [inbox, setInbox] = useState<Inbox>({ muted: false, results: [] });
  const [error, setError] = useState("");
  const load = useCallback(
    (request: Promise<Inbox>) =>
      request.then(
        (data) => {
          setError("");
          setInbox(data);
        },
        (err) => setError((err as Error).message),
      ),
    [],
  );
  useEffect(() => {
    const refresh = () => load(api<Inbox>("notifications/"));
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    return () => window.clearInterval(timer);
  }, [load]);
  const count = inbox.results.length;
  return (
    <details className="notify-menu" ref={ref}>
      <summary
        aria-label={`Notificações: ${count} ${inbox.muted ? "(silenciadas)" : ""}`}
      >
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
          <path
            d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20a2 2 0 0 0 4 0"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
          {inbox.muted && (
            <path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.8" />
          )}
        </svg>
        {count > 0 && (
          // Muted keeps the count visible but quiet, so pending items are never hidden.
          <span className={`notify-count${inbox.muted ? " muted-count" : ""}`}>
            {count > 9 ? "9+" : count}
          </span>
        )}
      </summary>
      <div className="notify-popover">
        <div className="notify-head">
          <strong>Notificações</strong>
          <button
            className="link"
            onClick={() =>
              load(
                api<Inbox>("notifications/", { muted: !inbox.muted }, "PATCH"),
              )
            }
          >
            {inbox.muted ? "Reativar" : "Silenciar"}
          </button>
          <button
            className="link"
            disabled={!count}
            onClick={() => load(api<Inbox>("notifications/clear/", {}))}
          >
            Limpar
          </button>
        </div>
        {error && <p role="alert">{error}</p>}
        {!count && <p className="muted">Nenhuma notificação.</p>}
        <ul>
          {inbox.results.map((n) => (
            <li key={n.id}>
              <button
                onClick={(event) => {
                  event.currentTarget
                    .closest("details")
                    ?.removeAttribute("open");
                  void load(api<Inbox>(`notifications/${n.id}/read/`, {}));
                  onOpen(n.ticket_id);
                }}
              >
                <strong>
                  {labels[n.action] || actions[n.action] || n.action} · #
                  {n.number}
                </strong>
                <span>{n.subject}</span>
                <small>
                  {n.actor_name} · {date(n.created_at)}
                </small>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
});
