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
    <div className="flex h-dvh items-center justify-center">
      <Spinner className="h-5 w-5 text-muted-foreground" />
    </div>
  );
}
