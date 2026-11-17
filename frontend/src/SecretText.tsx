import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { linkify } from "./WikiLinkPicker";

const TOKEN = /\[\[oculta:([0-9a-f-]{36})\]\]/g;

/** A password typed in a ticket: hidden until the viewer confirms their own password. */
function Hidden({
  ticketId,
  secretId,
}: {
  ticketId: string;
  secretId: string;
}) {
  const [asking, setAsking] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!value) return;
    // The revealed value goes back into hiding on its own.
    const timer = window.setTimeout(() => setValue(""), 30_000);
    return () => window.clearTimeout(timer);
  }, [value]);

  if (value)
    return (
      <span className="secret">
        <code>{value}</code>{" "}
        <button type="button" className="link" onClick={() => setValue("")}>
          Ocultar
        </button>
      </span>
    );
  return (
    <span className="secret">
      <span aria-label="Senha oculta">••••••••</span>{" "}
      {!asking ? (
        <button type="button" className="link" onClick={() => setAsking(true)}>
          Mostrar
        </button>
      ) : (
        <span className="secret-form">
          <input
            type="password"
            autoComplete="current-password"
            aria-label="Confirme a sua senha de acesso"
            placeholder="Sua senha de acesso"
            autoFocus
            onKeyDown={async (e) => {
              if (e.key !== "Enter") return;
              e.preventDefault();
              const field = e.currentTarget;
              if (busy || !field.value) return;
              setBusy(true);
              setError("");
              try {
                const result = await api<{ value: string }>(
                  `tickets/${ticketId}/secrets/${secretId}/reveal/`,
                  { password: field.value },
                );
                setValue(result.value);
                setAsking(false);
              } catch (err) {
                setError((err as Error).message);
                field.value = "";
              } finally {
                setBusy(false);
              }
            }}
          />{" "}
          <button
            type="button"
            className="link"
            onClick={() => {
              setAsking(false);
              setError("");
            }}
          >
            Cancelar
          </button>
          {error && (
            <small role="alert" className="error">
              {" "}
              {error}
            </small>
          )}
          <small> Digite a sua senha e pressione Enter.</small>
        </span>
      )}
    </span>
  );
}

/** Renders ticket text: placeholders become hidden passwords, wiki links become anchors. */
export function SecretText({
  text,
  ticketId,
}: {
  text: string;
  ticketId: string;
}) {
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    nodes.push(...linkify(text.slice(last, m.index)));
    nodes.push(<Hidden key={m.index} ticketId={ticketId} secretId={m[1]} />);
    last = m.index + m[0].length;
  }
  nodes.push(...linkify(text.slice(last)));
  return <>{nodes}</>;
}
