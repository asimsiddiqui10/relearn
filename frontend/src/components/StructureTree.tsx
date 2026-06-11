"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import type { StructureNode } from "@/lib/types";

interface TreeNode extends StructureNode {
  children: TreeNode[];
}

function buildTree(nodes: StructureNode[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  nodes.forEach((n) => byId.set(n.id, { ...n, children: [] }));
  const roots: TreeNode[] = [];
  byId.forEach((node) => {
    if (node.parent_node_id && byId.has(node.parent_node_id)) {
      byId.get(node.parent_node_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

function NodeRow({
  node,
  depth,
  onJump,
}: {
  node: TreeNode;
  depth: number;
  onJump: (page: number) => void;
}) {
  return (
    <li>
      <button
        onClick={() => node.page_start != null && onJump(node.page_start + 1)}
        className={cn(
          "block w-full truncate rounded-md py-1.5 pr-2 text-left text-sm transition-colors hover:bg-accent",
          depth === 0 ? "font-medium text-foreground" : "text-muted-foreground",
        )}
        style={{ paddingLeft: 10 + depth * 14 }}
        title={node.heading_text ?? ""}
      >
        {node.heading_text || "(untitled)"}
      </button>
      {node.children.length > 0 && (
        <ul>
          {node.children.map((c) => (
            <NodeRow key={c.id} node={c} depth={depth + 1} onJump={onJump} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function StructureTree({
  nodes,
  onJump,
}: {
  nodes: StructureNode[];
  onJump: (page: number) => void;
}) {
  const tree = useMemo(() => buildTree(nodes), [nodes]);
  if (nodes.length === 0) {
    return <p className="px-2 py-4 text-sm text-muted-foreground">No structure extracted.</p>;
  }
  return (
    <ul className="space-y-0.5">
      {tree.map((n) => (
        <NodeRow key={n.id} node={n} depth={0} onJump={onJump} />
      ))}
    </ul>
  );
}
