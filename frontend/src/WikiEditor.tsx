import { useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { Markup } from "./WikiMarkup";

type Uploaded = { id: string; name: string; media_type: string; url: string };

const EMOJIS = [
  "😀",
  "😃",
  "😄",
  "😁",
  "😆",
  "😅",
  "😂",
  "🙂",
  "😉",
  "😊",
  "😍",
  "😘",
  "🤔",
  "😎",
  "😴",
  "😭",
  "😢",
  "😡",
  "🤯",
  "🥳",
  "👍",
  "👎",
  "👏",
  "🙌",
  "🤝",
  "💪",
  "🎉",
  "🔥",
  "💡",
  "✅",
  "❌",
  "⚠️",
  "❤️",
  "🚀",
  "💻",
  "🛠️",
  "📌",
  "📎",
  "⭐",
  "🐛",
  "📷",
  "📅",
  "🔒",
  "🔗",
  "✨",
  "📡",
  "🌐",
  "⚙️",
  "📦",
  "🧠",
];
const IMAGES = ".png,.jpg,.jpeg,.gif,.webp";
const FILES = ".pdf,.txt,.docx,.xlsx";

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const lines = (...ys: number[]) =>
  ys.map((y, i) => (
    <line key={y} x1={i % 2 ? 7 : 4} y1={y} x2={i % 3 === 0 ? 20 : 17} y2={y} />
  ));

export function WikiEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  const saved = useRef({ start: 0, end: 0 });
  const [popover, setPopover] = useState<"" | "emoji" | "image">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [image, setImage] = useState<Uploaded | null>(null);
  const [alt, setAlt] = useState("");
  const [width, setWidth] = useState("640");

  function edit(next: string, start: number, end = start) {
    onChange(next);
    requestAnimationFrame(() => {
      area.current?.focus();
      area.current?.setSelectionRange(start, end);
    });
  }
  const range = () => {
    const el = area.current!;
    return { start: el.selectionStart, end: el.selectionEnd };
  };
  function wrap(before: string, after: string, placeholder: string) {
    const { start, end } = range();
    const selected = value.slice(start, end) || placeholder;
    edit(
      value.slice(0, start) + before + selected + after + value.slice(end),
      start + before.length,
      start + before.length + selected.length,
    );
  }
  function prefix(fn: (line: string, i: number) => string) {
    const { start, end } = range();
    const from = value.lastIndexOf("\n", start - 1) + 1;
    let to = value.indexOf("\n", end);
    if (to === -1) to = value.length;
    const block = value.slice(from, to).split("\n").map(fn).join("\n");
    edit(
      value.slice(0, from) + block + value.slice(to),
      from,
      from + block.length,
    );
  }
  const toggle = (p: string) => (l: string) =>
    l.startsWith(p) ? l.slice(p.length) : p + l;
  function insert(text: string, at = saved.current) {
    edit(
      value.slice(0, at.start) + text + value.slice(at.end),
      at.start + text.length,
    );
  }
  function codeBlock() {
    const { start, end } = range();
    const selected = value.slice(start, end);
    if (!selected.includes("\n")) return wrap("`", "`", "código");
    const lead = start > 0 && value[start - 1] !== "\n" ? "\n\n" : "";
    const tail = end < value.length && value[end] !== "\n" ? "\n\n" : "";
    insert(`${lead}\`\`\`\n${selected}\n\`\`\`${tail}`, { start, end });
  }
  function link() {
    const { start, end } = range();
    const selected = value.slice(start, end) || "texto do link";
    const url = window.prompt("URL do link (https://...)", "https://");
    if (!url || !/^https?:\/\/\S+$/.test(url)) return;
    insert(`[${selected}](${url})`, { start, end });
  }
  function align(kind: string) {
    const { start, end } = range();
    let from = value.lastIndexOf("\n\n", Math.max(start - 1, 0));
    from = from === -1 ? 0 : from + 2;
    let to = value.indexOf("\n\n", end);
    if (to === -1) to = value.length;
    const block = value.slice(from, to);
    const m = /^:::(center|right|justify)\n([\s\S]*?)\n:::[ \t]*$/.exec(block);
    const inner = m ? m[2] : block;
    const next = (m ? m[1] : "left") === kind ? "left" : kind;
    const out = next === "left" ? inner : `:::${next}\n${inner}\n:::`;
    edit(value.slice(0, from) + out + value.slice(to), from, from + out.length);
  }
  function table() {
    const { start, end } = range();
    const lead = start > 0 && value[start - 1] !== "\n" ? "\n\n" : "";
    insert(
      `${lead}| Coluna 1 | Coluna 2 |\n| --- | --- |\n| Valor | Valor |\n`,
      { start, end },
    );
  }

  async function upload(file: File): Promise<Uploaded | null> {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      return await api<Uploaded>("wiki/files/", form);
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }
  const imageMarkup = (file: Uploaded, text: string, size: string) =>
    `![${text.replace(/[\][]/g, "")}](${file.url}${size ? ` =${size}x` : ""})`;

  async function attach(file: File | undefined) {
    if (!file) return;
    const done = await upload(file);
    if (!done) return;
    insert(
      done.media_type.startsWith("image/")
        ? imageMarkup(done, "", "640")
        : `[${done.name.replace(/[\][]/g, "")}](${done.url})`,
      range(),
    );
  }
  const actions: Record<string, () => void> = {
    heading: () => prefix(toggle("### ")),
    bold: () => wrap("**", "**", "texto em negrito"),
    italic: () => wrap("*", "*", "texto em itálico"),
    strike: () => wrap("~~", "~~", "texto tachado"),
    quote: () => prefix(toggle("> ")),
    code: codeBlock,
    link,
    ul: () => prefix(toggle("- ")),
    ol: () => prefix((l, i) => `${i + 1}. ${l.replace(/^\d+\.\s+/, "")}`),
    table,
  };
  const button = (
    name: string,
    label: string,
    content: ReactNode,
    run = actions[name],
  ) => (
    <button
      type="button"
      className="editor-btn"
      title={label}
      aria-label={label}
      onClick={run}
    >
      {content}
    </button>
  );
  const aligns: [string, string, ReactNode][] = [
    ["left", "Alinhar à esquerda", lines(6, 12, 18)],
    ["center", "Centralizar", lines(6, 12, 18)],
    ["right", "Alinhar à direita", lines(6, 12, 18)],
    ["justify", "Justificar", lines(6, 12, 18)],
  ];

  return (
    <div className="editor-split">
      <div className="editor">
        <div
          className="editor-toolbar"
          role="toolbar"
          aria-label="Formatação do texto"
        >
          {button("heading", "Cabeçalho", "H")}
          {button("bold", "Negrito", <strong>B</strong>)}
          {button("italic", "Itálico", <em>I</em>)}
          {button("strike", "Tachado", <s>S</s>)}
          <span className="editor-sep" />
          {button("quote", "Citação", "“")}
          {button(
            "code",
            "Código",
            <Icon>
              <polyline points="9 8 4 12 9 16" />
              <polyline points="15 8 20 12 15 16" />
            </Icon>,
          )}
          {button(
            "link",
            "Link",
            <Icon>
              <path d="M10 13a5 5 0 0 0 7.07 0l1.93-1.93a5 5 0 0 0-7.07-7.07L10.5 5.5" />
              <path d="M14 11a5 5 0 0 0-7.07 0L5 12.93a5 5 0 0 0 7.07 7.07L13.5 18.5" />
            </Icon>,
          )}
          {button(
            "image",
            "Imagem",
            <Icon>
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </Icon>,
            () => {
              saved.current = range();
              setPopover(popover === "image" ? "" : "image");
            },
          )}
          <label
            className="editor-btn editor-file"
            title="Anexar arquivo (PDF, TXT, DOCX, XLSX)"
          >
            <Icon>
              <path d="M21 12.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6l7.9-7.9" />
            </Icon>
            <span className="sr-only">Anexar arquivo</span>
            <input
              type="file"
              accept={`${FILES},${IMAGES}`}
              disabled={busy}
              onChange={(e) => {
                saved.current = range();
                void attach(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
          <span className="editor-sep" />
          {button(
            "ul",
            "Lista",
            <Icon>
              <line x1="9" y1="6" x2="20" y2="6" />
              <line x1="9" y1="12" x2="20" y2="12" />
              <line x1="9" y1="18" x2="20" y2="18" />
              <circle cx="4" cy="6" r="1" />
              <circle cx="4" cy="12" r="1" />
              <circle cx="4" cy="18" r="1" />
            </Icon>,
          )}
          {button("ol", "Lista numerada", "1.")}
          {button(
            "table",
            "Tabela",
            <Icon>
              <rect x="3" y="4" width="18" height="16" rx="1" />
              <line x1="3" y1="10" x2="21" y2="10" />
              <line x1="9" y1="4" x2="9" y2="20" />
            </Icon>,
          )}
          <span className="editor-sep" />
          {aligns.map(([kind, label]) =>
            button(
              kind,
              label,
              <Icon>
                {kind === "left"
                  ? lines(6, 12, 18)
                  : kind === "center"
                    ? [
                        <line key="a" x1="4" y1="6" x2="20" y2="6" />,
                        <line key="b" x1="7" y1="12" x2="17" y2="12" />,
                        <line key="c" x1="6" y1="18" x2="18" y2="18" />,
                      ]
                    : kind === "right"
                      ? [
                          <line key="a" x1="4" y1="6" x2="20" y2="6" />,
                          <line key="b" x1="10" y1="12" x2="20" y2="12" />,
                          <line key="c" x1="7" y1="18" x2="20" y2="18" />,
                        ]
                      : [
                          <line key="a" x1="4" y1="6" x2="20" y2="6" />,
                          <line key="b" x1="4" y1="12" x2="20" y2="12" />,
                          <line key="c" x1="4" y1="18" x2="20" y2="18" />,
                        ]}
              </Icon>,
              () => align(kind),
            ),
          )}
          <span className="editor-sep" />
          <select
            className="editor-size-select"
            aria-label="Tamanho do texto"
            value=""
            onChange={(e) =>
              e.target.value &&
              wrap(`{{size:${e.target.value}}}`, "{{/size}}", "texto")
            }
          >
            <option value="">Tamanho</option>
            <option value="small">Pequeno</option>
            <option value="large">Grande</option>
            <option value="huge">Enorme</option>
          </select>
          <span className="editor-sep" />
          {button("emoji", "Emoji", "🙂", () => {
            saved.current = range();
            setPopover(popover === "emoji" ? "" : "emoji");
          })}
          {popover === "emoji" && (
            <div
              className="editor-popover emoji-grid"
              role="dialog"
              aria-label="Emojis"
            >
              {EMOJIS.map((emoji) => (
                <button
                  type="button"
                  key={emoji}
                  className="emoji-item"
                  aria-label={`Inserir ${emoji}`}
                  onClick={() => {
                    insert(emoji);
                    setPopover("");
                  }}
                >
                  {emoji}
                </button>
              ))}
            </div>
          )}
          {popover === "image" && (
            <div
              className="editor-popover img-popover"
              role="dialog"
              aria-label="Inserir imagem"
            >
              <label className="img-field">
                <span>Imagem (PNG, JPG, GIF ou WebP, até 5 MiB)</span>
                <input
                  type="file"
                  accept={IMAGES}
                  disabled={busy}
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (file) setImage(await upload(file));
                  }}
                />
              </label>
              {image && (
                <img
                  className="img-thumb"
                  src={image.url}
                  alt="Pré-visualização"
                />
              )}
              <label className="img-field">
                <span>Texto alternativo</span>
                <input
                  value={alt}
                  onChange={(e) => setAlt(e.target.value)}
                  placeholder="Descrição da imagem"
                />
              </label>
              <label className="img-field">
                <span>Tamanho</span>
                <select
                  value={width}
                  onChange={(e) => setWidth(e.target.value)}
                >
                  <option value="">Original</option>
                  <option value="320">Pequena (320px)</option>
                  <option value="640">Média (640px)</option>
                  <option value="960">Grande (960px)</option>
                </select>
              </label>
              <div className="wiki-actions">
                <button
                  type="button"
                  disabled={!image}
                  onClick={() => {
                    insert(imageMarkup(image!, alt, width));
                    setImage(null);
                    setAlt("");
                    setPopover("");
                  }}
                >
                  Inserir imagem
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPopover("")}
                >
                  Cancelar
                </button>
              </div>
            </div>
          )}
        </div>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {busy && <p role="status">Enviando arquivo…</p>}
        <textarea
          ref={area}
          name="body"
          aria-label="Conteúdo"
          required
          rows={16}
          maxLength={50000}
          spellCheck
          lang="pt-BR"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onPaste={(e) => {
            const file = [...e.clipboardData.files].find((f) =>
              f.type.startsWith("image/"),
            );
            if (!file) return;
            e.preventDefault();
            saved.current = range();
            void attach(file);
          }}
          onDrop={(e) => {
            const file = e.dataTransfer.files[0];
            if (!file) return;
            e.preventDefault();
            saved.current = range();
            void attach(file);
          }}
        />
      </div>
      <div className="editor-preview">
        <div className="editor-preview-header">Pré-visualização</div>
        <div className="editor-preview-body">
          {value.trim() ? (
            <Markup text={value} />
          ) : (
            <p className="muted">
              Comece a escrever para ver a pré-visualização…
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
