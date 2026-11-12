import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, date } from "./api";

type Summary = {
  id: string;
  title: string;
  tags: string[];
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

function inline(text: string): ReactNode[] {
  // Only http(s) links; everything else stays text, so stored content cannot inject markup.
  return text
    .split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g)
    .map((part, i) => {
      if (/^\*\*.+\*\*$/.test(part)) return <b key={i}>{part.slice(2, -2)}</b>;
      if (/^`.+`$/.test(part)) return <code key={i}>{part.slice(1, -1)}</code>;
      const link = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(part);
      if (link)
        return (
          <a key={i} href={link[2]} target="_blank" rel="noopener noreferrer">
            {link[1]}
          </a>
        );
      return part;
    });
}

export function Content({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let ordered = false;
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length)
      blocks.push(<p key={blocks.length}>{inline(paragraph.join(" "))}</p>);
    if (list.length) {
      const items = list.map((item, i) => <li key={i}>{inline(item)}</li>);
      blocks.push(
        ordered ? (
          <ol key={blocks.length}>{items}</ol>
        ) : (
          <ul key={blocks.length}>{items}</ul>
        ),
      );
    }
    paragraph = [];
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    const item = /^\s*(?:([-*])|(\d+)\.)\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      const Tag = `h${heading[1].length + 2}` as "h3" | "h4" | "h5";
      blocks.push(<Tag key={blocks.length}>{inline(heading[2])}</Tag>);
    } else if (item) {
      const isOrdered = Boolean(item[2]);
      if (paragraph.length || (list.length && isOrdered !== ordered)) flush();
      ordered = isOrdered;
      list.push(item[3]);
    } else if (!line.trim()) flush();
    else {
      if (list.length) flush();
      paragraph.push(line.trim());
    }
  }
  flush();
  return <div className="wiki-content">{blocks}</div>;
}

export function Wiki({ canEdit }: { canEdit: boolean }) {
  const [pages, setPages] = useState<Summary[] | null>(null);
  const [tag, setTag] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<Page | null>(null);
  const [editing, setEditing] = useState<Page | "new" | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
            setEditing("new");
          }}
        >
          Nova página
        </button>
      )}
      <button
        className={`wiki-menu${!tag && !open && !editing ? " active" : ""}`}
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
          <label>
            Conteúdo
            <textarea
              name="body"
              required
              rows={16}
              maxLength={50000}
              defaultValue={page?.body}
            />
          </label>
          <small className="field-hint">
            Use # Título, - lista, 1. passos, **negrito**, `código` e
            [texto](https://link). Não coloque senhas nem dados de clientes.
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
          <Tags tags={open.tags} /> {open.author_name} · {date(open.created_at)}
          {open.updated_by_name &&
            ` · editado por ${open.updated_by_name} em ${date(open.updated_at)}`}
        </p>
        <Content text={open.body} />
        {canEdit && (
          <div className="wiki-actions">
            <button onClick={() => setEditing(open)}>Editar</button>
            <button className="secondary" onClick={() => void remove(open)}>
              Excluir
            </button>
          </div>
        )}
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
      <div className="wiki-layout">
        {side}
        <div>{main}</div>
      </div>
    </div>
  );
}
