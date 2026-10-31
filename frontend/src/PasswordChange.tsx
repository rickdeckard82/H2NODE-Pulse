import { useState } from "react";
import { api } from "./api";

export function PasswordChange({ onCompleted }: { onCompleted: () => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">SEGURANÇA</p>
          <h1>Alterar senha</h1>
          <p>
            Ao concluir, suas sessões e dispositivos lembrados serão revogados.
          </p>
        </div>
      </div>
      <section className="panel narrow">
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (busy) return;
            const data = new FormData(event.currentTarget);
            if (data.get("new_password") !== data.get("confirm_password")) {
              setError("A confirmação não corresponde à nova senha.");
              return;
            }
            setBusy(true);
            setError("");
            try {
              await api("auth/password/", {
                current_password: data.get("current_password"),
                new_password: data.get("new_password"),
              });
              onCompleted();
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Senha atual
            <input
              name="current_password"
              type="password"
              required
              autoComplete="current-password"
              maxLength={256}
            />
          </label>
          <label>
            Nova senha
            <input
              name="new_password"
              type="password"
              required
              autoComplete="new-password"
              maxLength={256}
            />
          </label>
          <label>
            Confirmar nova senha
            <input
              name="confirm_password"
              type="password"
              required
              autoComplete="new-password"
              maxLength={256}
            />
          </label>
          <button disabled={busy}>
            {busy ? "Alterando…" : "Alterar senha"}
          </button>
        </form>
      </section>
    </>
  );
}
