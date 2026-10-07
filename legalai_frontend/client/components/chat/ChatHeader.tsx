import { SquarePen } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ChatHeader({
  onNewChat,
  canReset,
}: {
  onNewChat: () => void;
  /** False while there is nothing to clear; the button is then inert. */
  canReset: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[hsl(var(--line))] py-5">
      <div className="min-w-0">
        <h1 className="font-display text-[26px] leading-tight tracking-[-0.02em] text-[hsl(var(--ink))]">
          Legal AI Assistant
        </h1>
        <p className="mt-1 text-[13px] leading-relaxed text-[hsl(var(--ink-3))]">
          A conversation grounded in the indexed Acts, with every answer cited
          to its section.
        </p>
        <p className="mt-1 text-[11px] text-[hsl(var(--ink-3))]">
          Conversations aren't saved. Reloading starts a new chat.
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={onNewChat}
        disabled={!canReset}
        className="shrink-0"
      >
        <SquarePen /> New chat
      </Button>
    </div>
  );
}
