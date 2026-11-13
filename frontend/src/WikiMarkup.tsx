import type { CSSProperties, ReactNode } from "react";

/*
 * Wiki markup, same syntax as the EHS blog editor. It renders React nodes (never raw
 * HTML), so stored text cannot inject markup. Images and links may only point to
 * https URLs or to files of this system.
 */
const FILE = "/api/v1/wiki/files/[0-9a-f-]{36}/";
const SRC = `(?:https?:\\/\\/[^\\s)]+|${FILE.replaceAll("/", "\\/")})`;
const SIZES: Record<string, string> = {
  small: "0.85em",
  large: "1.25em",
  huge: "1.6em",
};
const PATTERNS: [string, RegExp][] = [
  ["code", /`([^`]+)`/],
  [
    "image",
    new RegExp(`!\\[([^\\]]*)\\]\\((${SRC})(?:\\s+=(\\d{1,4})x\\d{0,4})?\\)`),
  ],
  ["link", new RegExp(`\\[([^\\]]+)\\]\\((${SRC})\\)`)],
  ["bold", /\*\*(.+?)\*\*/s],
  ["italic", /\*(.+?)\*/s],
  ["strike", /~~(.+?)~~/s],
  ["size", /\{\{size:(small|large|huge)\}\}(.+?)\{\{\/size\}\}/s],
];

export function inline(text: string, key = ""): ReactNode[] {
  let best: { name: string; m: RegExpExecArray } | null = null;
  for (const [name, re] of PATTERNS) {
    const m = re.exec(text);
    if (m && (!best || m.index < best.m.index)) best = { name, m };
  }
  if (!best) return text ? [text] : [];
  const { name, m } = best;
  const k = `${key}${m.index}`;
  const rest = inline(text.slice(m.index + m[0].length), `${k}.`);
  let node: ReactNode;
  if (name === "code") node = <code key={k}>{m[1]}</code>;
  else if (name === "image")
    node = (
      <img
        key={k}
        src={m[2]}
        alt={m[1]}
        loading="lazy"
        style={
          m[3] ? { width: `${Number(m[3])}px`, maxWidth: "100%" } : undefined
        }
      />
    );
  else if (name === "link") {
    const internal = m[2].startsWith("/");
    node = (
      <a
        key={k}
        href={m[2]}
        {...(internal
          ? { download: "" }
          : { target: "_blank", rel: "noopener noreferrer" })}
      >
        {m[1]}
      </a>
    );
  } else if (name === "bold")
    node = <strong key={k}>{inline(m[1], `${k}b`)}</strong>;
  else if (name === "italic") node = <em key={k}>{inline(m[1], `${k}i`)}</em>;
  else if (name === "strike") node = <del key={k}>{inline(m[1], `${k}s`)}</del>;
  else
    node = (
      <span key={k} style={{ fontSize: SIZES[m[1]] }}>
        {inline(m[2], `${k}z`)}
      </span>
    );
  return [...inline(text.slice(0, m.index), `${k}<`), node, ...rest];
}

const cells = (row: string) =>
  row
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());
const dashes = (s: string) =>
  s.replace(/[\u00A0\u202F]/g, " ").replace(/[\u2013\u2014\u2015\u2212]/g, "-");
const isSeparator = (line: string) =>
  dashes(line).includes("-") &&
  /^\s*(?:\|\s*)?:?-+:?\s*(?:\|\s*:?-+:?\s*)*(?:\|\s*)?$/.test(dashes(line));

function table(lines: string[], key: number): ReactNode {
  const align = cells(dashes(lines[1])).map((s): CSSProperties["textAlign"] =>
    s.startsWith(":") && s.endsWith(":")
      ? "center"
      : s.endsWith(":")
        ? "right"
        : s.startsWith(":")
          ? "left"
          : undefined,
  );
  const row = (line: string, Tag: "th" | "td", k: number) => (
    <tr key={k}>
      {cells(line).map((c, i) => (
        <Tag key={i} style={{ textAlign: align[i] }}>
          {inline(c)}
        </Tag>
      ))}
    </tr>
  );
  return (
    <table key={key}>
      <thead>{row(lines[0], "th", 0)}</thead>
      <tbody>
        {lines
          .slice(2)
          .filter((l) => l.trim())
          .map((l, i) => row(l, "td", i))}
      </tbody>
    </table>
  );
}

const lineBreaks = (lines: string[]) =>
  lines.flatMap((l, i) =>
    i ? [<br key={`br${i}`} />, ...inline(l, `l${i}`)] : inline(l, "l0"),
  );

function block(raw: string, key: number): ReactNode {
  // A heading line is always its own block, even without a blank line around it.
  const rows = raw.split("\n");
  if (rows.length > 1 && rows.some((l) => /^#{1,3}\s+/.test(l))) {
    const groups: string[][] = [];
    for (const row of rows) {
      const last = groups[groups.length - 1];
      if (/^#{1,3}\s+/.test(row) || !last || /^#{1,3}\s+/.test(last[0]))
        groups.push([row]);
      else last.push(row);
    }
    return <div key={key}>{groups.map((g, i) => block(g.join("\n"), i))}</div>;
  }
  const heading = /^(#{1,3})\s+(.*)$/.exec(raw);
  if (heading) {
    // # -> h3: h1/h2 belong to the page layout.
    const Tag = `h${heading[1].length + 2}` as "h3" | "h4" | "h5";
    return <Tag key={key}>{inline(heading[2])}</Tag>;
  }
  const lines = raw.split("\n");
  if (lines.length === 1 && /^([-*_])\1{2,}$/.test(raw))
    return <hr key={key} />;
  if (lines.length >= 2 && lines[0].includes("|") && isSeparator(lines[1]))
    return table(lines, key);
  const start = lines.findIndex(
    (l, i) =>
      i > 0 &&
      i < lines.length - 1 &&
      l.includes("|") &&
      isSeparator(lines[i + 1]),
  );
  if (start > 0)
    return (
      <div key={key}>
        <p>{lineBreaks(lines.slice(0, start))}</p>
        {table(lines.slice(start), 0)}
      </div>
    );
  if (lines.every((l) => /^\s*[-*]\s+/.test(l)))
    return (
      <ul key={key}>
        {lines.map((l, i) => (
          <li
            key={i}
            style={{ marginLeft: `${(l.length - l.trimStart().length) * 6}px` }}
          >
            {inline(l.replace(/^\s*[-*]\s+/, ""))}
          </li>
        ))}
      </ul>
    );
  if (lines.every((l) => /^\s*\d+\.\s+/.test(l)))
    return (
      <ol key={key}>
        {lines.map((l, i) => (
          <li key={i}>{inline(l.replace(/^\s*\d+\.\s+/, ""))}</li>
        ))}
      </ol>
    );
  if (lines.every((l) => /^>\s?/.test(l)))
    return (
      <blockquote key={key}>
        <p>{lineBreaks(lines.map((l) => l.replace(/^>\s?/, "")))}</p>
      </blockquote>
    );
  return <p key={key}>{lineBreaks(lines)}</p>;
}

export function Markup({ text }: { text: string }) {
  const codes: string[] = [];
  const source = text
    .replace(/\r\n?/g, "\n")
    .replace(/[\u00A0\u202F]/g, " ")
    .replace(
      /```([\s\S]*?)```/g,
      (_, code: string) =>
        `\uE000${codes.push(code.replace(/^\n+|\n+$/g, "")) - 1}\uE001`,
    );
  const nodes = source
    .trim()
    .split(/\n{2,}/)
    .map((part, i) => {
      const raw = part.trim();
      const code = /^\uE000(\d+)\uE001$/.exec(raw);
      if (code)
        return (
          <pre key={i}>
            <code>{codes[Number(code[1])]}</code>
          </pre>
        );
      if (!raw) return null;
      const aligned = /^:::(center|right|justify)\n([\s\S]*)$/.exec(raw);
      if (!aligned) return block(raw, i);
      const inner = aligned[2].replace(/\n?:::[ \t]*$/, "").trim();
      return (
        <div
          key={i}
          style={{ textAlign: aligned[1] as CSSProperties["textAlign"] }}
        >
          {inner ? block(inner, 0) : null}
        </div>
      );
    });
  return <div className="wiki-content">{nodes}</div>;
}
