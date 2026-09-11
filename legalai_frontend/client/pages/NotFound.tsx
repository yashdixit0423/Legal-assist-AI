import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";

const NotFound = () => (
  <LegalAssistLayout>
    <div className="mx-auto flex min-h-[65vh] max-w-[700px] flex-col items-center justify-center px-5 text-center">
      <div className="eyebrow">Page not found</div>
      <h1 className="mt-4 font-display text-5xl tracking-[-0.04em]">This page is not in the corpus.</h1>
      <p className="mt-4 max-w-md text-sm leading-6 text-[hsl(var(--ink-3))]">The page you were looking for does not exist. Head back to the reading room to continue.</p>
      <Link to="/" className="mt-7 inline-flex items-center gap-2 text-sm font-bold text-[hsl(var(--brand))] hover:underline"><ArrowLeft size={15} /> Return home</Link>
    </div>
  </LegalAssistLayout>
);

export default NotFound;
