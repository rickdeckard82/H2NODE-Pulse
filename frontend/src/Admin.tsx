import { useEffect, useState } from "react";
import { all, api } from "./api";
import { SmtpSettings } from "./SmtpSettings";
type Field = { key: string; label: string; type?: string; options?: string[] };
type Resource = {
  label: string;
  path: string;
  fields: Field[];
  editable?: boolean;
  removable?: boolean;
  create?: boolean;
};
const name: Field = { key: "name", label: "Nome" };
const active: Field = { key: "is_active", label: "Ativo", type: "checkbox" };
const reason: Field = { key: "reason", label: "Justificativa" };
const group: Field = { key: "group", label: "Grupo (ID)", type: "number" };
const user: Field = { key: "user", label: "Usuário (ID)", type: "number" };
const resources: Resource[] = [
  { label: "SMTP", path: "settings/smtp", fields: [] },
  {
    label: "Áreas",
    path: "departments",
    fields: [name, active],
    editable: true,
    create: true,
  },
  {
    label: "Grupos",
    path: "groups",
    fields: [name, active],
    editable: true,
    create: true,
  },
  {
    label: "Categorias",
    path: "categories",
    fields: [
      name,
      group,
      { key: "restricted", label: "Acesso restrito", type: "checkbox" },
      active,
    ],
    editable: true,
    create: true,
  },
  {
    label: "Contas e perfis",
    path: "users",
    fields: [
      {
        key: "role",
        label: "Papel",
        options: ["collaborator", "technician", "manager", "admin", "privacy"],
      },
      {
        key: "department",
        label: "Área (ID, vazio para remover)",
        type: "number",
      },
      active,
      reason,
    ],
    editable: true,
  },
  {
    label: "Domínios de confiança",
    path: "settings/domains",
    fields: [
      { key: "domain", label: "Domínio corporativo exato" },
      active,
      reason,
    ],
    editable: true,
    create: true,
  },
  {
    label: "Membros dos grupos",
    path: "memberships",
    fields: [
      user,
      group,
      {
        key: "can_view_restricted",
        label: "Pode ver restritos",
        type: "checkbox",
      },
      { key: "can_transfer", label: "Pode transferir", type: "checkbox" },
      { key: "can_cancel", label: "Gestor pode cancelar", type: "checkbox" },
    ],
    removable: true,
    create: true,
  },
  {
    label: "Concessões de leitura",
    path: "settings/ticket-access",
    fields: [
      user,
      group,
      { key: "internal", label: "Notas internas", type: "checkbox" },
      { key: "restricted", label: "Restritos", type: "checkbox" },
    ],
    removable: true,
    create: true,
  },
  {
    label: "Política de reabertura",
    path: "settings/reopen-policies",
    fields: [
      { key: "hours", label: "Prazo em horas (0 desativa)", type: "number" },
      reason,
    ],
    create: true,
  },
];
type Row = Record<string, string | number | boolean | null>;
export function Admin() {
  const [resource, setResource] = useState(resources[1]);
  const [rows, setRows] = useState<Row[]>([]);
  const [editing, setEditing] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    setRows(await all<Row>(resource.path + "/"));
  }
  useEffect(() => {
    if (resource.path === "settings/smtp") return;
    let active = true;
    all<Row>(resource.path + "/")
      .then((data) => {
        if (active) setRows(data);
      })
      .catch((err) => {
        if (active) setError(err.message);
      });
    return () => {
      active = false;
    };
  }, [resource]);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">CONFIGURAÇÃO DO SERVIÇO</p>
          <h1>Administração</h1>
          <p>
            Gerencie a organização e os acessos. Alterações ficam auditadas.
          </p>
        </div>
      </div>
      <nav className="tabs" aria-label="Configurações">
        {resources.map((r) => (
          <button
            className={resource.path === r.path ? "selected" : "secondary"}
            key={r.path}
            onClick={() => {
              setResource(r);
              setEditing(null);
              setRows([]);
              setError("");
              setNotice("");
            }}
          >
            {r.label}
          </button>
        ))}
      </nav>
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
      {resource.path === "settings/smtp" ? (
        <SmtpSettings />
      ) : (
        <div className="detail-grid">
          <section className="panel">
            <h2>{resource.label}</h2>
            {!rows.length && <p>Nenhum registro.</p>}
            <ul className="admin-list">
              {rows.map((row) => (
                <li key={String(row.id)}>
                  <div>
                    <strong>
                      #{row.id} ·{" "}
                      {String(
                        row.name ||
                          row.email ||
                          row.domain ||
                          (row.user
                            ? `Usuário ${row.user} / Grupo ${row.group}`
                            : `${row.hours} horas`),
                      )}
                    </strong>
                    <small>
                      {resource.fields
                        .filter(
                          (f) => row[f.key] !== undefined && f.key !== "name",
                        )
                        .map((f) => `${f.label}: ${String(row[f.key])}`)
                        .join(" · ")}
                    </small>
                  </div>
                  {resource.editable && (
                    <button
                      className="secondary"
                      onClick={() => {
                        setEditing(row);
                        setError("");
                      }}
                    >
                      Editar #{row.id}
                    </button>
                  )}
                  {resource.removable && (
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={async () => {
                        if (!window.confirm(`Revogar acesso #${row.id}?`))
                          return;
                        setBusy(true);
                        try {
                          await api(
                            `${resource.path}/${row.id}/`,
                            {},
                            "DELETE",
                          );
                          await load();
                          setNotice("Acesso revogado.");
                        } catch (err) {
                          setError((err as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      Revogar #{row.id}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
          <section className="panel">
            <h2>{editing ? `Editar #${editing.id}` : "Novo registro"}</h2>
            {resource.create || editing ? (
              <form
                key={`${resource.path}/${editing?.id}`}
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (busy) return;
                  setBusy(true);
                  setError("");
                  const form = new FormData(e.currentTarget);
                  const data: Record<string, unknown> = {};
                  resource.fields.forEach((f) => {
                    data[f.key] =
                      f.type === "checkbox"
                        ? form.has(f.key)
                        : f.type === "number"
                          ? form.get(f.key)
                            ? Number(form.get(f.key))
                            : null
                          : form.get(f.key);
                  });
                  try {
                    await api(
                      `${resource.path}/${editing ? `${editing.id}/` : ""}`,
                      data,
                      editing ? "PATCH" : "POST",
                    );
                    setEditing(null);
                    await load();
                    setNotice("Configuração salva.");
                  } catch (err) {
                    setError((err as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {resource.fields.map((f) => (
                  <label
                    className={f.type === "checkbox" ? "checkbox" : ""}
                    key={f.key}
                  >
                    {f.type === "checkbox" ? (
                      <input
                        type="checkbox"
                        name={f.key}
                        defaultChecked={
                          editing
                            ? Boolean(editing[f.key])
                            : f.key === "is_active"
                        }
                      />
                    ) : null}
                    {f.label}
                    {f.options ? (
                      <select
                        name={f.key}
                        defaultValue={String(editing?.[f.key] || f.options[0])}
                      >
                        {f.options.map((v) => (
                          <option key={v}>{v}</option>
                        ))}
                      </select>
                    ) : f.type !== "checkbox" ? (
                      <input
                        type={f.type || "text"}
                        name={f.key}
                        min={f.key === "hours" ? 0 : 1}
                        required={f.key !== "department"}
                        defaultValue={String(editing?.[f.key] ?? "")}
                      />
                    ) : null}
                  </label>
                ))}
                <button disabled={busy}>
                  {busy ? "Salvando…" : "Salvar configuração"}
                </button>
                {editing && (
                  <button
                    type="button"
                    className="link"
                    onClick={() => setEditing(null)}
                  >
                    Cancelar edição
                  </button>
                )}
              </form>
            ) : (
              <p>
                Selecione uma conta para editar. Novas contas usam o cadastro
                corporativo.
              </p>
            )}
          </section>
        </div>
      )}
    </>
  );
}
