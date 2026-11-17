import { useState, type ReactNode } from "react";
import { api } from "./api";

type Page = {
  id: string;
  title: string;
  tags: string[];
  departments: { name: string }[];
};

const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const LINK = new RegExp(
  `${escape(window.location.origin)}/wiki/[0-9a-f-]{36}`,
  "g",
);

/** Turns links to wiki pages of this system into anchors; everything else stays text. */
export function linkify(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(LINK)) {
    nodes.push(text.slice(last, m.index));
    nodes.push(
      <a key={m.index} href={m[0]} target="_blank" rel="noopener noreferrer">
        {m[0]}
      </a>,
    );
    last = m.index + m[0].length;
  }
  nodes.push(text.slice(last));
  return nodes;
}

/** Technicians search wiki pages and add a link to one in their reply. */
export function WikiLinkPicker({ onPick }: { onPick: (text: string) => void }) {
  const [pages, setPages] = useState<Page[] | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (pages) return;
    try {
      setPages(await api<Page[]>("wiki/"));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const term = search.trim().toLowerCase();
  const found = term
    ? (pages ?? [])
        .filter(
          (p) =>
            p.title.toLowerCase().includes(term) ||
            p.tags.some((t) => t.toLowerCase().includes(term)),
        )
        .slice(0, 8)
    : [];
  return (
    <div className="wiki-picker">
      <label>
        Anexar link da wiki (opcional)
        <input
          type="search"
          value={search}
          placeholder="Pesquisar páginas da wiki"
          onFocus={() => void load()}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {term && pages && !found.length && (
        <small>Nenhuma página encontrada.</small>
      )}
      {found.length > 0 && (
        <ul className="wiki-picker-list">
          {found.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  onPick(
                    `Wiki: ${p.title}\n${window.location.origin}/wiki/${p.id}`,
                  );
                  setSearch("");
                }}
              >
                {p.title}
                {p.departments.length > 0 && (
                  <small>
                    {" "}
                    · restrita a {p.departments.map((d) => d.name).join(", ")}
                  </small>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
