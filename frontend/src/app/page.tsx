"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { Spinner } from "@/components/ui/spinner";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(user ? "/spaces" : "/login");
  }, [user, loading, router]);

  return (
    <div className="flex h-screen items-center justify-center">
      <Spinner className="h-6 w-6 text-muted-foreground" />
    </div>
  );
}
