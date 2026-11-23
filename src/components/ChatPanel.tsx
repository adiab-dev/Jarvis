import { type FormEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useAnimationControls } from "framer-motion";
import "./ChatPanel.css";

type Message = { id: string; role: "user" | "assistant"; content: string };
type ToolConfirmation = { approval_id: string; path: string; mode: string; content?: string };

const API_URL = "http://127.0.0.1:8008";

export default function ChatPanel({
  visible,
  onConversationStart,
  onSpeechLevel,
}: {
  visible: boolean;
  onConversationStart: () => void;
  onSpeechLevel: (level: number) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [inputHeight, setInputHeight] = useState(44);
  const [pendingMessage, setPendingMessage] = useState<Message | null>(null);
  const [drawBorder, setDrawBorder] = useState(false);
  const [sending, setSending] = useState(false);
  const [sparksVisible, setSparksVisible] = useState(true);
  const [replayActive, setReplayActive] = useState(false);
  const [replayPending, setReplayPending] = useState(false);
  const [thinkingVisible, setThinkingVisible] = useState(false);
  const [toolConfirmation, setToolConfirmation] = useState<ToolConfirmation | null>(null);
  const [approvalSending, setApprovalSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const flightRef = useRef<HTMLElement>(null);
  const landingRef = useRef<HTMLElement>(null);
  const [borderSize, setBorderSize] = useState({ width: 0, height: 0 });
  const audioCleanupRef = useRef<() => void>(() => undefined);
  const flightControls = useAnimationControls();

  useEffect(() => {
    const list = messageListRef.current;
    if (list) list.scrollTo({ top: list.scrollHeight, behavior: "instant" as ScrollBehavior });
  }, [messages.length]);

  useEffect(() => {
    if (!visible) return;
    const frame = requestAnimationFrame(() => textareaRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [visible]);

  useLayoutEffect(() => {
    if (!visible || messages.length === 0) {
      setReplayActive(false);
      setReplayPending(false);
      return;
    }
    setReplayActive(false);
    setReplayPending(true);
    const replayTimer = window.setTimeout(() => {
      setReplayPending(false);
      setReplayActive(true);
    }, 820);
    // The composer has just finished revealing; let the first bubbles start
    // rising for a beat before the orb responds to their movement.
    const orbTimer = window.setTimeout(onConversationStart, 920);
    return () => {
      window.clearTimeout(replayTimer);
      window.clearTimeout(orbTimer);
    };
  }, [visible]);

  useEffect(() => {
    if (!visible) {
      setSparksVisible(false);
      return;
    }
    setSparksVisible(true);
    const timer = window.setTimeout(() => setSparksVisible(false), 900);
    return () => window.clearTimeout(timer);
  }, [visible]);

  useEffect(() => () => audioCleanupRef.current(), []);

  function resizeTextarea(value: string) {
    const textarea = textareaRef.current;
    if (!textarea) return;
    if (!value) {
      setInputHeight(44);
      textarea.style.overflowY = "hidden";
      setInput(value);
      return;
    }
    const maxHeight = Number.parseFloat(getComputedStyle(textarea).maxHeight);
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, 44), maxHeight);
    setInputHeight(nextHeight);
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
    setInput(value);
  }

  function speak(blob: Blob) {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    let context: AudioContext | undefined;
    let frame = 0;
    let source: MediaElementAudioSourceNode | undefined;
    let analyser: AnalyserNode | undefined;

    const cleanup = () => {
      cancelAnimationFrame(frame);
      audio.pause();
      audio.onended = null;
      audio.onerror = null;
      URL.revokeObjectURL(url);
      if (context && context.state !== "closed") void context.close();
      onSpeechLevel(0);
    };
    audioCleanupRef.current();
    audioCleanupRef.current = cleanup;
    audio.onended = cleanup;
    audio.onerror = cleanup;

    try {
      context = new AudioContext();
      analyser = context.createAnalyser();
      analyser.fftSize = 256;
      source = context.createMediaElementSource(audio);
      source.connect(analyser);
      analyser.connect(context.destination);
      void context.resume();
    } catch (error) {
      console.warn("Audio level analysis is unavailable; playing TTS without orb sync.", error);
    }

    void audio.play().then(() => {
      const samples = analyser ? new Uint8Array(analyser.fftSize) : null;
      const readLevel = () => {
        if (!samples || !analyser || audio.paused || audio.ended) return;
        analyser.getByteTimeDomainData(samples);
        let energy = 0;
        for (const sample of samples) {
          const normalized = (sample - 128) / 128;
          energy += normalized * normalized;
        }
        const rms = Math.sqrt(energy / samples.length);
        onSpeechLevel(Math.min(1, Math.max(0, (rms - 0.015) * 3.7)));
        frame = requestAnimationFrame(readLevel);
      };
      readLevel();
    }).catch((error) => {
      console.warn("Jarvis speech playback failed:", error);
      cleanup();
    });
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    const userMessage: Message = { id: crypto.randomUUID(), role: "user", content: text };
    const history = [...messages, userMessage];
    const assistantMessage: Message = { id: crypto.randomUUID(), role: "assistant", content: "" };
    setPendingMessage(userMessage);
    setMessages([...history, assistantMessage]);
    setThinkingVisible(false);
    resizeTextarea("");
    setSending(true);

    try {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      await flightControls.start({
        opacity: 1,
        y: -16,
        transition: { duration: 0.24, ease: [0.18, 0.72, 0.25, 1] },
      });
      await flightControls.start({
        width: "58%",
        transition: { duration: 0.32, ease: [0.18, 0.72, 0.25, 1] },
      });
      messageListRef.current?.scrollTo({ top: messageListRef.current.scrollHeight, behavior: "instant" as ScrollBehavior });
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      const flightRect = flightRef.current?.getBoundingClientRect();
      const landingRect = landingRef.current?.getBoundingClientRect();
      if (!flightRect || !landingRect) throw new Error("Could not position the sent message.");
      setBorderSize({ width: landingRect.width, height: landingRect.height });
      setDrawBorder(true);
      const landingAnimation = flightControls.start({
        x: landingRect.left - flightRect.left,
        y: landingRect.top - flightRect.top,
        width: landingRect.width,
        transition: { duration: 1.4, ease: [0.22, 1, 0.36, 1] },
      });
      await new Promise<void>((resolve) => window.setTimeout(resolve, 110));
      onConversationStart();
      await landingAnimation;
      setPendingMessage(null);
      setDrawBorder(false);
      setThinkingVisible(true);

      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history.map(({ role, content }) => ({ role, content })) }),
      });
      if (!response.ok) throw new Error(`Chat request failed (${response.status})`);
      if (!response.body) throw new Error("The chat service did not return a response stream.");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullResponse = "";
      const appendChunk = (line: string) => {
        if (!line.trim()) return;
        const chunk = JSON.parse(line) as {
          content?: string;
          error?: string;
          confirmation_required?: ToolConfirmation;
        };
        if (chunk.error) throw new Error(chunk.error);
        if (chunk.confirmation_required) setToolConfirmation(chunk.confirmation_required);
        if (chunk.content) {
          fullResponse += chunk.content;
          setMessages((current) => {
            const next = [...current];
            const last = next[next.length - 1];
            if (last?.role === "assistant") {
              next[next.length - 1] = { ...last, content: last.content + chunk.content };
            }
            return next;
          });
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        lines.forEach(appendChunk);
        if (done) break;
      }
      appendChunk(buffer);

      if (fullResponse.trim()) {
        try {
          const speech = await fetch(`${API_URL}/tts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: fullResponse }),
          });
          if (speech.ok && speech.headers.get("content-type")?.startsWith("audio/")) {
            speak(await speech.blob());
          }
        } catch (error) {
          console.warn("Jarvis TTS request failed:", error);
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      setPendingMessage(null);
      setDrawBorder(false);
      setMessages((current) => {
        if (current[current.length - 1]?.id !== assistantMessage.id) {
          return [...history, { ...assistantMessage, content: `Could not reach Jarvis: ${message}` }];
        }
        const next = [...current];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { ...last, content: `Could not reach Jarvis: ${message}` };
        }
        return next;
      });
    } finally {
      setSending(false);
    }
  }

  async function answerToolConfirmation(approved: boolean) {
    if (!toolConfirmation || approvalSending) return;
    setApprovalSending(true);
    try {
      const response = await fetch(`${API_URL}/tool-approval`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_id: toolConfirmation.approval_id, approved }),
      });
      if (!response.ok) throw new Error(`Confirmation response failed (${response.status})`);
      setToolConfirmation(null);
    } catch (error) {
      console.error("Could not send file change confirmation:", error);
    } finally {
      setApprovalSending(false);
    }
  }

  return (
    <section className={`chat-interface ${visible ? "" : "chat-interface-hidden"}`} aria-label="Jarvis chat">
      <AnimatePresence initial={false}>
        {messages.length > 0 && (
          <motion.div
            className={`chat-transcript ${replayPending ? "chat-transcript-replay-pending" : ""}`}
            initial={false}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 14 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
          >
            <div className="chat-messages" aria-live="polite" ref={messageListRef}>
              {messages.map((message) => (
                <motion.article
                  ref={pendingMessage?.id === message.id ? landingRef : undefined}
                  className={`chat-message chat-message-${message.role} ${pendingMessage?.id === message.id ? "chat-message-landing-hidden" : ""} ${pendingMessage && message.role === "assistant" && !message.content ? "chat-message-assistant-pending" : ""}`}
                  key={message.id}
                  initial={false}
                  animate={replayActive ? { opacity: [0, 1], y: [window.innerHeight * 0.62, 0] } : { opacity: 1, y: 0 }}
                  transition={replayActive
                    ? { opacity: { duration: 0.9, delay: (messages.length - 1 - messages.indexOf(message)) * 0.12 }, y: { duration: 1.5, delay: (messages.length - 1 - messages.indexOf(message)) * 0.12, ease: [0.22, 1, 0.36, 1] } }
                    : { duration: 0.15 }}
                  style={{ width: message.role === "user" ? "58%" : "78%" }}
                >
                  {(message.content || (sending && thinkingVisible)) && (
                    <motion.p
                      initial={{ clipPath: "inset(0 100% 0 0)", opacity: 0 }}
                      animate={{ clipPath: "inset(0 0% 0 0)", opacity: 1 }}
                      transition={{ duration: 0.65, ease: [0.16, 1, 0.3, 1] }}
                    >{message.content || "Thinking…"}</motion.p>
                  )}
                </motion.article>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {pendingMessage && (
        <div className="chat-flight-anchor" aria-hidden="true">
          <motion.article
            ref={flightRef}
            className="chat-message chat-message-user chat-flight"
            initial={{ opacity: 0, y: 0, width: "100%" }}
            animate={flightControls}
            style={{ marginLeft: "auto" }}
          >
            <p>{pendingMessage.content}</p>
            {drawBorder && (
              <svg className="chat-border-draw" viewBox={`0 0 ${borderSize.width} ${borderSize.height}`} aria-hidden="true">
                <path d={`M 16.5 0.5 H ${borderSize.width - 16.5} Q ${borderSize.width - 0.5} 0.5 ${borderSize.width - 0.5} 16.5 V ${borderSize.height - 5.5} Q ${borderSize.width - 0.5} ${borderSize.height - 0.5} ${borderSize.width - 5.5} ${borderSize.height - 0.5} H 16.5 Q 0.5 ${borderSize.height - 0.5} 0.5 ${borderSize.height - 16.5} V 16.5 Q 0.5 0.5 16.5 0.5 Z`} pathLength="1000" />
              </svg>
            )}
          </motion.article>
        </div>
      )}

      {toolConfirmation && (
        <div className="tool-confirmation-backdrop" role="presentation">
          <section className="tool-confirmation" role="dialog" aria-modal="true" aria-labelledby="tool-confirmation-title">
            <h2 id="tool-confirmation-title">Confirm file or folder change?</h2>
            {toolConfirmation.mode === "delete"
              ? <p>This permanently deletes the target. If it is a folder, all its contents will also be deleted:</p>
              : <p>Jarvis wants to <strong>{toolConfirmation.mode}</strong> in a protected location:</p>}
            <code>{toolConfirmation.path}</code>
            {toolConfirmation.content && <pre className="tool-confirmation-content">{toolConfirmation.content}</pre>}
            <div className="tool-confirmation-actions">
              <button type="button" onClick={() => void answerToolConfirmation(false)} disabled={approvalSending}>Cancel</button>
              <button type="button" onClick={() => void answerToolConfirmation(true)} disabled={approvalSending}>Approve</button>
            </div>
          </section>
        </div>
      )}

      <div className="chat-composer-wrap">
        <motion.form
          className="chat-composer"
          onSubmit={sendMessage}
          initial={{ clipPath: "inset(0 100% 0 0)", opacity: 0.35 }}
          animate={visible
            ? { clipPath: "inset(0 0% 0 0)", opacity: 1 }
            : { clipPath: "inset(0 100% 0 0)", opacity: 0 }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        >
          <motion.textarea
            ref={textareaRef}
            rows={1}
            animate={{ height: inputHeight }}
            transition={{ height: { duration: 0.22, ease: [0.22, 1, 0.36, 1] } }}
            value={input}
            onChange={(event) => resizeTextarea(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Message Jarvis…"
            aria-label="Message Jarvis"
            disabled={sending}
          />
          <button type="submit" disabled={sending || !input.trim()} aria-label="Send message">
            {sending ? "…" : "↑"}
          </button>
        </motion.form>
        {sparksVisible && (
          <div className="chat-sparks" aria-hidden="true">
            {[0, 1, 2, 3].map((spark) => (
              <motion.i
                key={spark}
                initial={{ left: "0%", opacity: 0, scale: 0.3 }}
                animate={{ left: "100%", opacity: [0, 1, 0.8, 0], scale: [0.3, 1.25, 0.7, 0.1] }}
                transition={{ duration: 0.64, delay: spark * 0.075, ease: "easeOut" }}
                style={{ top: `${22 + spark * 16}%` }}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
