import { useEffect, useState } from "react";
import { api, date } from "./api";

const periods = [
  ["tickets_days", "tickets", "Chamados encerrados"],
  ["users_days", "users", "Usuários desativados"],
  ["groups_days", "groups", "Grupos desativados"],
  ["categories_days", "categories", "Categorias desativadas"],
  ["departments_days", "departments", "Áreas desativadas"],
  ["logs_days", "logs", "Logs do sistema"],
] as const;

type Counts = Record<(typeof periods)[number][1], number>;
type Policy = Record<(typeof periods)[number][0], number> & {
  enabled: boolean;
  last_run_at: string | null;
  last_result: { removed?: Counts; waiting?: Counts };
  preview: Counts;
  next_run_at: string | null;
};

export function RetentionSettings() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    api<Policy>("settings/retention/")
      .then(setPolicy)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <section className="panel narrow">
      <h2>Retenção de dados</h2>
      <p role="note" className="error">
        Depois do prazo, os dados são apagados definitivamente e não podem ser
        recuperados pelo sistema. Revise os prazos com o jurídico antes de
        ativar.
      </p>
      <p>
        Informe os dias de guarda, contados do encerramento, da desativação ou
        do registro. Use 0 para não remover, ou pelo menos 30 dias. Registros
        ainda usados por outros dados aguardam esses dados expirarem.
      </p>
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
      {!policy ? (
        <p>Carregando configuração…</p>
      ) : (
        <form
          key={revision}
          onSubmit={async (event) => {
            event.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            setNotice("");
            const data = new FormData(event.currentTarget);
            try {
              const result = await api<Policy>(
                "settings/retention/",
                {
                  enabled: data.has("enabled"),
                  ...Object.fromEntries(
                    periods.map(([key]) => [key, Number(data.get(key))]),
                  ),
                  confirmation: data.get("confirmation"),
                  reason: data.get("reason"),
                },
                "PATCH",
              );
              setPolicy(result);
              setRevision((value) => value + 1);
              setNotice("Política de retenção salva.");
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {periods.map(([key, count, label]) => (
            <div key={key}>
              <label>
                {label} (dias)
                <input
                  name={key}
                  type="number"
                  min={0}
                  max={36500}
                  required
                  defaultValue={policy[key]}
                  aria-describedby={`${key}-hint`}
                />
              </label>
              <small id={`${key}-hint`} className="field-hint">
                {policy[key]
                  ? `${policy.preview[count]} já passaram do prazo salvo.`
                  : "Sem remoção."}
              </small>
            </div>
          ))}
          <label className="checkbox">
            <input
              type="checkbox"
              name="enabled"
              defaultChecked={policy.enabled}
            />
            Ativar a remoção automática
          </label>
          <label>
            Para ativar, digite REMOVER
            <input name="confirmation" maxLength={20} autoComplete="off" />
          </label>
          <label>
            Justificativa da alteração
            <input name="reason" required maxLength={300} />
          </label>
          <small>
            {policy.next_run_at
              ? `Próxima execução a partir de ${date(policy.next_run_at)}. Toda alteração reinicia uma carência de 24 horas.`
              : "Remoção automática desativada."}
          </small>
          {policy.last_run_at && (
            <small>
              Última execução em {date(policy.last_run_at)}:{" "}
              {periods
                .map(
                  ([, count, label]) =>
                    `${label}: ${policy.last_result.removed?.[count] ?? 0}`,
                )
                .join(" · ")}
            </small>
          )}
          <button disabled={busy}>
            {busy ? "Salvando…" : "Salvar retenção"}
          </button>
        </form>
      )}
    </section>
  );
}
