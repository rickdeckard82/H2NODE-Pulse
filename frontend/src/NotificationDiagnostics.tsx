import { useEffect, useState } from "react";
import { api, date } from "./api";

type Delivery = {
  id: number;
  ticket_number: number;
  event_action: string;
  channel: string;
  recipient: string;
  status: string;
  attempts: number;
  next_attempt_at: string;
  last_attempt_at: string | null;
  sent_at: string | null;
  provider_id: string;
  last_error_code: string;
};

type Check = {
  id: number;
  channel: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  error_code: string;
};

const labels: Record<string, string> = {
  pending: "Pendente",
  retry: "Nova tentativa agendada",
  sent: "Enviada",
  failed: "Falha definitiva",
  suppressed: "Suprimida por autorização",
};

export function NotificationDiagnostics() {
  const [rows, setRows] = useState<Delivery[]>([]);
  const [checks, setChecks] = useState<Check[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const load = () =>
    Promise.all([
      api<Delivery[]>("settings/notifications/").then(setRows),
      api<Check[]>("settings/notifications/test/").then(setChecks),
    ]).catch((err) => setError(err.message));
  useEffect(() => void load(), []);

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>Diagnóstico de notificações</h2>
          <p>
            Últimas 200 entregas. Destinatários aparecem mascarados e erros são
            sanitizados.
          </p>
        </div>
        <button className="secondary" onClick={() => void load()}>
          Atualizar
        </button>
      </div>
      <div className="action-list">
        {(["email", "chat"] as const).map((channel) => (
          <button
            key={channel}
            className="secondary"
            disabled={busy === -1}
            onClick={async () => {
              const reason = window.prompt(
                "Justificativa do teste controlado:",
              );
              if (!reason) return;
              setBusy(-1);
              setError("");
              setNotice("");
              try {
                await api("settings/notifications/test/", { channel, reason });
                setNotice(
                  "Teste enfileirado para o worker. Atualize em alguns segundos para ver o resultado.",
                );
                await load();
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(null);
              }
            }}
          >
            {channel === "email" ? "Testar e-mail" : "Testar Google Chat"}
          </button>
        ))}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      {checks.length > 0 && (
        <ul className="admin-list">
          {checks.map((check) => (
            <li key={check.id}>
              <div>
                <strong>
                  Teste de{" "}
                  {check.channel === "email" ? "e-mail" : "Google Chat"} ·{" "}
                  {labels[check.status] || check.status}
                </strong>
                <small>
                  {date(check.created_at)}
                  {check.error_code ? ` · código: ${check.error_code}` : ""}
                </small>
              </div>
            </li>
          ))}
        </ul>
      )}
      {!rows.length ? (
        <p>Nenhuma entrega processada.</p>
      ) : (
        <ul className="admin-list">
          {rows.map((row) => (
            <li key={row.id}>
              <div>
                <strong>
                  #{row.ticket_number} ·{" "}
                  {row.channel === "email" ? "E-mail" : "Google Chat"} ·{" "}
                  {labels[row.status] || row.status}
                </strong>
                <small>
                  {row.recipient} · {row.attempts} tentativa(s)
                  {row.last_attempt_at
                    ? ` · última: ${date(row.last_attempt_at)}`
                    : ""}
                  {row.last_error_code
                    ? ` · código: ${row.last_error_code}`
                    : ""}
                </small>
              </div>
              {["failed", "retry"].includes(row.status) && (
                <button
                  className="secondary"
                  disabled={busy === row.id}
                  onClick={async () => {
                    const reason = window.prompt(
                      "Justificativa para reenviar:",
                    );
                    if (!reason) return;
                    setBusy(row.id);
                    setError("");
                    try {
                      await api(`settings/notifications/${row.id}/retry/`, {
                        reason,
                      });
                      setNotice("Entrega recolocada na fila.");
                      await load();
                    } catch (err) {
                      setError((err as Error).message);
                    } finally {
                      setBusy(null);
                    }
                  }}
                >
                  Reenviar
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
