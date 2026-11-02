import { useCallback, useEffect, useRef, useState } from "react";
import {
  all,
  api,
  ApiError,
  date,
  states,
  type Page,
  type Ticket,
  type User,
} from "./api";
import { TicketDetail } from "./TicketDetail";
type Category = { id: number; name: string; restricted: boolean };
export function Portal({
  user,
  onExpired,
  open,
}: {
  user: User;
  onExpired: () => void;
  open?: string;
}) {
  const [selected, setSelected] = useState<string | null>(open ?? null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent("pulse:page-change"));
  }, [selected]);
  const [page, setPage] = useState<Page<Ticket> | null>(null);
  const [query, setQuery] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const createKey = useRef(crypto.randomUUID());
  const load = useCallback(async () => {
    setError("");
    try {
      setPage(await api<Page<Ticket>>(`tickets/?${query}`));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [query]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    all<Category>("categories/")
      .then(setCategories)
      .catch((err) => setError(err.message));
  }, []);
  if (selected)
    return (
      <TicketDetail
        id={selected}
        user={user}
        back={() => {
          setSelected(null);
          void load();
        }}
        onExpired={onExpired}
      />
    );
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {user.role === "collaborator"
              ? "PORTAL DO COLABORADOR"
              : "CONSOLE DE ATENDIMENTO"}
          </p>
          <h1>
            {user.role === "collaborator"
              ? "Meus chamados"
              : "Fila de chamados"}
          </h1>
          <p>Um atendimento próximo, do primeiro contato à solução.</p>
        </div>
        <button onClick={() => setCreating(!creating)}>
          {creating ? "Voltar à lista" : "Abrir chamado"}
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {creating ? (
        <section className="panel narrow">
          <h2>Novo chamado</h2>
          <p>
            Descreva o que precisa. Não envie senhas, segredos ou dados pessoais
            desnecessários.
          </p>
          <form
            onChange={() => {
              createKey.current = crypto.randomUUID();
            }}
            onSubmit={async (e) => {
              e.preventDefault();
              if (busy) return;
              setBusy(true);
              setError("");
              const data = Object.fromEntries(new FormData(e.currentTarget));
              try {
                const result = await api<{ ticket_id: string }>(
                  "tickets/",
                  {
                    ...data,
                    category: Number(data.category),
                    impact: Number(data.impact),
                    urgency: Number(data.urgency),
                  },
                  "POST",
                  createKey.current,
                );
                setSelected(result.ticket_id);
                setCreating(false);
                createKey.current = crypto.randomUUID();
              } catch (err) {
                setError((err as Error).message);
                if (err instanceof ApiError && err.status === 403) onExpired();
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Categoria
              <select name="category" required defaultValue="">
                <option value="" disabled>
                  Selecione
                </option>
                {categories.map((c) => (
                  <option value={c.id} key={c.id}>
                    {c.name}
                    {c.restricted ? " · Acesso restrito" : ""}
                  </option>
                ))}
              </select>
            </label>
            {!categories.length && (
              <p role="status">
                Nenhuma categoria disponível. Solicite a configuração à
                administração.
              </p>
            )}
            <label>
              Assunto
              <input name="subject" required maxLength={200} />
            </label>
            <label>
              Descrição
              <textarea
                name="description"
                required
                maxLength={10000}
                rows={5}
              />
            </label>
            <div className="two-columns">
              <label>
                Impacto
                <select name="impact" defaultValue="1">
                  <option value="1">Baixo · uma pessoa</option>
                  <option value="2">Médio · equipe</option>
                  <option value="3">Alto · organização</option>
                </select>
              </label>
              <label>
                Urgência
                <select name="urgency" defaultValue="1">
                  <option value="1">Baixa</option>
                  <option value="2">Média</option>
                  <option value="3">Alta</option>
                </select>
              </label>
            </div>
            <button disabled={busy || !categories.length}>
              {busy ? "Enviando…" : "Criar chamado"}
            </button>
          </form>
        </section>
      ) : (
        <>
          <form
            className="filters panel"
            onSubmit={(e) => {
              e.preventDefault();
              const values = new FormData(e.currentTarget);
              const params = new URLSearchParams();
              values.forEach((v, k) => {
                if (v) params.set(k, String(v));
              });
              setQuery(params.toString());
            }}
          >
            <label>
              Buscar
              <input name="search" placeholder="Assunto ou descrição" />
            </label>
            <label>
              Estado
              <select name="state">
                <option value="">Todos os estados</option>
                {Object.entries(states).map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Prioridade
              <select name="priority">
                <option value="">Todas</option>
                {[1, 2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    P{n}
                  </option>
                ))}
              </select>
            </label>
            {user.role !== "collaborator" && (
              <>
                <label>
                  Área (ID)
                  <input type="number" min="1" name="department" />
                </label>
                <label>
                  Responsável (ID)
                  <input type="number" min="1" name="assignee" />
                </label>
              </>
            )}
            <button>Filtrar</button>
            <button
              type="button"
              className="secondary"
              onClick={() => void load()}
            >
              Atualizar lista
            </button>
          </form>
          <section aria-label="Lista de chamados" className="ticket-list">
            {!page ? (
              <p role="status">Carregando chamados…</p>
            ) : !page.results.length ? (
              <div className="panel empty">
                <h2>Nenhum chamado encontrado</h2>
                <p>Abra uma solicitação ou ajuste os filtros.</p>
              </div>
            ) : (
              page.results.map((t) => (
                <button
                  className="ticket-row"
                  key={t.id}
                  onClick={() => setSelected(t.id)}
                >
                  <span className="ticket-number">#{t.number}</span>
                  <span className="ticket-summary">
                    <strong>{t.subject}</strong>
                    <small>
                      {t.requester_name} · {date(t.created_at)}
                    </small>
                  </span>
                  <span className={`badge state-${t.state}`}>
                    {states[t.state]}
                  </span>
                  <span>P{t.priority}</span>
                  <span className="row-assignee">
                    {t.assignee_name || "Sem responsável"} →
                  </span>
                </button>
              ))
            )}
          </section>
          {page && (
            <nav className="pagination" aria-label="Paginação">
              <button
                className="secondary"
                disabled={!page.previous}
                onClick={() =>
                  setQuery(new URL(page.previous!).searchParams.toString())
                }
              >
                Anterior
              </button>
              <span>{page.count} chamado(s)</span>
              <button
                className="secondary"
                disabled={!page.next}
                onClick={() =>
                  setQuery(new URL(page.next!).searchParams.toString())
                }
              >
                Próxima
              </button>
            </nav>
          )}
        </>
      )}
    </>
  );
}
