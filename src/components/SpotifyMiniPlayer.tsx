import { useEffect, useState } from "react";

const API_URL = "http://127.0.0.1:8008";
type SpotifyStatus = { open: boolean; track: string; playing: boolean | null; image: string | null };

export default function SpotifyMiniPlayer() {
  const [status, setStatus] = useState<SpotifyStatus | null>(null);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      const response = await fetch(`${API_URL}/spotify/status`);
      if (response.ok) setStatus(await response.json() as SpotifyStatus);
    } catch { /* the local backend may still be starting */ }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, []);

  async function command(action: string) {
    setError("");
    try {
      const response = await fetch(`${API_URL}/spotify/control`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const result = await response.json() as { message?: string };
      if (!response.ok) throw new Error(result.message ?? "Spotify control failed.");
      if (result.message?.startsWith("Couldn't") || result.message?.startsWith("Could not") || result.message?.includes("couldn't")) {
        setError(result.message);
      }
      window.setTimeout(() => void refresh(), 500);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Spotify control failed.");
    }
  }

  if (!status?.open) return null;
  return (
    <aside className="spotify-mini-player" aria-label="Spotify controls">
      {status.image ? <img className="spotify-mini-art" src={status.image} alt="Album artwork" /> :
        <div className="spotify-mini-art spotify-mini-art-empty" aria-label="Album artwork unavailable"><span>♫</span></div>}
      <div className="spotify-mini-track" title={status.track}>{status.track || "Spotify is open"}</div>
      <div className="spotify-mini-controls">
        <button type="button" aria-label="Previous track" title="Previous" onClick={() => void command("previous")}>⏮</button>
        <button type="button" aria-label="Play or pause" title="Play / pause" onClick={() => void command("toggle")}>⏯</button>
        <button type="button" aria-label="Next track" title="Next" onClick={() => void command("next")}>⏭</button>
      </div>
      {error && <span className="spotify-mini-error" role="status">{error}</span>}
    </aside>
  );
}
