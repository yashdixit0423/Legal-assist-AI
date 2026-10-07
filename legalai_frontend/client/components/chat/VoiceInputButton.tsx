import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";
import { toast } from "sonner";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { MAX_QUESTION_CHARS } from "./ChatComposer";

/**
 * Voice input through the browser's own speech recognition (decision D1 = A).
 *
 * The transcript goes into the composer for the user to read and edit; it is
 * never sent on its own. In browsers without the API (Firefox, for one) the
 * button is not rendered at all, rather than offered and then refused.
 *
 * Privacy note for the UI copy: Chrome and Edge send the audio to Google,
 * Safari to Apple. Nothing reaches the LegalAssist server but the text.
 */

// The Web Speech API is not in TypeScript's DOM library; this is the slice used.
interface RecognitionResult {
  readonly isFinal: boolean;
  readonly 0: { readonly transcript: string };
}
interface RecognitionEvent {
  readonly resultIndex: number;
  readonly results: {
    readonly length: number;
    [index: number]: RecognitionResult;
  };
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}
type RecognitionConstructor = new () => Recognition;

function recognitionConstructor(): RecognitionConstructor | null {
  const scope = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

export const voiceSupported = () =>
  recognitionConstructor() !== null &&
  typeof navigator.mediaDevices?.getUserMedia === "function";

export function VoiceInputButton({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const [supported] = useState(voiceSupported);
  const [listening, setListening] = useState(false);
  const recognition = useRef<Recognition | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;

  const stop = useCallback(() => recognition.current?.stop(), []);

  // Never keep the microphone open behind a page the user has left, and stop
  // listening the moment an answer starts streaming.
  useEffect(() => () => recognition.current?.abort(), []);
  useEffect(() => {
    if (disabled) recognition.current?.abort();
  }, [disabled]);

  const start = useCallback(async () => {
    const Constructor = recognitionConstructor();
    if (!Constructor) return;
    try {
      // Ask for the microphone explicitly so a refusal is caught here, with
      // a clear message, rather than as an opaque recognition error.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
    } catch {
      toast("Microphone access is required for voice input.");
      return;
    }

    const instance = new Constructor();
    instance.lang = "en-IN";
    instance.continuous = true;
    instance.interimResults = true;

    // Dictation continues whatever was already typed.
    const base = valueRef.current.trim();
    let committed = "";
    instance.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) committed += result[0].transcript;
        else interim += result[0].transcript;
      }
      const spoken = `${committed}${interim}`.replace(/\s+/g, " ").trim();
      onChange(
        [base, spoken].filter(Boolean).join(" ").slice(0, MAX_QUESTION_CHARS),
      );
    };
    instance.onerror = (event) => {
      if (event.error === "aborted") return;
      if (
        event.error === "not-allowed" ||
        event.error === "service-not-allowed"
      ) {
        toast("Microphone access is required for voice input.");
      } else {
        toast("Couldn't transcribe that, try again.");
      }
    };
    instance.onend = () => {
      setListening(false);
      recognition.current = null;
    };
    recognition.current = instance;
    try {
      instance.start();
      setListening(true);
    } catch {
      recognition.current = null;
      toast("Couldn't transcribe that, try again.");
    }
  }, [onChange]);

  if (!supported) return null;

  if (listening) {
    return (
      <span className="flex items-center gap-2" role="status">
        <span className="flex items-center gap-1.5 text-[12px] font-semibold text-[hsl(var(--brand))]">
          <span className="status-dot animate-pulse" aria-hidden="true" />
          Listening…
        </span>
        <button
          type="button"
          onClick={stop}
          className="icon-button icon-button-active h-8 w-8"
          aria-label="Stop voice input"
        >
          <Square size={12} className="fill-current" />
        </button>
      </span>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={() => void start()}
          disabled={disabled}
          className="icon-button h-8 w-8 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="Voice input — dictate into the message box"
        >
          <Mic size={15} />
        </button>
      </TooltipTrigger>
      <TooltipContent>
        Dictate. You review the text before sending.
      </TooltipContent>
    </Tooltip>
  );
}
