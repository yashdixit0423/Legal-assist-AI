import { useState } from "react";
import { LoaderCircle, Scale } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { login, register } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";

/**
 * Sign in and register.
 *
 * Login failures are always 401 with one message, whether the email is unknown
 * or the password is wrong — the backend does that deliberately so the form is
 * not an account-enumeration oracle. The server's message is shown verbatim
 * and no copy here distinguishes the two cases.
 */
export function Login() {
  return <AuthForm mode="login" />;
}

export function Register() {
  return <AuthForm mode="register" />;
}

function AuthForm({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isRegister = mode === "register";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (isRegister ? register(email, password) : login(email, password));
      navigate("/ask");
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not reach the server.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[hsl(var(--canvas))] px-5 py-10">
      <div className="w-full max-w-[400px]">
        <Link to="/ask" className="mb-7 flex items-center gap-3">
          <span className="brand-mark">
            <Scale size={18} strokeWidth={2.4} />
          </span>
          <span className="font-display text-[19px] tracking-[-0.02em]">
            LegalAssist <span className="text-[hsl(var(--brand))]">AI</span>
          </span>
        </Link>

        <h1 className="font-display text-[27px] leading-tight tracking-[-0.02em]">
          {isRegister ? "Create an account" : "Sign in"}
        </h1>
        <p className="mt-2 text-[13px] leading-relaxed text-[hsl(var(--ink-3))]">
          An account is only needed to ask questions, because asking spends your
          own provider key. Browsing and searching the corpus need nothing.
        </p>

        <form onSubmit={submit} className="mt-6 space-y-3">
          <label className="block">
            <span className="meta-label">Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1 w-full rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 py-2 text-[14px] outline-none focus:border-[hsl(var(--brand))]"
            />
          </label>
          <label className="block">
            <span className="meta-label">Password</span>
            <input
              type="password"
              required
              minLength={isRegister ? 12 : 1}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 w-full rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 py-2 text-[14px] outline-none focus:border-[hsl(var(--brand))]"
            />
            {isRegister && (
              <span className="mt-1 block text-[11px] text-[hsl(var(--ink-4))]">
                At least 12 characters. Length is the only rule that reliably
                helps.
              </span>
            )}
          </label>

          {error && (
            <p className="rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 py-2 text-[12.5px] text-[hsl(var(--ink-2))]">
              {error}
            </p>
          )}

          <Button type="submit" disabled={busy} className="w-full">
            {busy ? (
              <LoaderCircle size={15} className="animate-spin" />
            ) : isRegister ? (
              "Create account"
            ) : (
              "Sign in"
            )}
          </Button>
        </form>

        <p className="mt-5 text-[12.5px] text-[hsl(var(--ink-3))]">
          {isRegister ? "Already have an account? " : "No account yet? "}
          <Link
            to={isRegister ? "/login" : "/register"}
            className="font-semibold text-[hsl(var(--brand))] hover:underline"
          >
            {isRegister ? "Sign in" : "Create one"}
          </Link>
        </p>
      </div>
    </div>
  );
}
