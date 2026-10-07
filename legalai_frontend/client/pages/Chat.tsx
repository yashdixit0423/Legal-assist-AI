import { ChatEmptyState } from "@/components/chat/ChatEmptyState";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { LegalAssistLayout } from "@/components/LegalAssistLayout";

/**
 * Page shell. The conversation lives in memory only (nothing is persisted);
 * the message list and composer slot into the scroll area and the bottom bar.
 */
export default function Chat() {
  return (
    <LegalAssistLayout variant="app">
      <div className="mx-auto flex min-h-0 w-full max-w-[840px] flex-1 flex-col px-5 sm:px-8">
        <ChatHeader onNewChat={() => {}} canReset={false} />

        <div className="min-h-0 flex-1 overflow-y-auto">
          <ChatEmptyState />
        </div>

        <div className="pb-[max(1rem,env(safe-area-inset-bottom))] pt-3">
          <p className="text-center text-[11px] text-[hsl(var(--ink-4))]">
            Informational assistance, not legal advice. Verify important matters
            with a qualified professional.
          </p>
        </div>
      </div>
    </LegalAssistLayout>
  );
}
