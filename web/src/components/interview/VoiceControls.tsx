"use client";

import { useEffect, useRef, useState } from "react";
import { engagementApi } from "@/lib/api-engagement";
import { createRecognition, delivery, deliveryTip, recognitionAvailable, speak, speechAvailable, stopSpeaking } from "@/lib/voice";

const PREF = "mindmesh_voice_mode";

/**
 * Voice mode for mock interviews (P3): reads each question aloud and turns a spoken answer into text in
 * the answer box, which the learner can edit before submitting. Typing always works.
 */
export default function VoiceControls({ question, disabled, onText }: {
  question: string;
  disabled: boolean;
  onText: (text: string) => void;
}) {
  const [on, setOn] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [tip, setTip] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const rec = useRef<ReturnType<typeof createRecognition>>(null);
  const said = useRef("");
  const started = useRef(0);
  const canListen = recognitionAvailable();

  useEffect(() => {
    try { setOn(localStorage.getItem(PREF) === "on"); } catch { /* storage unavailable */ }
  }, []);

  useEffect(() => {
    if (on && question) speak(question);  // read each new question aloud in voice mode
    setTip(null);
    return () => stopSpeaking();
  }, [on, question]);

  function toggle() {
    const next = !on;
    setOn(next);
    try { localStorage.setItem(PREF, next ? "on" : "off"); } catch { /* ignore */ }
    if (!next) stop();
  }

  function start() {
    setErr(null);
    setTip(null);
    stopSpeaking();
    const r = createRecognition();
    if (!r) return;
    said.current = "";
    started.current = Date.now();
    r.onresult = (e) => {
      let finalText = "";
      let interimText = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText += res[0].transcript;
        else interimText += res[0].transcript;
      }
      if (finalText.trim()) {
        said.current = `${said.current} ${finalText.trim()}`.trim();
        onText(finalText.trim());
      }
      setInterim(interimText);
    };
    r.onerror = (e) => {
      setErr(e.error === "not-allowed" ? "Microphone access is blocked. Allow it in your browser, or type your answer." : "Voice input stopped. You can try again or type your answer.");
    };
    r.onend = () => {
      setListening(false);
      setInterim("");
      const seconds = (Date.now() - started.current) / 1000;
      if (said.current) {
        const d = delivery(said.current, seconds);
        setTip(deliveryTip(d));
        engagementApi.event("voice_answer", { seconds: d.seconds, wpm: d.wpm, fillers: d.fillers });
      }
    };
    rec.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      setErr("Voice input couldn't start. You can type your answer.");
    }
  }

  function stop() {
    rec.current?.stop();
  }

  return (
    <div className="stack-sm">
      <div className="row" style={{ gap: ".5rem" }}>
        <button type="button" className="ghost small" aria-pressed={on} onClick={toggle} style={{ minHeight: 44 }}>
          Voice mode {on ? "on" : "off"}
        </button>
        {on && speechAvailable() && (
          <button type="button" className="ghost small" onClick={() => speak(question)} style={{ minHeight: 44 }}>Read the question again</button>
        )}
        {on && canListen && (listening ? (
          <button type="button" className="dark" onClick={stop} style={{ minHeight: 44 }}>Stop</button>
        ) : (
          <button type="button" onClick={start} disabled={disabled} style={{ minHeight: 44 }}>Answer out loud</button>
        ))}
      </div>
      {on && !canListen && (
        <p className="notice info small" style={{ margin: 0 }}>This browser can read questions aloud but can&apos;t take spoken answers. Type your answer, or try Chrome, Edge or Safari.</p>
      )}
      {on && canListen && (
        <p className="muted small" style={{ margin: 0 }}>
          Your browser turns your speech into text (in Chrome and Edge, on the browser maker&apos;s servers). Mindmesh only receives the text you submit, and you can edit it first.
        </p>
      )}
      <p className="small" role="status" aria-live="polite" style={{ margin: 0 }}>
        {listening ? `Listening…${interim ? ` “${interim}”` : ""}` : tip ?? ""}
      </p>
      {err && <p className="notice bad small" role="alert" style={{ margin: 0 }}>{err}</p>}
    </div>
  );
}
