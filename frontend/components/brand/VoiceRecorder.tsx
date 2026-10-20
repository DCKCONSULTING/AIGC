"use client";

import { useEffect, useRef, useState } from "react";

type VoiceRecorderProps = {
  disabled?: boolean;
  onRecorded: (file: File) => void;
};

function formatTime(total: number) {
  const minutes = Math.floor(total / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (total % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function VoiceRecorder({ disabled, onRecorded }: VoiceRecorderProps) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    return () => {
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, []);

  async function start() {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser cannot record audio.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : MediaRecorder.isTypeSupported("audio/mp4")
          ? "audio/mp4"
          : "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const type = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        const ext = type.includes("mp4") ? "m4a" : "webm";
        onRecorded(new File([blob], `instruction.${ext}`, { type }));
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
      setSeconds(0);
      timerRef.current = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    } catch {
      setError("Allow microphone access to record your instruction.");
    }
  }

  function stop() {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
    if (timerRef.current) window.clearInterval(timerRef.current);
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={disabled}
          onClick={recording ? stop : start}
          className={`h-12 rounded-full px-6 text-sm font-medium disabled:opacity-60 ${
            recording ? "bg-red-600 text-white hover:bg-red-700" : "bg-gold hover:bg-gold-deep"
          }`}
        >
          {recording ? "Stop recording" : "Record voice"}
        </button>
        {recording ? (
          <p className="text-sm font-medium text-red-700">Recording {formatTime(seconds)}</p>
        ) : null}
      </div>
      <p className="mt-2 text-sm text-muted">
        We’ll ask for microphone access, then turn your recording into text for you to confirm.
      </p>
      {error ? <p className="mt-2 text-sm text-red-700">{error}</p> : null}
    </div>
  );
}
