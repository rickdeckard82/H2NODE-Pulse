import { useCallback, useEffect, useState } from "react";
import { api, date, states } from "./api";

type Clock = {
  met: number;
  breached: number;
  pending: number;
  average_minutes: number | null;
};
type Summary = {
  start: string;
  end: string;
  timezone: string;
  created: number;
  resolved: number;
  cancelled: number;
  closed: number;
  has_scope: boolean;
  reopened: number;
  backlog_at_end: number;
  without_policy: number;
  response: Clock;
  resolution: Clock;
  open_by_state: { state: string; count: number }[];
  open_by_group: { group__name: string; count: number }[];
  open_by_assignee: { assignee__first_name: string; count: number }[] | null;
};
type Export = { id: string; expires_at: string; rows: number };

const local = (value: Date) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(
    value,
  );

const minutesLabel = (value: number | null) =>
  value === null ? "—" : `${value} min`;

function rate(clock: Clock) {
  const decided = clock.met + clock.breached;
  return decided ? `${Math.round((clock.met / decided) * 100)}%` : "—";
}

function Counts({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; count: number }[];
}) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {rows.length ? (
        <ul className="admin-list">
          {rows.map((row) => (
            <li key={row.label}>
              <span>{row.label}</span>
              <strong>{row.count}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p>Nenhum chamado aberto.</p>
      )}
    </section>
  );
}

export function Reports() {
  const today = local(new Date());
  const [period, setPeriod] = useState({
    start: today.slice(0, 8) + "01",
    end: today,
  });
  const [summary, setSummary] = useState<Summary | null>(null);
  const [exported, setExported] = useState<Export | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setError("");
    try {
      setSummary(
        await api<Summary>(
          `reports/summary/?start=${period.start}&end=${period.end}`,
        ),
      );
    } catch (err) {
      setError((err as Error).message);
    }
  }, [period]);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">GESTÃO DO ATENDIMENTO</p>
          <h1>Relatórios e SLA</h1>
          <p>
            Indicadores dos grupos sob sua responsabilidade. Tempos em minutos
            úteis, conforme a política de SLA congelada em cada chamado.
          </p>
        </div>
      </div>
      <form
        className="panel filters"
        onSubmit={(e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          setExported(null);
          setPeriod({
            start: String(form.get("start")),
            end: String(form.get("end")),
          });
        }}
      >
        <label>
          Início
          <input
            type="date"
            name="start"
            required
            defaultValue={period.start}
          />
        </label>
        <label>
          Fim
          <input type="date" name="end" required defaultValue={period.end} />
        </label>
        <button>Atualizar relatório</button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              setExported(await api<Export>("reports/exports/", period));
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Gerando…" : "Exportar CSV"}
        </button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {exported && (
        <p role="status" className="notice">
          Arquivo com {exported.rows} chamado(s) pronto.{" "}
          <a href={`/api/v1/reports/exports/${exported.id}/`} download>
            Baixar CSV
          </a>{" "}
          (disponível até {date(exported.expires_at)}; o download é registrado).
        </p>
      )}
      {summary && (
        <>
          {!summary.has_scope && (
            <p className="notice" role="status">
              Sua conta ainda não participa de nenhum grupo, por isso o
              relatório está vazio. Peça a inclusão à administração.
            </p>
          )}
          <section className="panel" aria-label="Indicadores do período">
            <h2>
              Período de {summary.start.split("-").reverse().join("/")} a{" "}
              {summary.end.split("-").reverse().join("/")}
            </h2>
            <dl className="metrics">
              <div>
                <dt>Abertos no período</dt>
                <dd>{summary.created}</dd>
              </div>
              <div>
                <dt>Resoluções</dt>
                <dd>{summary.resolved}</dd>
              </div>
              <div>
                <dt>Fechados</dt>
                <dd>{summary.closed}</dd>
              </div>
              <div>
                <dt>Reaberturas</dt>
                <dd>{summary.reopened}</dd>
              </div>
              <div>
                <dt>Cancelados</dt>
                <dd>{summary.cancelled}</dd>
              </div>
              <div>
                <dt>Backlog no fim do período</dt>
                <dd>{summary.backlog_at_end}</dd>
              </div>
              <div>
                <dt>1ª resposta no prazo</dt>
                <dd>{rate(summary.response)}</dd>
              </div>
              <div>
                <dt>Resolução no prazo</dt>
                <dd>{rate(summary.resolution)}</dd>
              </div>
              <div>
                <dt>Média até 1ª resposta</dt>
                <dd>{minutesLabel(summary.response.average_minutes)}</dd>
              </div>
              <div>
                <dt>Média de resolução</dt>
                <dd>{minutesLabel(summary.resolution.average_minutes)}</dd>
              </div>
            </dl>
            <p>
              <small>
                SLA calculado sobre os chamados abertos no período: resposta{" "}
                {summary.response.met} no prazo, {summary.response.breached}{" "}
                fora e {summary.response.pending} em aberto ou sem medição;
                resolução {summary.resolution.met} no prazo,{" "}
                {summary.resolution.breached} fora e{" "}
                {summary.resolution.pending} em aberto ou sem medição.
                Cancelados não entram no SLA.{" "}
                {summary.without_policy > 0 &&
                  `${summary.without_policy} chamado(s) sem política de SLA. `}
                Fuso: {summary.timezone}.
              </small>
            </p>
          </section>
          <div className="detail-grid">
            <Counts
              title="Abertos agora por estado"
              rows={summary.open_by_state.map((r) => ({
                label: states[r.state] || r.state,
                count: r.count,
              }))}
            />
            <Counts
              title="Abertos agora por grupo"
              rows={summary.open_by_group.map((r) => ({
                label: r.group__name,
                count: r.count,
              }))}
            />
            {summary.open_by_assignee && (
              <Counts
                title="Abertos agora por técnico"
                rows={summary.open_by_assignee.map((r) => ({
                  label: r.assignee__first_name,
                  count: r.count,
                }))}
              />
            )}
          </div>
        </>
      )}
    </>
  );
}
