export type VoiceRecognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: VoiceRecognitionEvent) => void) | null;
  onerror: ((event: VoiceRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  abort: () => void;
};

type VoiceRecognitionEvent = {
  results: ArrayLike<ArrayLike<{ transcript: string }>>;
};

type VoiceRecognitionErrorEvent = {
  error: string;
};

type VoiceRecognitionConstructor = new () => VoiceRecognition;

type SpeechWindow = Window & typeof globalThis & {
  SpeechRecognition?: VoiceRecognitionConstructor;
  webkitSpeechRecognition?: VoiceRecognitionConstructor;
};

export function createVoiceRecognition(): VoiceRecognition | null {
  const speechWindow = window as SpeechWindow;
  const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
  if (!Recognition) return null;

  const recognition = new Recognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = navigator.language || "en-US";
  return recognition;
}
