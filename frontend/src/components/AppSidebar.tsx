"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Library, LogOut, MessageSquarePlus, PanelLeft } from "lucide-react";
import { api, type ChatSession } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";

/** /spaces/<id>/... → id, else null */
function spaceIdFrom(pathname: string | null): string | null {
  const m = pathname?.match(/^\/spaces\/([^/]+)/);
  return m ? m[1] : null;
}
function sessionIdFrom(pathname: string | null): string | null {
  const m = pathname?.match(/\/chat\/([^/]+)/);
  return m ? m[1] : null;
}

export function AppSidebar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [chats, setChats] = useState<ChatSession[]>([]);
  const menuRef = useRef<HTMLDivElement>(null);

  const spaceId = spaceIdFrom(pathname);
  const activeSession = sessionIdFrom(pathname);

  const loadChats = useCallback(() => {
    if (!spaceId) {
      setChats([]);
      return;
    }
    api.listChatSessions(spaceId).then(setChats).catch(() => {});
  }, [spaceId]);

  // refetch on navigation (covers new sessions + first-message auto-titles)
  useEffect(() => {
    loadChats();
  }, [loadChats, pathname]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  async function newChat() {
    if (!spaceId) return;
    const cs = await api.createChatSession(spaceId);
    setChats((c) => [cs, ...c]);
    router.push(`/spaces/${spaceId}/chat/${cs.id}`);
  }

  const initial = (user?.email?.[0] ?? "?").toUpperCase();
  const navActive = pathname === "/spaces" || (!!spaceId && !activeSession);

  return (
    <aside
      className={cn(
        "flex h-dvh shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-all duration-300",
        collapsed ? "w-14" : "w-64",
      )}
    >
      <div className="flex h-14 items-center justify-between px-3">
        {!collapsed && (
          <Link href="/spaces" className="fade-rise px-2 font-serif text-2xl font-light">
            Relearn
          </Link>
        )}
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title={collapsed ? "Expand" : "Collapse"}
        >
          <PanelLeft className="h-4 w-4" />
        </button>
      </div>

      <nav className="flex min-h-0 flex-1 flex-col px-2.5 py-1">
        <Link
          href="/spaces"
          className={cn(
            "flex h-9 items-center gap-3 rounded-md px-2.5 text-sm transition-colors",
            navActive
              ? "bg-accent font-medium text-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-foreground",
            collapsed && "justify-center px-0",
          )}
          title="Spaces"
        >
          <Library className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Spaces</span>}
        </Link>

        {/* recent chats for the current space */}
        {!collapsed && spaceId && (
          <div className="mt-4 flex min-h-0 flex-1 flex-col">
            <div className="mb-1 flex items-center justify-between px-2.5">
              <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground/70">
                Chats
              </span>
              <button
                onClick={newChat}
                className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                title="New chat"
              >
                <MessageSquarePlus className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-0.5">
              {chats.length === 0 ? (
                <p className="px-2.5 py-2 text-xs text-muted-foreground/60">No chats yet.</p>
              ) : (
                chats.map((c) => (
                  <Link
                    key={c.id}
                    href={`/spaces/${spaceId}/chat/${c.id}`}
                    title={c.title ?? "New chat"}
                    className={cn(
                      "block truncate rounded-md px-2.5 py-1.5 text-sm transition-colors",
                      c.id === activeSession
                        ? "bg-accent font-medium text-foreground"
                        : "text-muted-foreground hover:bg-accent hover:text-foreground",
                    )}
                  >
                    {c.title ?? "New chat"}
                  </Link>
                ))
              )}
            </div>
          </div>
        )}
      </nav>

      <div ref={menuRef} className="relative border-t border-sidebar-border p-2.5">
        {menuOpen && !collapsed && (
          <div className="absolute bottom-full left-2.5 mb-1 w-[calc(100%-1.25rem)] rounded-lg border border-border bg-popover p-1 shadow-lg">
            <button
              onClick={logout}
              className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-accent"
            >
              <LogOut className="h-4 w-4 text-muted-foreground" /> Sign out
            </button>
          </div>
        )}
        <button
          onClick={() => (collapsed ? logout() : setMenuOpen((v) => !v))}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-md p-1.5 transition-colors hover:bg-accent",
            collapsed && "justify-center",
          )}
          title={collapsed ? "Sign out" : user?.email}
        >
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary font-serif text-sm font-medium text-primary-foreground">
            {initial}
          </span>
          {!collapsed && (
            <span className="min-w-0 flex-1 truncate text-left text-xs text-muted-foreground">
              {user?.email}
            </span>
          )}
        </button>
      </div>
    </aside>
  );
}
