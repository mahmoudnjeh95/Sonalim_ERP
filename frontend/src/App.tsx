import { useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";
import { queryClient } from "./lib/query-client";
import { AuthProvider } from "./lib/auth";
import { I18nProvider } from "./lib/i18n";
import { HelpTooltipProvider } from "./components/patterns/HelpTooltip";
import { AppSplash } from "./components/patterns/AppSplash";
import { router } from "./routes/router";

export default function App() {
  const [showSplash, setShowSplash] = useState(true);

  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AuthProvider>
          {showSplash && <AppSplash onFinished={() => setShowSplash(false)} />}
          <HelpTooltipProvider delayDuration={200}>
            <RouterProvider router={router} />
          </HelpTooltipProvider>
          <Toaster
            position="top-right"
            toastOptions={{
              classNames: {
                toast: "rounded-lg border border-border bg-background shadow-raised font-sans",
                title: "text-sm font-medium text-foreground",
                description: "text-sm text-muted-foreground",
                success: "!border-success/20",
                error: "!border-destructive/20",
              },
            }}
          />
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
