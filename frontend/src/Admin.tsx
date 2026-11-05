import { Fragment, useCallback, useEffect, useState } from "react";
import { all, api, priorities } from "./api";
import { AuditLog } from "./AuditLog";
import { ChatSettings } from "./ChatSettings";
import { CompanySettings } from "./CompanySettings";
import { NotificationDiagnostics } from "./NotificationDiagnostics";
import { SmtpSettings } from "./SmtpSettings";
type Field = {
  key: string;
  label: string;
  type?: string;
  // [value sent to the API, label shown to the administrator]
  options?: [string, string][];
  default?: string;
  optional?: boolean;
  hint?: string;
  // Picks a record by name instead of asking the administrator for its numeric id.
  ref?: "users" | "groups" | "departments";
  roles?: string[];
};
type Resource = {
  label: string;
  path: string;
  fields: Field[];
  editable?: boolean;
  removable?: boolean;
  removeLabel?: string;
  removeReason?: boolean;
  // Creation can ask for different data than editing (e.g. a new account's e-mail).
  createFields?: Field[];
  toggleActive?: boolean;
  create?: boolean;
  note?: string;
};
type Ref = {
  id: number;
  name?: string;
  first_name?: string;
  email?: string;
  role?: string;
  is_active?: boolean;
};
const name: Field = { key: "name", label: "Nome" };
const suggestion = (minutes: number) =>
  minutes < 60
    ? `${minutes} min`
    : `${minutes} min (${minutes / 60} h de expediente)`;
// Suggested targets are a starting point for the administrator, never applied automatically.
const slaFields: Field[] = (
  [
    [1, 30, 240],
    [2, 60, 480],
    [3, 240, 1200],
    [4, 480, 3000],
  ] as const
).flatMap(([priority, response, resolution]) => [
  {
    key: `p${priority}_response`,
    label: `${priorities[priority - 1][1]} · 1ª resposta (min úteis)`,
    type: "number",
    hint: `Sugestão: ${suggestion(response)}.`,
  },
  {
    key: `p${priority}_resolution`,
    label: `${priorities[priority - 1][1]} · resolução (min úteis)`,
    type: "number",
    hint: `Sugestão: ${suggestion(resolution)}. Não pode ser menor que a 1ª resposta.`,
  },
]);
const active: Field = { key: "is_active", label: "Ativo", type: "checkbox" };
const reason: Field = { key: "reason", label: "Justificativa" };
const group: Field = { key: "group", label: "Grupo", ref: "groups" };
const department: Field = {
  key: "department",
  label: "Área",
  ref: "departments",
  optional: true,
};
const versioned =
  "Cada versão é imutável e auditada; para mudar, salve uma nova versão. Chamados mantêm a versão vigente na abertura.";
