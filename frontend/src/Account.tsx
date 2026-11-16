import { useState } from "react";
import { api, type User } from "./api";
import { MfaSettings } from "./MfaSettings";
import { PasswordChange } from "./PasswordChange";

// Re-encoding on a canvas crops to a square, shrinks the upload and drops EXIF metadata.
async function toAvatar(file: File) {
  const bitmap = await createImageBitmap(file);
  const side = Math.min(bitmap.width, bitmap.height);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const context = canvas.getContext("2d")!;
  context.fillStyle = "white";
  context.fillRect(0, 0, 256, 256);
  context.drawImage(
    bitmap,
    (bitmap.width - side) / 2,
    (bitmap.height - side) / 2,
    side,
    side,
    0,
    0,
    256,
    256,
  );
  return canvas.toDataURL("image/jpeg", 0.85);
}

export function Account({
  user,
  onChanged,
  onPasswordChanged,
}: {
  user: User;
  onChanged: (user: User) => void;
  onPasswordChanged: () => void;
}) {
  const [avatar, setAvatar] = useState(user.avatar);
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
        <h2>Foto e nome</h2>
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
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            setNotice("");
            try {
              const updated = await api<User>(
                "auth/me/",
                {
                  first_name: new FormData(e.currentTarget).get("first_name"),
                  avatar,
                  email_notifications:
                    new FormData(e.currentTarget).get("email_notifications") ===
                    "on",
                },
                "PATCH",
              );
              setNotice("Perfil atualizado.");
              onChanged(updated);
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="profile-photo">
            {avatar ? (
              <img className="avatar large" src={avatar} alt="Sua foto" />
            ) : (
              <span className="avatar large" aria-hidden="true">
                {user.first_name.trim().charAt(0).toUpperCase() || "U"}
              </span>
            )}
            <label className="secondary file-button">
              Escolher imagem
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={async (e) => {
                  const file = e.currentTarget.files?.[0];
                  if (!file) return;
                  try {
                    setAvatar(await toAvatar(file));
                  } catch {
                    setError("Não foi possível ler essa imagem.");
                  }
                }}
              />
            </label>
            {avatar && (
              <button
                type="button"
                className="link"
                onClick={() => setAvatar("")}
              >
                Remover foto
              </button>
            )}
          </div>
          <label>
            Nome
            <input
              name="first_name"
              required
              maxLength={150}
              defaultValue={user.first_name}
              autoComplete="name"
            />
          </label>
          <label>
            E-mail corporativo
            <input value={user.email} readOnly aria-describedby="email-hint" />
            <small id="email-hint">
              O e-mail da conta não pode ser alterado.
            </small>
          </label>
          <label className="check">
            <input
              type="checkbox"
              name="email_notifications"
              defaultChecked={user.email_notifications}
            />
            Receber por e-mail as notificações dos chamados
          </label>
          <small>
            Não afeta e-mails de segurança da conta, como confirmação de
            cadastro e redefinição de senha. O sino do portal continua ativo.
          </small>
          <button disabled={busy}>
            {busy ? "Salvando…" : "Salvar perfil"}
          </button>
        </form>
      </section>
      <PasswordChange embedded onCompleted={onPasswordChanged} />
      <MfaSettings user={user} onChanged={onChanged} />
    </>
  );
}
