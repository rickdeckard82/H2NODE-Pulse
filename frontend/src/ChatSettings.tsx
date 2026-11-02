import { useEffect, useState } from "react";
import { api } from "./api";

type Configuration = {
  enabled: boolean;
  webhook_configured: boolean;
  updated_at: string | null;
};

export function ChatSettings() {
  const [config, setConfig] = useState<Configuration | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const load = () =>
    api<Configuration>("settings/chat/")
      .then(setConfig)
      .catch((err) => setError(err.message));
  useEffect(() => void load(), []);

  return (
    <section className="panel narrow">
      <h2>Google Chat</h2>
      <p>
        Publique no espaço da TI somente número, estado e link autenticado.
        Chamados restritos nunca são enviados ao espaço geral.
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
      {!config ? (
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
              const result = await api<Configuration>(
                "settings/chat/",
                {
                  webhook: data.get("webhook"),
                  clear_webhook: data.has("clear_webhook"),
                  enabled: data.has("enabled"),
                  reason: data.get("reason"),
                },
                "PATCH",
              );
              setConfig(result);
              setRevision((value) => value + 1);
              setNotice("Configuração do Google Chat salva.");
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Webhook do espaço
            <input
              name="webhook"
              type="password"
              autoComplete="new-password"
              placeholder="https://chat.googleapis.com/v1/spaces/…"
              maxLength={2048}
            />
          </label>
          <small>
            {config.webhook_configured
              ? "Webhook protegido e cadastrado. Deixe em branco para mantê-lo."
              : "Nenhum webhook cadastrado."}
          </small>
          <label className="checkbox">
            <input type="checkbox" name="clear_webhook" />
            Remover o webhook armazenado
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              name="enabled"
              defaultChecked={config.enabled}
            />
            Ativar notificações no espaço geral da TI
          </label>
          <label>
            Justificativa da alteração
            <input name="reason" required maxLength={300} />
          </label>
          <button disabled={busy}>
            {busy ? "Salvando…" : "Salvar Google Chat"}
          </button>
        </form>
      )}
    </section>
  );
}
