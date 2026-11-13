import { useCallback, useEffect, useRef, useState } from "react";
import {
  actions,
  all,
  api,
  ApiError,
  date,
  priorityName,
  states,
  type Attachment,
  type Event,
  type Ticket,
  type User,
} from "./api";
export function TicketDetail({
  id,
  user,
  back,
  onExpired,
}: {
  id: string;
  user: User;
  back: () => void;
  onExpired: () => void;
}) {
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [files, setFiles] = useState<Attachment[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [targets, setTargets] = useState<
    { group: number; group_name: string; user: number; user_name: string }[]
  >([]);
  const [action, setAction] = useState("");
  const [visibility, setVisibility] = useState("public");
  const key = useRef(crypto.randomUUID());
  const load = useCallback(async () => {
    const [t, e, f] = await Promise.all([
      api<Ticket>(`tickets/${id}/`),
      all<Event>(`tickets/${id}/events/`),
      all<Attachment>(`tickets/${id}/attachments/`),
    ]);
    setTicket(t);
    setEvents(e);
    setFiles(f);
    if (t.can_transfer)
      setTargets(await all(`tickets/${id}/transfer-options/`));
  }, [id]);
  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [load]);
  async function send(path: string, data: object | FormData) {
    if (busy) return false;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`tickets/${id}/${path}/`, data, "POST", key.current);
      key.current = crypto.randomUUID();
      await load();
      setNotice("Alteração registrada.");
      setAction("");
      return true;
    } catch (err) {
      setError((err as Error).message);
      if (err instanceof ApiError && err.status === 409) {
        key.current = crypto.randomUUID();
        await load();
      }
      if (
        err instanceof ApiError &&
        err.status === 403 &&
        !(await api<User>("auth/me/").catch(() => null))
      )
        onExpired();
      return false;
    } finally {
      setBusy(false);
    }
  }
  if (!ticket)
    return (
      <>
        <button className="secondary" onClick={back}>
          Voltar aos chamados
        </button>
        <p role={error ? "alert" : "status"}>
          {error || "Carregando chamado…"}
        </p>
      </>
    );
  const owner = ticket.requester === user.id;
  const support =
    !owner && ["technician", "manager", "admin"].includes(user.role);
  const terminal = ["closed", "cancelled"].includes(ticket.state);
  const working =
    ticket.assignee === user.id ||
    ticket.participants.some((p) => p.id === user.id);
  const available = [
    ...(support && ticket.state === "new" ? ["claim"] : []),
    ...(support &&
    !working &&
    ["in_progress", "waiting_information", "waiting_test"].includes(
      ticket.state,
    )
      ? ["join"]
      : []),
    ...(support && ticket.state === "in_progress"
      ? ["request_information", "request_test", "resolve"]
      : []),
    ...(owner && ticket.state === "resolved" ? ["confirm"] : []),
    ...(((owner || support) &&
      ["in_progress", "waiting_information", "waiting_test"].includes(
        ticket.state,
      )) ||
    (support && ticket.state === "resolved")
      ? ["close"]
      : []),
    ...((owner || support) && ["resolved", "closed"].includes(ticket.state)
      ? ["reopen"]
      : []),
    ...((owner && ticket.state === "new") ||
    (support && ticket.can_cancel && !terminal)
      ? ["cancel"]
      : []),
    ...(support && ticket.can_transfer && !terminal
      ? ["transfer", ...(ticket.state !== "new" ? ["return_queue"] : [])]
      : []),
  ];
  return (
    <>
      <button className="link back" onClick={back}>
        ← Voltar aos chamados
      </button>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            CHAMADO #{ticket.number}
            {ticket.restricted ? " · ACESSO RESTRITO" : ""}
          </p>
          <h1>{ticket.subject}</h1>
          <span className={`badge state-${ticket.state}`}>
            {states[ticket.state]}
          </span>
        </div>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => load().catch((err) => setError(err.message))}
        >
          Atualizar chamado
        </button>
      </div>
      {error && !action && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      <div className="detail-grid">
        <div>
          <section className="panel">
            <h2>Solicitação</h2>
            <p className="preserve">{ticket.description}</p>
            <p className="muted">
              {ticket.requester_name} · {date(ticket.created_at)}
            </p>
            {(ticket.client_ip || ticket.client_os) && (
              <p className="muted">
                Informado com autorização do solicitante:
                {ticket.client_ip && ` IP ${ticket.client_ip}`}
                {ticket.client_ip && ticket.client_os && " ·"}
                {ticket.client_os && ` ${ticket.client_os}`}
              </p>
            )}
          </section>
          <section className="panel timeline">
            <h2>Histórico do atendimento</h2>
            {events.map((e) => (
              <article
                key={e.id}
                className={
                  e.visibility === "internal" ? "event internal" : "event"
                }
              >
                <div>
                  <strong>{e.actor_name}</strong>{" "}
                  <span className="muted">{date(e.created_at)}</span>
                </div>
                <p className="event-label">
                  {e.visibility === "internal"
                    ? "NOTA INTERNA · Apenas equipe autorizada"
                    : "Registro público"}{" "}
                  ·{" "}
                  {actions[e.action] ||
                    (
                      {
                        created: "Abertura",
                        claimed: "Atribuição",
                        "comment.added": "Comentário",
                        "requester.replied": "Resposta do solicitante",
                        "comment.corrected": "Correção",
                        "sla.breached": "Alerta de SLA",
                      } as Record<string, string>
                    )[e.action] ||
                    e.action}
                </p>
                {e.comment && (
                  <p className="preserve">
                    {e.comment.corrects && (
                      <strong>Correção de comentário anterior: </strong>
                    )}
                    {e.comment.body}
                  </p>
                )}
                {files
                  .filter((f) => f.comment === e.comment?.id)
                  .map((f) => (
                    <div className="attachment" key={f.id}>
                      {f.status === "clean" ? (
                        <a
                          href={`/api/v1/tickets/${id}/attachments/${f.id}/download/`}
                        >
                          Baixar {f.name}
                        </a>
                      ) : (
                        <span>
                          {f.name} ·{" "}
                          {f.status === "blocked"
                            ? "Bloqueado"
                            : "Em quarentena, aguardando verificação"}
                        </span>
                      )}
                      <small>{Math.ceil(f.size / 1024)} KiB</small>
                    </div>
                  ))}
              </article>
            ))}
          </section>
          {!terminal && (owner || support) && (
            <section
              className={`panel ${visibility === "internal" ? "internal" : ""}`}
            >
              <h2>
                {visibility === "internal"
                  ? "Escrever nota interna"
                  : ticket.state === "waiting_test" && owner
                    ? "Informar resultado do teste"
                    : ticket.state === "waiting_information" && owner
                      ? "Enviar informações"
                      : "Responder ao chamado"}
              </h2>
              <form
                onChange={() => {
                  key.current = crypto.randomUUID();
                }}
                onSubmit={async (e) => {
                  e.preventDefault();
                  const form = e.currentTarget;
                  const data = new FormData(form);
                  const file = data.get("file") as File;
                  if (
                    visibility === "internal" &&
                    !data.has("confirm_internal")
                  ) {
                    setError("Confirme o destino da nota interna.");
                    return;
                  }
                  if (file?.size > 5 * 1024 * 1024) {
                    setError("Limite do anexo: 5 MiB.");
                    return;
                  }
                  data.delete("confirm_internal");
                  data.set("expected_version", String(ticket.version));
                  data.set("visibility", visibility);
                  const success = file?.size
                    ? await send("attachments", data)
                    : await send("comments", {
                        body: data.get("body"),
                        visibility,
                        expected_version: ticket.version,
                      });
                  if (success) {
                    form.reset();
                    setVisibility("public");
                  }
                }}
              >
                {support && (
                  <label>
                    Destino
                    <select
                      value={visibility}
                      onChange={(e) => setVisibility(e.target.value)}
                    >
                      <option value="public">
                        Resposta pública · solicitante e equipe
                      </option>
                      <option value="internal">
                        Nota interna · apenas equipe autorizada
                      </option>
                    </select>
                  </label>
                )}
                <label>
                  Mensagem
                  <textarea name="body" required rows={4} maxLength={8000} />
                </label>
                <label>
                  Anexo opcional
                  <input
                    type="file"
                    name="file"
                    accept=".txt,.pdf,.png,.jpg,.jpeg"
                  />
                </label>
                <small>
                  TXT, PDF, PNG ou JPEG, até 5 MiB. Disponível somente após
                  verificação. Não envie senhas ou dados desnecessários.
                </small>
                {visibility === "internal" && (
                  <label className="checkbox">
                    <input name="confirm_internal" type="checkbox" required />
                    Confirmo: publicar somente para a equipe autorizada.
                  </label>
                )}
                <button disabled={busy}>
                  {busy
                    ? "Enviando…"
                    : visibility === "internal"
                      ? "Publicar nota interna"
                      : "Enviar resposta pública"}
                </button>
              </form>
            </section>
          )}
        </div>
        <aside>
          <section className="panel">
            <h2>Atendimento</h2>
            <dl>
              <dt>Responsável</dt>
              <dd>{ticket.assignee_name || "Aguardando atribuição"}</dd>
              {ticket.participants.length > 0 && (
                <>
                  <dt>Participantes</dt>
                  <dd>{ticket.participants.map((p) => p.name).join(", ")}</dd>
                </>
              )}
              <dt>Prioridade</dt>
              <dd>{priorityName(ticket.priority)}</dd>
              {ticket.rating && (
                <>
                  <dt>Avaliação do solicitante</dt>
                  <dd>
                    <span className="stars" aria-hidden="true">
                      {"★".repeat(ticket.rating)}
                      {"☆".repeat(5 - ticket.rating)}
                    </span>{" "}
                    {ticket.rating} de 5 · {ratingLabels[ticket.rating - 1]}
                  </dd>
                </>
              )}
              <dt>Área na abertura</dt>
              <dd>{ticket.department_name || "Não informada"}</dd>
              <dt>Próxima ação</dt>
              <dd>
                {["waiting_test", "waiting_information", "resolved"].includes(
                  ticket.state,
                )
                  ? "Solicitante"
                  : terminal
                    ? "Atendimento encerrado"
                    : "Equipe de suporte"}
              </dd>
            </dl>
            <div className="action-list">
              {available.map((a) => (
                <button
                  disabled={busy}
                  className="secondary"
                  key={a}
                  onClick={() => {
                    key.current = crypto.randomUUID();
                    setError("");
                    setAction(a);
                  }}
                >
                  {actions[a]}
                </button>
              ))}
            </div>
          </section>
          {action && (
            <dialog
              className="about-dialog"
              aria-labelledby="action-title"
              ref={(el) => {
                if (el && !el.open) el.showModal();
              }}
              onClose={() => setAction("")}
            >
              <h2 id="action-title">{actions[action]}</h2>
              {error && (
                <p className="error" role="alert">
                  {error}
                </p>
              )}
              <form
                onChange={() => {
                  key.current = crypto.randomUUID();
                }}
                onSubmit={(e) => {
                  e.preventDefault();
                  const values = Object.fromEntries(
                    new FormData(e.currentTarget),
                  );
                  const target = String(values.target || "").split(":");
                  delete values.target;
                  const rating = values.rating ? Number(values.rating) : null;
                  delete values.rating;
                  const payload = {
                    ...values,
                    expected_version: ticket.version,
                    ...(action === "transfer"
                      ? {
                          group: Number(target[0]),
                          assignee: Number(target[1]),
                        }
                      : ["claim", "join"].includes(action)
                        ? {}
                        : { action }),
                    ...(rating ? { rating } : {}),
                  };
                  void send(
                    ["claim", "join", "transfer"].includes(action)
                      ? action
                      : "transitions",
                    payload,
                  );
                }}
              >
                {!["claim", "join", "confirm"].includes(action) && (
                  <label>
                    Mensagem pública
                    <textarea name="message" required maxLength={8000} />
                  </label>
                )}
                {action === "confirm" && (
                  <StarRating legend="Como foi a solução?" />
                )}
                {action === "close" && owner && (
                  <StarRating legend="Como foi o atendimento?" />
                )}
                {action === "transfer" && (
                  <label>
                    Destino do atendimento
                    <select name="target" required defaultValue="">
                      <option value="" disabled>
                        {targets.length
                          ? "Selecione grupo e técnico"
                          : "Nenhum técnico disponível nos seus grupos"}
                      </option>
                      {targets.map((t) => (
                        <option
                          key={`${t.group}:${t.user}`}
                          value={`${t.group}:${t.user}`}
                        >
                          {t.group_name} · {t.user_name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <p>
                  A ação e sua mensagem ficam registradas no histórico público.
                </p>
                <button disabled={busy}>Confirmar ação</button>
                <button
                  type="button"
                  className="link"
                  onClick={() => setAction("")}
                >
                  Voltar
                </button>
              </form>
            </dialog>
          )}
        </aside>
      </div>
    </>
  );
}

const ratingLabels = ["Ruim", "Fraca", "Regular", "Boa", "Ótima"];

function StarRating({ legend }: { legend: string }) {
  const [value, setValue] = useState(0);
  return (
    <fieldset className="star-rating">
      <legend>{legend}</legend>
      <div>
        {ratingLabels.map((label, i) => (
          <label key={label} className={i < value ? "on" : ""}>
            <input
              type="radio"
              name="rating"
              value={i + 1}
              required
              className="sr-only"
              onChange={() => setValue(i + 1)}
            />
            <span aria-hidden="true">★</span>
            <span className="sr-only">
              {i + 1} {i ? "estrelas" : "estrela"} · {label}
            </span>
          </label>
        ))}
      </div>
      <small aria-live="polite">
        {value
          ? ratingLabels[value - 1]
          : "1 estrela = ruim · 5 estrelas = ótima"}
      </small>
    </fieldset>
  );
}
