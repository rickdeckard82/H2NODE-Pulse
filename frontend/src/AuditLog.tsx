import { useEffect, useState } from "react";
import { all, api, date, type Page } from "./api";

type Row = {
  created_at: string;
  actor_id: number | null;
  actor_name: string | null;
  actor_email: string | null;
  action: string;
  source: "identity" | "ticket";
  subject: string;
  reason: string | null;
};
type Person = { id: number; first_name: string; email: string };

const labels: Record<string, string> = {
  "account.created": "Criou uma conta",
  "account.domain_disabled": "Contas afetadas por domínio desativado",
  "account.password_changed": "Alterou a senha",
  "account.profile_updated": "Atualizou o perfil",
  "account.registered": "Fez o cadastro",
  "account.updated": "Alterou uma conta",
  "bootstrap.admin_created": "Administrador inicial criado",
  "bootstrap.email_trusted": "E-mail do administrador inicial confirmado",
  "category.created": "Criou uma categoria",
  "category.updated": "Alterou uma categoria",
  "chat.linked": "Conectou o Google Chat",
  "chat.updated": "Alterou a configuração do Google Chat",
  "company.updated": "Alterou os dados da empresa",
  "device.remembered": "Lembrou um dispositivo",
  "domain.created": "Adicionou um domínio",
  "domain.deleted": "Removeu um domínio",
  "domain.updated": "Alterou um domínio",
  "integration.test_requested": "Pediu um teste de integração",
  "membership.created": "Adicionou membro a um grupo",
  "membership.deleted": "Removeu membro de um grupo",
  "membership.updated": "Alterou membro de um grupo",
  "mfa.disabled": "Desativou a verificação em duas etapas",
  "mfa.disabled_by_admin":
    "Desativou a verificação em duas etapas de uma conta",
  "mfa.enrolled": "Ativou a verificação em duas etapas",
  "mfa.recovery_used": "Usou um código de recuperação",
  "mfa.replaced": "Trocou a verificação em duas etapas",
  "mfa.setup_started": "Iniciou a verificação em duas etapas",
  "notification.requeued": "Reenviou uma notificação",
  "reopen_policy.created": "Criou política de reabertura",
  "report.downloaded": "Baixou um relatório",
  "retention.purged": "Remoção automática de dados executada",
  "retention.updated": "Alterou a política de retenção",
  "report.exported": "Exportou um relatório",
  "account.invite": "Aceitou o convite",
  "account.reset": "Redefiniu a senha",
  "account.verify": "Confirmou o e-mail",
  "session.forget_device": "Esqueceu o dispositivo confiável",
  "session.login": "Entrou no sistema",
  "session.login_failed": "Tentativa de login recusada",
  "session.login_mfa": "Entrou com verificação em duas etapas",
  "session.login_trusted_device": "Entrou por dispositivo confiável",
  "session.logout": "Saiu do sistema",
  "session.revoke": "Encerrou todas as sessões",
  "sla_policy.created": "Criou política de SLA",
  "smtp.updated": "Alterou a configuração de e-mail",
  cancel: "Cancelou o chamado",
  claimed: "Assumiu o chamado",
  close: "Encerrou o chamado",
  "comment.added": "Comentou no chamado",
  "comment.corrected": "Corrigiu um comentário",
  confirm: "Confirmou a solução",
  created: "Abriu o chamado",
  "participant.joined": "Entrou no atendimento",
  reopen: "Reabriu o chamado",
  "requester.replied": "Respondeu como solicitante",
  request_information: "Pediu informações",
  request_test: "Pediu um teste",
  resolve: "Resolveu o chamado",
  return_queue: "Devolveu o chamado à fila",
  "sla.breached": "Prazo de SLA estourado",
  transferred: "Transferiu o chamado",
};

export function AuditLog() {
  const [people, setPeople] = useState<Person[]>([]);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState<Page<Row> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    all<Person>("users/")
      .then(setPeople)
      .catch((err) => setError(err.message));
  }, []);
  useEffect(() => {
    let active = true;
    setError("");
    api<Page<Row>>(`settings/audit/?${query}`)
      .then((data) => {
        if (active) setPage(data);
      })
      .catch((err) => {
        if (active) setError(err.message);
      });
    return () => {
      active = false;
    };
  }, [query]);
  const go = (url: string | null) =>
    url && setQuery(new URL(url).searchParams.toString());

  return (
    <section className="panel">
      <h2>Log do sistema</h2>
      <p>Ações registradas, da mais recente para a mais antiga.</p>
      <form
        className="filters"
        onSubmit={(event) => {
          event.preventDefault();
          const params = new URLSearchParams();
          new FormData(event.currentTarget).forEach((value, key) => {
            if (value) params.set(key, String(value));
          });
          setQuery(params.toString());
        }}
      >
        <label>
          Usuário
          <select name="user" defaultValue="">
            <option value="">Todos</option>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.first_name
                  ? `${person.first_name} · ${person.email}`
                  : person.email}
              </option>
            ))}
          </select>
        </label>
        <label>
          De
          <input type="date" name="start" />
        </label>
        <label>
          Até
          <input type="date" name="end" />
        </label>
        <button>Filtrar</button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!page ? (
        <p role="status">Carregando log…</p>
      ) : !page.results.length ? (
        <p>Nenhum registro.</p>
      ) : (
        <>
          <p role="status">{page.count} registros</p>
          <ul className="admin-list">
            {page.results.map((row) => (
              <li key={`${row.created_at}-${row.action}-${row.subject}`}>
                <div>
                  <strong>
                    {labels[row.action] || row.action}
                    {row.source === "ticket" && ` #${row.subject}`}
                  </strong>
                  <small>
                    {date(row.created_at)} ·{" "}
                    {row.actor_id
                      ? `${row.actor_name || "Sem nome"} · ${row.actor_email}`
                      : row.action === "session.login_failed"
                        ? "E-mail não cadastrado"
                        : "Sistema"}
                  </small>
                  {row.reason && <small>Justificativa: {row.reason}</small>}
                </div>
              </li>
            ))}
          </ul>
          <div className="action-list">
            <button
              className="secondary"
              disabled={!page.previous}
              onClick={() => go(page.previous)}
            >
              Anterior
            </button>
            <button
              className="secondary"
              disabled={!page.next}
              onClick={() => go(page.next)}
            >
              Próxima
            </button>
          </div>
        </>
      )}
    </section>
  );
}
