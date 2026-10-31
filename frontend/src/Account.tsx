import { useState } from "react";
import { api, type User } from "./api";

export function Account({
  user,
  onChanged,
}: {
  user: User;
  onChanged: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">PERFIL</p>
          <h1>{user.first_name}</h1>
          <p>{user.email}</p>
        </div>
      </div>
      <section className="panel narrow">
        <h2>{pending ? "Confirmar novo e-mail" : "Alterar e-mail"}</h2>
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
        {pending ? (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (busy) return;
              setBusy(true);
              setError("");
              try {
                await api(
                  "auth/confirm-email/",
                  Object.fromEntries(new FormData(e.currentTarget)),
                );
                setNotice(
                  "Novo e-mail confirmado. Entre novamente com o endereço atualizado.",
                );
                onChanged();
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Código recebido no novo e-mail
              <input
                name="token"
                required
                autoComplete="one-time-code"
                maxLength={128}
              />
            </label>
            <button disabled={busy}>
              {busy ? "Confirmando…" : "Confirmar novo e-mail"}
            </button>
            <button
              type="button"
              className="link"
              onClick={() => {
                setPending(false);
                setError("");
                setNotice("");
              }}
            >
              Cancelar
            </button>
          </form>
        ) : (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (busy) return;
              setBusy(true);
              setError("");
              try {
                await api(
                  "auth/email/",
                  Object.fromEntries(new FormData(e.currentTarget)),
                );
                setPending(true);
                setNotice(
                  "Enviamos um código ao novo e-mail, quando o endereço é elegível.",
                );
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Novo e-mail corporativo
              <input name="email" type="email" required autoComplete="email" />
            </label>
            <label>
              Senha atual
              <input
                name="password"
                type="password"
                required
                autoComplete="current-password"
              />
            </label>
            <button disabled={busy}>
              {busy ? "Enviando…" : "Enviar código de confirmação"}
            </button>
          </form>
        )}
      </section>
    </>
  );
}
