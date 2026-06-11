"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Root, Element, Text } from "hast";

import type { CitationInfo } from "@/lib/chat-types";
import { CitationChip } from "./CitationChip";

/** rehype plugin: split [E#] out of text nodes into <cite data-eid> elements,
 *  preserving all surrounding markdown/KaTeX. */
function rehypeCitations() {
  return (tree: Root) => {
    const walk = (node: Root | Element) => {
      if (!("children" in node) || !node.children) return;
      const out: (Element | Text)[] = [];
      for (const child of node.children as (Element | Text)[]) {
        if (child.type === "text" && /\[E\d+\]/.test(child.value)) {
          for (const part of child.value.split(/(\[E\d+\])/g)) {
            if (!part) continue;
            const m = part.match(/^\[E(\d+)\]$/);
            if (m) {
              out.push({
                type: "element",
                tagName: "cite",
                properties: { dataEid: `E${m[1]}` },
                children: [{ type: "text", value: part }],
              } as Element);
            } else {
              out.push({ type: "text", value: part });
            }
          }
        } else {
          if (child.type === "element") walk(child);
          out.push(child);
        }
      }
      node.children = out;
    };
    walk(tree);
  };
}

export function TextBlock({
  text,
  citations,
  onCite,
}: {
  text: string;
  citations: Record<string, CitationInfo>;
  onCite: (c: CitationInfo) => void;
}) {
  return (
    <div className="prose-answer font-serif text-[0.95rem] leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex, rehypeCitations]}
        components={{
          cite({ node }) {
            const eid = (node?.properties?.dataEid as string) ?? "";
            return <CitationChip eid={eid} citation={citations[eid]} onClick={onCite} />;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
