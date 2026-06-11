"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Library, LogOut, PanelLeft } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";

export function AppSidebar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const initial = (user?.email?.[0] ?? "?").toUpperCase();
  const navActive = pathname?.startsWith("/spaces");

  return (
    <aside
      className={cn(
        "flex h-dvh shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-all duration-300",
        collapsed ? "w-14" : "w-60",
      )}
    >
      {/* header: logo + collapse toggle */}
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

      {/* nav */}
      <nav className="flex-1 px-2.5 py-1">
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
      </nav>

      {/* user */}
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
