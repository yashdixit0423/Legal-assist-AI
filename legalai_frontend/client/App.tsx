import "./global.css";

import { Toaster } from "@/components/ui/toaster";
import { createRoot } from "react-dom/client";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Ask from "./pages/Ask";
import Browse from "./pages/Browse";
import Search from "./pages/Search";
import Section from "./pages/Section";
import Settings from "./pages/Settings";
import { Login, Register } from "./pages/Auth";
import NotFound from "./pages/NotFound";
import { ApiError } from "@/lib/api/client";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Corpus reads carry ETag + max-age=300; match that rather than fight it.
      staleTime: 5 * 60 * 1000,
      // A 404 or a 422 will not become a 200 by asking again. Only retry
      // transport-level failures, and only once.
      retry: (attempts, error) => !(error instanceof ApiError) && attempts < 1,
    },
  },
});

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/ask" replace />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/browse" element={<Browse />} />
          <Route path="/browse/:slug" element={<Browse />} />
          <Route path="/search" element={<Search />} />
          <Route path="/sections/:sectionId" element={<Section />} />
          <Route
            path="/statutes/:slug/sections/:sectionNo"
            element={<Section />}
          />
          <Route path="/settings" element={<Settings />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

createRoot(document.getElementById("root")!).render(<App />);
