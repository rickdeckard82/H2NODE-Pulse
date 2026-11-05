export const priorities: [string, string][] = [
  ["1", "Crítica (P1)"],
  ["2", "Alta (P2)"],
  ["3", "Média (P3)"],
  ["4", "Baixa (P4)"],
];
export type Company = {
  name: string;
  cnpj: string;
  responsible: string;
  logo: string;
};
export type User = {
  id: number;
  first_name: string;
  email: string;
  role: string;
  avatar: string;
};
export type Page<T> = {
  results: T[];
  next: string | null;
  previous: string | null;
  count: number;
};
export type Ticket = {
  can_transfer: boolean;
  can_cancel: boolean;
  id: string;
  number: number;
  subject: string;
  description: string;
  state: string;
  priority: number;
  requester: number;
  requester_name: string;
  assignee: number | null;
  assignee_name: string | null;
  participants: { id: number; name: string }[];
  department_name: string;
  group: number;
  version: number;
  restricted: boolean;
  created_at: string;
};
export type Event = {
  id: string;
  action: string;
  actor_name: string;
  created_at: string;
  visibility: string;
  comment: { id: string; body: string; corrects: string | null } | null;
};
export type Attachment = {
  id: string;
  comment: string;
  name: string;
  status: string;
  size: number;
};
export const states: Record<string, string> = {
  new: "Novo",
  in_progress: "Em atendimento",
  waiting_information: "Aguardando informações",
  waiting_test: "Aguardando teste",
  resolved: "Resolvido",
  closed: "Fechado",
  cancelled: "Cancelado",
};
export const actions: Record<string, string> = {
  claim: "Assumir chamado",
  join: "Participar do atendimento",
  close: "Encerrar chamado",
  "participant.joined": "Novo participante",
  request_information: "Solicitar informações",
  request_test: "Solicitar teste",
  resolve: "Resolver chamado",
  confirm: "Confirmar solução",
  reopen: "Reabrir chamado",
  cancel: "Cancelar chamado",
  return_queue: "Devolver à fila",
  transfer: "Transferir chamado",
};
export const date = (value: string) =>
  new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(value));
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
function describe(data: { detail?: string; errors?: object }) {
  if (!data.errors) return data.detail || "Não foi possível concluir.";
  const messages = Object.values(data.errors)
    .flat()
    .map((m) => (typeof m === "string" ? m : JSON.stringify(m)));
  const password = ["password", "new_password"].some(
    (key) => key in data.errors!,
  );
  return (
    (password ? "Escolha uma senha mais forte. " : "Verifique os dados. ") +
    messages.join(" ")
  );
}
export async function api<T>(
  path: string,
  body?: object | FormData,
  method = "POST",
  key?: string,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    const csrf = await fetch("/api/v1/auth/csrf/", { cache: "no-store" }).then(
      (r) => r.json(),
    );
    headers["X-CSRFToken"] = csrf.csrfToken;
    if (!(body instanceof FormData))
      headers["Content-Type"] = "application/json";
    if (key) headers["Idempotency-Key"] = key;
  }
  const response = await fetch(`/api/v1/${path}`, {
    method: body === undefined ? "GET" : method,
    headers,
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
    cache: "no-store",
  });
  const data =
    response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok)
    throw new ApiError(
      response.status,
      response.status === 413
        ? "Arquivo grande demais. Limite: 5 MiB."
        : describe(data),
    );
  return data as T;
}
export async function all<T>(path: string): Promise<T[]> {
  const rows: T[] = [];
  let next: string | null = path;
  while (next) {
    const page: Page<T> = await api<Page<T>>(next);
    rows.push(...page.results);
    next = page.next ? page.next.split("/api/v1/")[1] : null;
  }
  return rows;
}
