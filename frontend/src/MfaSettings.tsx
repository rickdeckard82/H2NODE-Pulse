import { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, type User } from "./api";

export function MfaSettings({
  user,
  onChanged,
}: {
  user: User;
  onChanged: (user: User) => void;
}) {
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(
    null,
  );
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const path = user.mfa_enabled
    ? "auth/mfa/disable/"
    : setup
      ? "auth/mfa/enable/confirm/"
      : "auth/mfa/enable/";

  return (
    <section className="panel narrow">
      <h2>Verificação em duas etapas</h2>
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
      {codes.length ? (
        <>
          <p>
            Guarde seus códigos de recuperação em local seguro. Cada código pode
            ser usado uma vez.
          </p>
          <ul>
            {codes.map((code) => (
              <li key={code}>
                <code>{code}</code>
              </li>
            ))}
          </ul>
          <button onClick={() => setCodes([])}>Guardei os códigos</button>
        </>
      ) : (
        <form
          key={path}
          onSubmit={async (event) => {
            event.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            setNotice("");
            try {
              const result = await api<{
                secret?: string;
                uri?: string;
                recovery_codes?: string[];
              }>(path, Object.fromEntries(new FormData(event.currentTarget)));
              if (result.secret && result.uri) {
                setSetup({ secret: result.secret, uri: result.uri });
                return;
              }
              setSetup(null);
              setCodes(result.recovery_codes ?? []);
              setNotice(
                user.mfa_enabled
                  ? "Verificação em duas etapas desativada."
                  : "Verificação em duas etapas ativada.",
              );
              onChanged(await api<User>("auth/me/"));
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <p>
            {user.mfa_enabled
              ? "Ativa. Desativar deixa a conta protegida só pela senha."
              : "Inativa. Ative para pedir um código do aplicativo autenticador ao entrar."}{" "}
            Ao concluir, suas outras sessões serão encerradas.
          </p>
          {setup && (
            <>
              <p>Escaneie o QR Code com seu aplicativo autenticador:</p>
              <div className="mfa-qr">
                <QRCodeSVG
                  value={setup.uri}
                  size={224}
                  marginSize={4}
                  level="M"
                  title="QR Code para cadastrar o autenticador"
                />
              </div>
              <p>Ou digite a chave manualmente:</p>
              <code className="secret">{setup.secret}</code>
            </>
          )}
          {!setup && (
            <label>
              Sua senha
              <input
                type="password"
                name="password"
                autoComplete="current-password"
                required
                maxLength={256}
              />
            </label>
          )}
          {(setup || user.mfa_enabled) && (
            <label>
              {setup
                ? "Código do autenticador"
                : "Código do autenticador ou de recuperação"}
              <input
                name="code"
                autoComplete="one-time-code"
                required
                maxLength={64}
              />
            </label>
          )}
          <button disabled={busy}>
            {busy
              ? "Aguarde…"
              : user.mfa_enabled
                ? "Desativar verificação"
                : setup
                  ? "Confirmar código"
                  : "Ativar verificação"}
          </button>
        </form>
      )}
    </section>
  );
}
