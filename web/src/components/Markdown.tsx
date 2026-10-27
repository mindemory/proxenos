// A tiny markdown renderer for the self-model files: headings, lists,
// paragraphs, code blocks, quotes, rules, and inline bold, italics, code
// and links. It builds React elements, so file contents are never parsed as HTML.

import type { ReactNode } from "react";

type Block =
  | { type: "h"; level: number; text: string }
  | { type: "ul" | "ol"; items: string[] }
  | { type: "p" | "quote" | "code"; text: string }
  | { type: "hr" };

function parse(md: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  let quote: string[] = [];
  let list: { type: "ul" | "ol"; items: string[] } | null = null;
  let code: string[] | null = null;

  const flush = () => {
    if (para.length) blocks.push({ type: "p", text: para.join(" ") });
    if (quote.length) blocks.push({ type: "quote", text: quote.join(" ") });
    if (list) blocks.push(list);
    para = [];
    quote = [];
    list = null;
  };

  for (const line of md.replace(/\r\n?/g, "\n").split("\n")) {
    if (code) {
      if (line.trim().startsWith("```")) {
        blocks.push({ type: "code", text: code.join("\n") });
        code = null;
      } else code.push(line);
      continue;
    }
    const t = line.trim();
    let m: RegExpMatchArray | null;
    if (!t) flush();
    else if (t.startsWith("```")) {
      flush();
      code = [];
    } else if ((m = t.match(/^(#{1,6})\s+(.*)$/))) {
      flush();
      blocks.push({ type: "h", level: m[1].length, text: m[2] });
    } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) {
      flush();
      blocks.push({ type: "hr" });
    } else if ((m = t.match(/^([-*+]|\d+[.)])\s+(.*)$/))) {
      const type = /^\d/.test(m[1]) ? "ol" : "ul";
      if (!list || list.type !== type) {
        flush();
        list = { type, items: [] };
      }
      list.items.push(m[2]);
    } else if (list && /^\s+/.test(line)) {
      list.items[list.items.length - 1] += " " + t;
    } else if (t.startsWith(">")) {
      if (!quote.length) flush();
      quote.push(t.replace(/^>\s?/, ""));
    } else {
      if (list || quote.length) flush();
      para.push(t);
    }
  }
  if (code) blocks.push({ type: "code", text: code.join("\n") });
  flush();
  return blocks;
}

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*)/g;

function inline(text: string): ReactNode[] {
  return text
    .split(INLINE)
    .filter(Boolean)
    .map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
        return (
          <code key={i} className="px-1 py-0.5 rounded bg-gray-100 text-[0.9em] font-mono">
            {part.slice(1, -1)}
          </code>
        );
      }
      const link = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
      if (link) {
        return /^https?:\/\//i.test(link[2]) ? (
          <a key={i} href={link[2]} target="_blank" rel="noopener noreferrer" className="underline decoration-primary decoration-2 hover:text-yellow-700">
            {link[1]}
          </a>
        ) : (
          link[1]
        );
      }
      if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
        return <em key={i}>{part.slice(1, -1)}</em>;
      }
      return part;
    });
}

const HEADING = ["text-2xl font-bold", "text-xl font-bold", "text-lg font-bold", "text-base font-bold"];

export function Markdown({ source }: { source: string }) {
  return (
    <div className="space-y-3 text-text-primary leading-relaxed break-words">
      {parse(source).map((b, i) => {
        switch (b.type) {
          case "h": {
            const cls = `${HEADING[Math.min(b.level, 4) - 1]} ${i > 0 ? "pt-2" : ""}`;
            return b.level === 1 ? (
              <h3 key={i} className={cls}>{inline(b.text)}</h3>
            ) : (
              <h4 key={i} className={cls}>{inline(b.text)}</h4>
            );
          }
          case "ul":
            return (
              <ul key={i} className="list-disc pl-6 space-y-1 marker:text-primary">
                {b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} className="list-decimal pl-6 space-y-1 marker:font-bold marker:text-yellow-700">
                {b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}
              </ol>
            );
          case "quote":
            return (
              <blockquote key={i} className="border-l-4 border-primary/40 pl-4 text-text-secondary">
                {inline(b.text)}
              </blockquote>
            );
          case "code":
            return (
              <pre key={i} className="bg-gray-100 rounded-xl p-4 text-sm font-mono overflow-x-auto">
                {b.text}
              </pre>
            );
          case "hr":
            return <hr key={i} className="border-gray-100" />;
          default:
            return <p key={i}>{inline(b.text)}</p>;
        }
      })}
    </div>
  );
}
