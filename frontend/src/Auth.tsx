import { useState } from "react";
import { api } from "./api";
const modes: Record<string, string> = {
  login: "Entrar",
  register: "Criar conta",
  confirm: "Confirme seu cadastro",
  forgot: "Recuperar senha",
  reset: "Definir nova senha",
};
export function Auth({
  onLogin,
  initialNotice = "",
}: {
  onLogin: () => void;
  initialNotice?: string;
}) {
  const [mode, setMode] = useState("login");
  const [mfa, setMfa] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(initialNotice);
  const [busy, setBusy] = useState(false);
  const [pendingEmail, setPendingEmail] = useState("");
  return (
    <div className="auth-layout">
      <section className="welcome">
        <p className="eyebrow pulse-eyebrow">
          <span className="pulse-status-dot" aria-hidden="true" />
          PULSE SERVICES · SUPORTE INTERNO
        </p>
        <h1>
          Seu suporte.
          <br />
          Mais próximo.
        </h1>
        <p>
          Abra um chamado, acompanhe o atendimento e encontre a solução junto
          com a TI.
        </p>
        <ul>
          <li>Um lugar para suas solicitações</li>
          <li>Histórico de cada atendimento</li>
          <li>Informações protegidas por acesso</li>
        </ul>
      </section>
      <section className="panel auth-panel" aria-label="Acesso ao portal">
        <h2>{mfa ? "Verificação em duas etapas" : modes[mode]}</h2>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        <form
          key={mode + mfa}
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            setNotice("");
            const data: Record<string, unknown> = Object.fromEntries(
              new FormData(e.currentTarget),
            );
            if (mfa) data.remember_device = data.remember_device === "on";
            try {
              const result = await api<{
                status?: string;
                detail?: string;
              }>(`auth/${mfa ? "mfa/verify" : mode}/`, data);
              if (result.status === "authenticated") onLogin();
              else if (result.status === "completed") {
                setMode("login");
                setNotice(
                  mode === "reset"
                    ? "Senha alterada. Entre com a nova senha."
                    : "Cadastro confirmado. Agora você já pode entrar.",
                );
              } else if (result.status === "mfa_required") {
                setMfa(true);
              } else if (mode === "register") {
                setPendingEmail(String(data.email || ""));
                setMode("confirm");
                setNotice(
                  "Enviamos o código de confirmação para o e-mail informado, quando o cadastro é elegível.",
                );
              } else if (mode === "forgot") {
                setMode("reset");
                setNotice(
                  "Enviamos o código de recuperação para o e-mail informado, quando a conta é elegível.",
                );
              } else
                setNotice(
                  result.detail ||
                    "Solicitação processada. Verifique seu e-mail, quando aplicável.",
                );
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {mfa ? (
            <>
              <label>
                Código do autenticador ou de recuperação
                <input
                  name="code"
                  autoComplete="one-time-code"
                  required
                  maxLength={64}
                />
              </label>
              <label className="checkbox">
                <input name="remember_device" type="checkbox" />
                Lembrar este dispositivo por 30 dias
              </label>
              <small>
                Use apenas em um dispositivo pessoal. A senha continuará sendo
                solicitada.
              </small>
            </>
          ) : (
            <>
              {mode === "register" && (
                <label>
                  Nome
                  <input
                    name="name"
                    autoComplete="name"
                    required
                    maxLength={150}
                  />
                </label>
              )}
              {["login", "register", "forgot"].includes(mode) && (
                <label>
                  E-mail corporativo
                  <input
                    type="email"
                    name="email"
                    autoComplete="username"
                    required
                  />
                </label>
              )}
              {["confirm", "reset"].includes(mode) && (
                <label>
                  Código recebido por e-mail
                  <input
                    name="token"
                    required
                    autoComplete="off"
                    maxLength={128}
                  />
                </label>
              )}
              {["login", "register", "reset"].includes(mode) && (
                <label>
                  Senha
                  <input
                    type="password"
                    name="password"
                    autoComplete={
                      mode === "login" ? "current-password" : "new-password"
                    }
                    required
                    maxLength={256}
                    aria-describedby={
                      mode === "login" ? undefined : "password-hint"
                    }
                  />
                </label>
              )}
              {["register", "reset"].includes(mode) && (
                <small id="password-hint" className="field-hint">
                  Use pelo menos 8 caracteres e evite senhas comuns, somente
                  números ou parecidas com seu nome ou e-mail.
                </small>
              )}
            </>
          )}
          <button disabled={busy}>
            {busy ? "Aguarde…" : mfa ? "Verificar código" : modes[mode]}
          </button>
        </form>
        {!mfa && (
          <nav className="auth-links" aria-label="Opções de acesso">
            {Object.entries(modes)
              .filter(
                ([key]) =>
                  key !== mode && ["login", "register", "forgot"].includes(key),
              )
              .map(([key, label]) => (
                <button
                  className="link"
                  key={key}
                  onClick={() => {
                    setMode(key);
                    setError("");
                    setNotice("");
                  }}
                >
                  {label}
                </button>
              ))}
            {mode === "confirm" && pendingEmail && (
              <button
                className="link"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    await api("auth/resend/", { email: pendingEmail });
                    setNotice(
                      "Se o cadastro estiver elegível, um novo código será enviado.",
                    );
                  } catch (err) {
                    setError((err as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Reenviar código
              </button>
            )}
          </nav>
        )}
      </section>
    </div>
  );
}
