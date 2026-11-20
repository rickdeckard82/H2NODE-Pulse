import { useEffect, useRef, useState } from "react";
import { api } from "./api";
type TurnstileApi = {
  render: (
    el: HTMLElement,
    opts: {
      sitekey: string;
      callback: (token: string) => void;
      "expired-callback": () => void;
      "error-callback": () => void;
    },
  ) => string;
  reset: (id?: string) => void;
  remove: (id?: string) => void;
};
declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}
const TURNSTILE_MODES = ["login", "register", "forgot"];
const TURNSTILE_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
function loadTurnstile(): Promise<TurnstileApi> {
  return new Promise((resolve, reject) => {
    if (window.turnstile) return resolve(window.turnstile);
    let script = document.querySelector<HTMLScriptElement>(
      `script[src="${TURNSTILE_SRC}"]`,
    );
    if (!script) {
      script = document.createElement("script");
      script.src = TURNSTILE_SRC;
      script.async = true;
      document.head.appendChild(script);
    }
    script.addEventListener("load", () =>
      window.turnstile ? resolve(window.turnstile) : reject(new Error("x")),
    );
    script.addEventListener("error", () => reject(new Error("x")));
  });
}
function TurnstileWidget({
  siteKey,
  onToken,
  resetSignal,
}: {
  siteKey: string;
  onToken: (token: string) => void;
  resetSignal: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const widget = useRef<string | undefined>(undefined);
  const cb = useRef(onToken);
  useEffect(() => {
    cb.current = onToken;
  });
  useEffect(() => {
    let cancelled = false;
    loadTurnstile()
      .then((t) => {
        if (cancelled || !box.current) return;
        widget.current = t.render(box.current, {
          sitekey: siteKey,
          callback: (token) => cb.current(token),
          "expired-callback": () => cb.current(""),
          "error-callback": () => cb.current(""),
        });
      })
      .catch(() => cb.current(""));
    return () => {
      cancelled = true;
      if (widget.current !== undefined)
        window.turnstile?.remove(widget.current);
    };
  }, [siteKey]);
  useEffect(() => {
    if (resetSignal && widget.current !== undefined) {
      cb.current("");
      window.turnstile?.reset(widget.current);
    }
  }, [resetSignal]);
  return <div ref={box} className="turnstile" />;
}
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
  const [siteKey, setSiteKey] = useState("");
  const [tsToken, setTsToken] = useState("");
  const [tsReset, setTsReset] = useState(0);
  useEffect(() => {
    fetch("/api/v1/auth/csrf/", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setSiteKey(d.turnstileSiteKey || ""))
      .catch(() => undefined);
  }, []);
  const needsTs = !!siteKey && !mfa && TURNSTILE_MODES.includes(mode);
  return (
    <div className="auth-layout">
      <section className="welcome">
        <p className="eyebrow pulse-eyebrow">
          <span className="pulse-status-dot" aria-hidden="true" />
          H2NODE PULSE · SUPORTE INTERNO
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
            delete data["cf-turnstile-response"];
            if (needsTs) {
              if (!tsToken) {
                setError("Conclua a verificação de segurança.");
                setBusy(false);
                return;
              }
              data.turnstile_token = tsToken;
            }
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
              if (needsTs) setTsReset((n) => n + 1);
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
              {["login", "confirm", "reset"].includes(mode) && (
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
              {["confirm", "reset"].includes(mode) && (
                <small id="password-hint" className="field-hint">
                  Use pelo menos 8 caracteres e evite senhas comuns, somente
                  números ou parecidas com seu nome ou e-mail.
                </small>
              )}
            </>
          )}
          {needsTs && (
            <TurnstileWidget
              siteKey={siteKey}
              onToken={setTsToken}
              resetSignal={tsReset}
            />
          )}
          <button disabled={busy || (needsTs && !tsToken)}>
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