const resources: Resource[] = [
  { label: "Empresa", path: "settings/company", fields: [] },
  { label: "SMTP", path: "settings/smtp", fields: [] },
  { label: "Google Chat", path: "settings/chat", fields: [] },
  { label: "Entregas", path: "settings/notifications", fields: [] },
  { label: "Log do sistema", path: "settings/audit", fields: [] },
  {
    label: "Áreas",
    path: "departments",
    fields: [name, active],
    editable: true,
    create: true,
    removable: true,
    toggleActive: true,
  },
  {
    label: "Grupos",
    path: "groups",
    fields: [name, active],
    editable: true,
    create: true,
    removable: true,
    toggleActive: true,
  },
  {
    label: "Categorias",
    path: "categories",
    fields: [
      name,
      group,
      {
        key: "priority",
        label: "Prioridade sugerida",
        type: "number",
        options: priorities,
        default: "3",
        hint: "Vem selecionada na abertura; o solicitante pode trocar.",
      },
      { key: "restricted", label: "Acesso restrito", type: "checkbox" },
      active,
    ],
    editable: true,
    create: true,
    removable: true,
    toggleActive: true,
  },
  {
    label: "Contas e perfis",
    path: "users",
    fields: [
      {
        key: "role",
        label: "Papel",
        options: [
          ["collaborator", "Colaborador"],
          ["technician", "Técnico"],
          ["manager", "Gestor"],
          ["admin", "Administrador"],
        ],
      },
      department,
      active,
      reason,
    ],
    createFields: [
      { key: "first_name", label: "Nome" },
      { key: "email", label: "E-mail corporativo", type: "email" },
      department,
      reason,
    ],
    editable: true,
    create: true,
    toggleActive: true,
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
    removable: true,
    removeReason: true,
    toggleActive: true,
  },
  {
    label: "Membros dos grupos",
    path: "memberships",
    fields: [
      {
        key: "user",
        label: "Técnico ou gestor",
        ref: "users",
        roles: ["technician", "manager"],
      },
      group,
      {
        key: "can_view_restricted",
        label: "Pode ver restritos",
        type: "checkbox",
      },
      { key: "can_transfer", label: "Pode transferir", type: "checkbox" },
      { key: "can_cancel", label: "Gestor pode cancelar", type: "checkbox" },
    ],
    editable: true,
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
    note: versioned,
  },
  {
    label: "Política de SLA",
    path: "settings/sla-policies",
    fields: [
      {
        key: "timezone",
        label: "Fuso horário (IANA)",
        default: "America/Sao_Paulo",
      },
      {
        key: "weekdays",
        label: "Dias úteis (0 = segunda … 6 = domingo)",
        default: "0,1,2,3,4",
      },
      {
        key: "start_time",
        label: "Início do expediente",
        type: "time",
        default: "08:00",
      },
      {
        key: "end_time",
        label: "Fim do expediente",
        type: "time",
        default: "18:00",
      },
      {
        key: "holidays",
        label: "Feriados (AAAA-MM-DD, separados por espaço)",
        optional: true,
      },
      ...slaFields,
      reason,
    ],
    create: true,
    note: versioned,
  },
];
type Row = Record<string, string | number | boolean | null>;
export function Admin() {
  const [resource, setResource] = useState(
    resources.find((item) => item.path === "departments")!,
  );

  useEffect(() => {
    window.dispatchEvent(new CustomEvent("pulse:page-change"));
  }, [resource]);
  const [rows, setRows] = useState<Row[]>([]);
  const [editing, setEditing] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [refs, setRefs] = useState<Record<string, Ref[]>>({});
  const loadRefs = useCallback(async () => {
    const [users, groups, departments] = await Promise.all(
      ["users", "groups", "departments"].map((path) => all<Ref>(path + "/")),
    );
    setRefs({ users, groups, departments });
  }, []);
  useEffect(() => {
    loadRefs().catch((err) => setError(err.message));
  }, [loadRefs]);
  const refLabel = (ref: Ref) =>
    ref.name || (ref.first_name ? `${ref.first_name} · ${ref.email}` : "");
  const refName = (source: string, id: Row[string]) => {
    const found = refs[source]?.find((ref) => ref.id === id);
    return found
      ? found.name || found.first_name || ""
      : id == null
        ? "—"
        : String(id);
  };
  const display = (field: Field, value: Row[string]) =>
    field.ref
      ? refName(field.ref, value)
      : typeof value === "boolean"
        ? value
          ? "Sim"
          : "Não"
        : (field.options?.find(([option]) => option === String(value))?.[1] ??
          String(value));
  async function load() {
    setRows(await all<Row>(resource.path + "/"));
    await loadRefs();
  }
  useEffect(() => {
    if (resource.path.startsWith("settings/") && !resource.fields.length)
      return;
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
  const title = (row: Row) =>
    String(
      row.name ||
        (row.first_name ? `${row.first_name} · ${row.email}` : row.email) ||
        row.domain ||
        (row.user
          ? `${refName("users", row.user)} · ${refName("groups", row.group)}`
          : row.p1_response !== undefined
            ? `SLA · ${row.reason}`
            : `${row.hours} horas · ${row.reason}`),
    );
  const formFields = editing
    ? resource.fields
    : resource.createFields || resource.fields;
  async function toggle(row: Row) {
    const verb = row.is_active ? "Desativar" : "Reativar";
    const body: Record<string, unknown> = { is_active: !row.is_active };
    if (resource.fields.some((f) => f.key === "reason")) {
      const reason = window.prompt(
        `${verb} ${title(row)}? Informe a justificativa.`,
      );
      if (!reason?.trim()) return;
      body.reason = reason;
    } else if (!window.confirm(`${verb} ${title(row)}?`)) return;
    setBusy(true);
    setError("");
    try {
      await api(`${resource.path}/${row.id}/`, body, "PATCH");
      await load();
      setNotice(row.is_active ? "Registro desativado." : "Registro reativado.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
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
      {resource.path === "settings/company" ? (
        <CompanySettings />
      ) : resource.path === "settings/audit" ? (
        <AuditLog />
      ) : resource.path === "settings/smtp" ? (
        <SmtpSettings />
      ) : resource.path === "settings/chat" ? (
        <ChatSettings />
      ) : resource.path === "settings/notifications" ? (
        <NotificationDiagnostics />
      ) : (
        <div className="detail-grid">
          <section className="panel">
            <h2>{resource.label}</h2>
            {resource.note && <p>{resource.note}</p>}
            {!rows.length && <p>Nenhum registro.</p>}
            <ul className="admin-list">
              {rows.map((row) => (
                <li key={String(row.id)}>
                  <div>
                    <strong>{title(row)}</strong>
                    <small>
                      {resource.fields
                        .filter(
                          (f) =>
                            row[f.key] !== undefined &&
                            f.key !== "name" &&
                            !(row.user && ["user", "group"].includes(f.key)),
                        )
                        .map((f) => `${f.label}: ${display(f, row[f.key])}`)
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
                      Editar
                    </button>
                  )}
                  {resource.toggleActive && (
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => toggle(row)}
                    >
                      {row.is_active ? "Desativar" : "Reativar"}
                    </button>
                  )}
                  {resource.removable && (
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={async () => {
                        const label = resource.removeLabel || "Remover";
                        let body = {};
                        if (resource.removeReason) {
                          const reason = window.prompt(
                            `${label} ${title(row)}? Informe a justificativa.`,
                          );
                          if (!reason?.trim()) return;
                          body = { reason };
                        } else if (!window.confirm(`${label} ${title(row)}?`))
                          return;
                        setBusy(true);
                        try {
                          await api(
                            `${resource.path}/${row.id}/`,
                            body,
                            "DELETE",
                          );
                          await load();
                          setNotice("Registro removido.");
                        } catch (err) {
                          setError((err as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      {resource.removeLabel || "Remover"}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
          <section className="panel">
            <h2>{editing ? `Editar ${title(editing)}` : "Novo registro"}</h2>
            {resource.create || editing ? (
              <form
                key={`${resource.path}/${editing?.id}`}
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (busy) return;
                  setBusy(true);
                  setError("");
                  const element = e.currentTarget;
                  const form = new FormData(element);
                  const data: Record<string, unknown> = {};
                  formFields.forEach((f) => {
                    data[f.key] =
                      f.type === "checkbox"
                        ? form.has(f.key)
                        : f.type === "number" || f.ref
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
                    element.reset();
                    await load();
                    setNotice(
                      resource.createFields && !editing
                        ? "Conta criada como Colaborador. O convite para definir a senha foi enviado por e-mail."
                        : "Configuração salva.",
                    );
                  } catch (err) {
                    setError((err as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {formFields.map((f) => (
                  <Fragment key={f.key}>
                    <label className={f.type === "checkbox" ? "checkbox" : ""}>
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
                          defaultValue={String(
                            editing?.[f.key] || f.default || f.options[0][0],
                          )}
                        >
                          {f.options.map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                      ) : f.ref ? (
                        <select
                          name={f.key}
                          required={!f.optional}
                          defaultValue={String(editing?.[f.key] ?? "")}
                        >
                          <option value="">
                            {f.optional ? "Nenhuma" : "Selecione…"}
                          </option>
                          {(refs[f.ref] || [])
                            .filter(
                              (ref) =>
                                (!f.roles ||
                                  f.roles.includes(String(ref.role))) &&
                                (ref.is_active !== false ||
                                  ref.id === editing?.[f.key]),
                            )
                            .map((ref) => (
                              <option key={ref.id} value={ref.id}>
                                {refLabel(ref)}
                              </option>
                            ))}
                        </select>
                      ) : f.type !== "checkbox" ? (
                        <input
                          type={f.type || "text"}
                          name={f.key}
                          min={
                            f.type === "number"
                              ? Number(f.key !== "hours")
                              : undefined
                          }
                          required={f.key !== "department" && !f.optional}
                          aria-describedby={f.hint && `${f.key}-hint`}
                          defaultValue={String(
                            editing?.[f.key] ?? f.default ?? "",
                          )}
                        />
                      ) : null}
                    </label>
                    {f.hint && (
                      <small id={`${f.key}-hint`} className="field-hint">
                        {f.hint}
                      </small>
                    )}
                  </Fragment>
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
