import { Fragment } from "react";

import { MARK_END, MARK_START } from "@/lib/memoryMarks";

/**
 * A search snippet with its matched words highlighted. The text is only ever rendered as React
 * text nodes, which escape everything, so nothing in a message can become markup: the two mark
 * characters are the only thing turned into an element (<mark>), and strays are dropped.
 */
export function Marked({ text }: { text: string }) {
  const clean = (s: string) => s.replaceAll(MARK_START, "").replaceAll(MARK_END, "");
  return (
    <>
      {text.split(MARK_START).map((piece, i) => {
        if (i === 0) return <Fragment key={i}>{clean(piece)}</Fragment>;
        const [marked, ...rest] = piece.split(MARK_END);
        return (
          <Fragment key={i}>
            <mark className="rounded-sm bg-accent/25 px-0.5 text-ink">{marked}</mark>
            {clean(rest.join(""))}
          </Fragment>
        );
      })}
    </>
  );
}
