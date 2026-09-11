import { useEffect, useState } from "react";
import {
  BookOpenText,
  LogIn,
  Menu,
  Moon,
  Scale,
  Search as SearchIcon,
  Settings2,
  Sun,
  X,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";

export function LegalAssistLayout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [dark, setDark] = useState(() => {
    const savedTheme = localStorage.getItem("legalassist-theme");
    const initialDark = savedTheme
      ? savedTheme === "dark"
      : document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", initialDark);
    return initialDark;
  });
  const [menuOpen, setMenuOpen] = useState(false);
  const { signedIn } = useAuth();

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("legalassist-theme", dark ? "dark" : "light");
  }, [dark]);

  const navItems = [
    { to: "/ask", label: "Ask", icon: Scale },
    { to: "/search", label: "Search", icon: SearchIcon },
    { to: "/browse", label: "Browse the law", icon: BookOpenText },
  ];

  return (
    <div className="min-h-screen bg-[hsl(var(--canvas))] text-[hsl(var(--ink))]">
      <header className="sticky top-0 z-40 border-b border-[hsl(var(--line))] bg-[hsl(var(--canvas)/.88)] backdrop-blur-xl">
        <div className="mx-auto flex h-[72px] max-w-[1440px] items-center justify-between px-5 sm:px-8 lg:px-10">
          <Link
            to="/ask"
            className="flex items-center gap-3"
            onClick={() => setMenuOpen(false)}
          >
            <span className="brand-mark">
              <Scale size={18} strokeWidth={2.4} />
            </span>
            <span className="font-display text-[19px] tracking-[-0.02em] text-[hsl(var(--ink))]">
              LegalAssist <span className="text-[hsl(var(--brand))]">AI</span>
            </span>
          </Link>

          <nav className="hidden items-center gap-1 rounded-full border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2)/.75)] p-1 md:flex">
            {navItems.map(({ to, label, icon: Icon }) => (
              <Link
                key={to}
                to={to}
                className={cn(
                  "nav-link",
                  location.pathname.startsWith(to) && "nav-link-active",
                )}
              >
                <Icon size={15} /> {label}
              </Link>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setDark((value) => !value)}
              className="icon-button"
              aria-label={
                dark ? "Switch to light theme" : "Switch to dark theme"
              }
            >
              {dark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            {!signedIn && (
              <Link
                to="/login"
                className="nav-link hidden sm:inline-flex"
                title="Sign in"
              >
                <LogIn size={15} /> Sign in
              </Link>
            )}
            <Link
              to="/settings"
              className={cn(
                "icon-button hidden sm:inline-flex",
                location.pathname === "/settings" && "icon-button-active",
              )}
              aria-label="Settings"
              title="Settings"
            >
              <Settings2 size={16} />
            </Link>
            <button
              className="icon-button md:hidden"
              onClick={() => setMenuOpen((open) => !open)}
              aria-label="Open navigation"
            >
              {menuOpen ? <X size={17} /> : <Menu size={17} />}
            </button>
          </div>
        </div>
        {menuOpen && (
          <div className="border-t border-[hsl(var(--line))] px-5 py-3 md:hidden">
            <div className="grid gap-1">
              {navItems.map(({ to, label, icon: Icon }) => (
                <Link
                  key={to}
                  to={to}
                  onClick={() => setMenuOpen(false)}
                  className={cn(
                    "nav-link",
                    location.pathname.startsWith(to) && "nav-link-active",
                  )}
                >
                  <Icon size={15} /> {label}
                </Link>
              ))}
              <Link
                to="/settings"
                onClick={() => setMenuOpen(false)}
                className={cn(
                  "nav-link",
                  location.pathname === "/settings" && "nav-link-active",
                )}
              >
                <Settings2 size={15} /> Settings
              </Link>
            </div>
          </div>
        )}
      </header>
      <main>{children}</main>
      <footer className="mx-auto flex max-w-[1440px] flex-col gap-2 border-t border-[hsl(var(--line))] px-5 py-7 text-xs text-[hsl(var(--ink-3))] sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-10">
        <p>LegalAssist AI · Read the source. Ask with context.</p>
        <p>
          Not legal advice. Each Act carries its own as-of date; see Browse.
        </p>
      </footer>
    </div>
  );
}
