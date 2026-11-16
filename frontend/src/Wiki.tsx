import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, date } from "./api";
import { Markup } from "./WikiMarkup";
import { WikiEditor } from "./WikiEditor";

type Summary = {
  id: string;
  title: string;
  tags: string[];
  groups: { id: number; name: string }[];
  author_name: string;
  created_at: string;
  updated_at: string;
};
type Page = Summary & { body: string; updated_by_name: string };

export function tagColor(tag: string) {
  let hash = 0;
  for (const c of tag.toLowerCase()) hash = (hash * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${hash} 60% 30%)`;
}

function Tags({ tags }: { tags: string[] }) {
  return (
    <span className="wiki-tags">
      {tags.map((t) => (
        <span key={t} className="wiki-tag" style={{ background: tagColor(t) }}>
          {t}
        </span>
      ))}
    </span>
  );
}

export function Wiki({ canEdit }: { canEdit: boolean }) {
  const [pages, setPages] = useState<Summary[] | null>(null);
  const [tag, setTag] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<Page | null>(null);
  const [editing, setEditing] = useState<Page | "new" | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [groups, setGroups] = useState<{ id: number; name: string }[]>([]);
  const [picked, setPicked] = useState<number[]>([]);
  useEffect(() => {
    if (canEdit)
      api<{ id: number; name: string }[]>("wiki/groups/")
        .then(setGroups)
        .catch(() => setGroups([]));
  }, [canEdit]);

  const load = useCallback(async () => {
    try {
      setPages(await api<Summary[]>("wiki/"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const tags = useMemo(() => {
    const count = new Map<string, number>();
    pages?.forEach((p) =>
      p.tags.forEach((t) => count.set(t, (count.get(t) ?? 0) + 1)),
    );
    return [...count.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [pages]);

  const shown = (pages ?? []).filter(
    (p) =>
      (!tag || p.tags.includes(tag)) &&
      (!search || p.title.toLowerCase().includes(search.toLowerCase())),
  );

  async function show(id: string) {
    setError("");
    try {
      setOpen(await api<Page>(`wiki/${id}/`));
      setEditing(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function save(form: HTMLFormElement) {
    if (busy) return;
    setBusy(true);
    setError("");
    const values = new FormData(form);
    const body = {
      title: String(values.get("title")),
      body: String(values.get("body")),
      tags: String(values.get("tags"))
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      groups: picked,
    };
    try {
      const saved =
        editing === "new"
          ? await api<Page>("wiki/", body)
          : await api<Page>(`wiki/${(editing as Page).id}/`, body, "PATCH");
      setOpen(saved);
      setEditing(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && e.status === 403) setEditing(null);
    } finally {
      setBusy(false);
    }
  }

  async function remove(page: Page) {
    if (
      !window.confirm(
        `Excluir a página "${page.title}"? Isso não pode ser desfeito.`,
      )
    )
      return;
    try {
      await api(`wiki/${page.id}/`, {}, "DELETE");
      setOpen(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const side = (
    <aside className="wiki-side" aria-label="Menu da wiki">
      {canEdit && (
        <button
          onClick={() => {
            setOpen(null);
            setDraft("");
            setPicked([]);
            setEditing("new");
          }}
        >
          Nova página
        </button>
      )}
      <button
        onClick={() => {
          setTag("");
          setOpen(null);
          setEditing(null);
        }}
      >
        Todas as páginas
      </button>
      <p className="wiki-menu-title">Tags</p>
      {tags.map(([name, count]) => (
        <button
          key={name}
          className={`wiki-menu${tag === name ? " active" : ""}`}
          onClick={() => {
            setTag(name);
            setOpen(null);
            setEditing(null);
          }}
        >
          <span className="wiki-dot" style={{ background: tagColor(name) }} />
          {name} <small>{count}</small>
        </button>
      ))}
      {pages && !tags.length && <small>Nenhuma tag ainda.</small>}
    </aside>
  );

  let main: ReactNode;
  if (editing) {
    const page = editing === "new" ? null : editing;
    main = (
      <section className="panel">
        <h2>{page ? "Editar página" : "Nova página"}</h2>
        <form
          key={page?.id ?? "new"}
          onSubmit={(e) => {
            e.preventDefault();
            void save(e.currentTarget);
          }}
        >
          <label>
            Título
            <input
              name="title"
              required
              maxLength={200}
              defaultValue={page?.title}
            />
          </label>
          <label>
            Tags (separadas por vírgula, até 5)
            <input name="tags" defaultValue={page?.tags.join(", ")} />
          </label>
          <fieldset className="wiki-groups">
            <legend>Visível para os grupos</legend>
            {groups.map((g) => (
              <label key={g.id} className="check">
                <input
                  type="checkbox"
                  checked={picked.includes(g.id)}
                  onChange={(e) =>
                    setPicked(
                      e.target.checked
                        ? [...picked, g.id]
                        : picked.filter((id) => id !== g.id),
                    )
                  }
                />
                {g.name}
              </label>
            ))}
            <small className="field-hint">
              Sem nenhum grupo marcado, a página fica visível para todos.
              Gestores e administradores sempre veem todas as páginas.
            </small>
          </fieldset>
          <p className="editor-label">Conteúdo</p>
          <WikiEditor value={draft} onChange={setDraft} />
          <small className="field-hint">
            Use a barra de ferramentas ou a sintaxe Markdown. Imagens e anexos
            são verificados contra vírus ao enviar. Não coloque senhas nem dados
            de clientes.
          </small>
          <div className="wiki-actions">
            <button disabled={busy}>
              {busy ? "Salvando…" : "Salvar página"}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setEditing(null)}
            >
              Cancelar
            </button>
          </div>
        </form>
      </section>
    );
  } else if (open) {
    main = (
      <article className="panel">
        <button className="link" onClick={() => setOpen(null)}>
          ← Todas as páginas
        </button>
        <h2>{open.title}</h2>
        <p className="muted">
          <Tags tags={open.tags} />{" "}
          {open.groups.length > 0 &&
            `🔒 ${open.groups.map((g) => g.name).join(", ")} · `}
          {open.author_name} · {date(open.created_at)}
          {open.updated_by_name &&
            ` · editado por ${open.updated_by_name} em ${date(open.updated_at)}`}
        </p>
        <Markup text={open.body} />
        {canEdit && (
          <div className="wiki-actions">
            <button
              onClick={() => {
                setDraft(open.body);
                setPicked(open.groups.map((g) => g.id));
                setEditing(open);
              }}
            >
              Editar
            </button>
            <button className="secondary" onClick={() => void remove(open)}>
              Excluir
            </button>
          </div>
        )}
        <div className="wiki-actions wiki-footer">
          <button
            className="link"
            onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          >
            ↑ Voltar ao topo
          </button>
          <button className="link" onClick={() => setOpen(null)}>
            ← Voltar para todas as páginas
          </button>
        </div>
      </article>
    );
  } else {
    main = (
      <>
        <div className="wiki-bar">
          <input
            type="search"
            aria-label="Pesquisar na wiki"
            placeholder="Pesquisar na wiki"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {!pages ? (
          <p role="status">Carregando a wiki…</p>
        ) : !shown.length ? (
          <p className="panel">
            {pages.length
              ? "Nenhuma página encontrada."
              : canEdit
                ? "A wiki está vazia. Use “Nova página” para criar a primeira."
                : "A wiki ainda não tem páginas."}
          </p>
        ) : (
          <ul className="wiki-list">
            {shown.map((p) => (
              <li key={p.id}>
                <span className="wiki-avatar" aria-hidden="true">
                  {p.author_name.charAt(0).toUpperCase()}
                </span>
                <div>
                  <button
                    className="link wiki-title"
                    onClick={() => void show(p.id)}
                  >
                    {p.title}
                  </button>
                  <small>
                    {p.author_name} criou em {date(p.created_at)}
                  </small>
                </div>
                <Tags tags={p.tags} />
              </li>
            ))}
          </ul>
        )}
      </>
    );
  }

  return (
    <div className="wiki">
      <header className="wiki-hero">
        <h2>Wiki</h2>
        <p>
          Repositório de conhecimento da equipe. “O conhecimento só é valioso
          quando é compartilhado.”
        </p>
      </header>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className={`wiki-layout${editing ? " editing" : ""}`}>
        {!editing && side}
        <div>{main}</div>
      </div>
    </div>
  );
}
