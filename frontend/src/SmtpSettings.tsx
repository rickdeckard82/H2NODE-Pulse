import { useEffect, useState } from "react";
import { api } from "./api";

type Configuration = {
  enabled: boolean;
  host: string;
  port: number;
  security: string;
  username: string;
  from_email: string;
  password_configured: boolean;
  source: string;
  updated_at: string | null;
};

export function SmtpSettings() {
  const [config, setConfig] = useState<Configuration | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const load = () =>
    api<Configuration>("settings/smtp/")
      .then(setConfig)
      .catch((err) => setError(err.message));
  useEffect(() => {
    void load();
  }, []);
  return (
    <section className="panel narrow">
      <h2>Servidor SMTP</h2>
      <p>
        Configure o envio de códigos de identidade e notificações de chamados.
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
        <>
          <p>Carregando configuração…</p>
          <button className="secondary" onClick={() => void load()}>
            Tentar novamente
          </button>
        </>
      ) : (
        <form
          key={revision}
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            setNotice("");
            const data = new FormData(e.currentTarget);
            const payload = {
              host: String(data.get("host")),
              port: Number(data.get("port")),
              security: data.get("security"),
              username: data.get("username"),
              from_email: data.get("from_email"),
              password: data.get("password"),
              clear_password: data.has("clear_password"),
              enabled: data.has("enabled"),
              reason: data.get("reason"),
            };
            try {
              const result = await api<Configuration>(
                "settings/smtp/",
                payload,
                "PATCH",
              );
              setConfig(result);
              setRevision((v) => v + 1);
              setNotice(
                "Configuração SMTP salva. Os próximos e-mails usarão os novos dados.",
              );
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {config.source === "environment" && (
            <p>
              Configuração ainda não salva no painel. Um SMTP definido pelo
              operador no ambiente continuará valendo até salvar aqui.
            </p>
          )}
          <label>
            Servidor SMTP (nome DNS)
            <input
              name="host"
              defaultValue={config.host}
              placeholder="smtp.seu-provedor.com"
              maxLength={253}
            />
          </label>
          <div className="two-columns">
            <label>
              Porta
              <select name="port" defaultValue={config.port}>
                {[25, 465, 587, 2525].map((port) => (
                  <option key={port} value={port}>
                    {port}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Segurança da conexão
              <select name="security" defaultValue={config.security}>
                <option value="starttls">
                  STARTTLS (normalmente porta 587)
                </option>
                <option value="ssl">
                  TLS implícito (normalmente porta 465)
                </option>
              </select>
            </label>
          </div>
          <label>
            Usuário SMTP
            <input
              name="username"
              autoComplete="off"
              defaultValue={config.username}
              maxLength={254}
            />
          </label>
          <label>
            Senha SMTP
            <input
              name="password"
              type="password"
              autoComplete="new-password"
              maxLength={1024}
            />
          </label>
          <small>
            {config.password_configured
              ? "Senha cadastrada. Deixe em branco para mantê-la."
              : "Nenhuma senha cadastrada no painel."}{" "}
            Para relay sem autenticação, mantenha usuário e senha vazios.
          </small>
          <label className="checkbox">
            <input type="checkbox" name="clear_password" />
            Remover a senha SMTP armazenada
          </label>
          <label>
            E-mail remetente
            <input
              name="from_email"
              type="email"
              defaultValue={config.from_email}
            />
          </label>
          <label className="checkbox">
            <input
              name="enabled"
              type="checkbox"
              defaultChecked={config.enabled}
            />
            Ativar envio de e-mails de identidade e chamados
          </label>
          <label>
            Justificativa da alteração
            <input name="reason" required maxLength={300} />
          </label>
          <button disabled={busy}>{busy ? "Salvando…" : "Salvar SMTP"}</button>
        </form>
      )}
    </section>
  );
}
