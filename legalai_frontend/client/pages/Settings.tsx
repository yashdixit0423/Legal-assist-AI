import { useState } from "react";
import {
  Check,
  KeyRound,
  LoaderCircle,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";
import { formatDate } from "@/components/SectionReader";
import {
  deleteCredential,
  listCredentials,
  putCredential,
  verifyCredential,
} from "@/lib/api/corpus";
import { me } from "@/lib/api/auth";
import { useAuth } from "@/hooks/use-auth";
import {
  PROVIDERS,
  type Provider,
  type VerifyCredentialResponse,
} from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The provider-key vault.
 *
 * The key is write-only: the server stores AES-256-GCM ciphertext and returns
 * only the last four characters. There is deliberately no reveal control here,
 * because there is nothing to reveal — a "show key" affordance would be a
 * button that cannot work.
 */
export default function Settings() {
  const { signedIn, signOut } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState<Provider>("openai");
  const [apiKey, setApiKey] = useState("");
  const [verification, setVerification] =
    useState<VerifyCredentialResponse | null>(null);

  const account = useQuery({
    queryKey: ["me"],
    queryFn: me,
    enabled: signedIn,
  });
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: listCredentials,
    enabled: signedIn,
  });

  const save = useMutation({
    mutationFn: () => putCredential(provider, apiKey.trim()),
    onSuccess: () => {
      setApiKey("");
      setVerification(null);
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
  });

  const verify = useMutation({
    mutationFn: (target: Provider) => verifyCredential(target),
    onSuccess: (result) => {
      setVerification(result);
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
  });

  const remove = useMutation({
    mutationFn: (target: string) => deleteCredential(target),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["credentials"] }),
  });

  if (!signedIn) {
    return (
      <LegalAssistLayout>
        <div className="mx-auto max-w-[620px] px-5 py-16 text-center sm:px-8">
          <h1 className="font-display text-[26px]">
            Sign in to manage your keys
          </h1>
          <p className="mt-2 text-[14px] text-[hsl(var(--ink-3))]">
            Browsing and searching the corpus needs no account. Asking questions
            spends your own provider key, so it does.
          </p>
          <Link to="/login" className="mt-5 inline-block">
            <Button>Sign in</Button>
          </Link>
        </div>
      </LegalAssistLayout>
    );
  }

  return (
    <LegalAssistLayout>
      <div className="mx-auto max-w-[720px] px-5 py-10 sm:px-8">
        <h1 className="font-display text-[30px] leading-tight tracking-[-0.02em]">
          Settings
        </h1>

        <section className="settings-card mt-7">
          <div className="meta-label mb-1 flex items-center gap-1.5">
            <ShieldCheck size={12} /> Account
          </div>
          <p className="text-[14px] text-[hsl(var(--ink))]">
            {account.data?.email ?? "…"}
          </p>
          {account.data && (
            <p className="mt-0.5 text-[11.5px] text-[hsl(var(--ink-4))]">
              Joined {formatDate(account.data.created_at)}
            </p>
          )}
          <button
            onClick={() => {
              signOut();
              navigate("/ask");
            }}
            className="mt-3 text-[12px] font-semibold text-[hsl(var(--brand))] hover:underline"
          >
            Sign out
          </button>
          <p className="mt-1 text-[11px] text-[hsl(var(--ink-4))]">
            Signing out clears the tokens in this browser. The server holds no
            session to end.
          </p>
        </section>

        <section className="settings-card mt-4">
          <div className="meta-label mb-1 flex items-center gap-1.5">
            <KeyRound size={12} /> Provider key
          </div>
          <p className="mb-4 text-[12.5px] leading-relaxed text-[hsl(var(--ink-3))]">
            Encrypted on write and never returned by any endpoint. Only the last
            four characters are stored in readable form, so you can tell which
            key is which.
          </p>

          <div className="flex flex-wrap gap-2">
            {PROVIDERS.map((option) => (
              <button
                key={option}
                onClick={() => setProvider(option)}
                className={cn(
                  "rounded-lg border px-3 py-1.5 text-[12px] font-semibold capitalize transition-colors",
                  provider === option
                    ? "border-[hsl(var(--brand))] bg-[hsl(var(--brand-soft))] text-[hsl(var(--brand))]"
                    : "border-[hsl(var(--line))] text-[hsl(var(--ink-3))]",
                )}
              >
                {option}
              </button>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="Paste the key — it is sent once and never read back"
              className="min-w-[240px] flex-1 rounded-lg border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-3 py-2 text-[13px] outline-none focus:border-[hsl(var(--brand))]"
            />
            <Button
              onClick={() => save.mutate()}
              disabled={apiKey.trim().length < 8 || save.isPending}
            >
              {save.isPending ? (
                <LoaderCircle size={14} className="animate-spin" />
              ) : (
                "Save key"
              )}
            </Button>
          </div>
          {save.isError && (
            <p className="mt-2 text-[12px] text-[hsl(var(--ink-3))]">
              {(save.error as Error).message}
            </p>
          )}

          <div className="mt-6 space-y-2">
            {credentials.data?.length === 0 && (
              <p className="text-[12.5px] text-[hsl(var(--ink-4))]">
                No key stored yet. Asking a question needs one — browsing and
                searching do not.
              </p>
            )}
            {credentials.data?.map((credential) => (
              <div
                key={credential.provider}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] px-4 py-3"
              >
                <div>
                  <div className="text-[13.5px] font-semibold capitalize text-[hsl(var(--ink))]">
                    {credential.provider}
                  </div>
                  <div className="mt-0.5 font-mono text-[12px] text-[hsl(var(--ink-3))]">
                    ••••••••{credential.key_hint ?? "????"}
                  </div>
                  <div className="mt-0.5 text-[11px] text-[hsl(var(--ink-4))]">
                    {credential.last_verified_at
                      ? `verified ${formatDate(credential.last_verified_at)}`
                      : "not verified yet"}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() =>
                      verify.mutate(credential.provider as Provider)
                    }
                    disabled={verify.isPending}
                    className="rounded-lg border border-[hsl(var(--line))] px-2.5 py-1.5 text-[11.5px] font-semibold text-[hsl(var(--ink-2))] hover:border-[hsl(var(--brand))]"
                  >
                    {verify.isPending ? "Checking…" : "Verify"}
                  </button>
                  <button
                    onClick={() => remove.mutate(credential.provider)}
                    className="icon-button"
                    aria-label={`Delete the ${credential.provider} key`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/*
            verify returns 200 with valid:false for a bad key. It is an answer
            to a question about a key, not a failed request, so it renders
            inline rather than as an error.
          */}
          {verification && (
            <div
              className={cn(
                "mt-3 flex items-start gap-2 rounded-xl border p-3 text-[12.5px]",
                verification.valid
                  ? "border-[hsl(var(--brand))] bg-[hsl(var(--brand-soft))] text-[hsl(var(--brand))]"
                  : "border-[hsl(var(--line))] bg-[hsl(var(--canvas-2))] text-[hsl(var(--ink-2))]",
              )}
            >
              {verification.valid ? (
                <Check size={14} className="mt-0.5 shrink-0" />
              ) : (
                <X size={14} className="mt-0.5 shrink-0" />
              )}
              <span>
                {verification.valid
                  ? `The ${verification.provider} key works.`
                  : (verification.message ?? "That key was rejected.")}
              </span>
            </div>
          )}
        </section>
      </div>
    </LegalAssistLayout>
  );
}
