/**
 * Aufnahme im Browser (MediaRecorder) und Umwandlung in WAV, 16 kHz mono.
 *
 * Warum WAV: Chrome nimmt WebM/Opus auf, Safari MP4/AAC – OpenRouter-Anbieter verstehen aber nicht jedes Format.
 * WAV versteht jedes Audiomodell, und 16 kHz mono reicht für Sprache (≈ 32 KB je Sekunde).
 */

export class MicError extends Error {
  constructor(public code: "denied" | "no_device" | "insecure" | "unsupported" | "failed", message: string) {
    super(message);
  }
}

export const MAX_SECONDS = 90;
const TARGET_RATE = 16000;

export class Recorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private ctx: AudioContext | null = null;
  private raf = 0;

  /** ``onLevel`` bekommt laufend die Lautstärke 0…1 für die Anzeige. */
  async start(onLevel?: (level: number) => void): Promise<void> {
    if (!window.isSecureContext) throw new MicError("insecure", "Das Mikrofon funktioniert nur über HTTPS.");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined")
      throw new MicError("unsupported", "Dieser Browser kann keine Sprache aufnehmen.");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (err) {
      const name = (err as DOMException)?.name;
      if (name === "NotAllowedError" || name === "SecurityError")
        throw new MicError("denied", "Kein Mikrofonzugriff. Bitte das Mikrofon für diese Seite im Browser erlauben.");
      if (name === "NotFoundError" || name === "OverconstrainedError")
        throw new MicError("no_device", "Kein Mikrofon gefunden.");
      throw new MicError("failed", "Das Mikrofon konnte nicht gestartet werden.");
    }
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.recorder.start(250);
    if (onLevel) this.meter(onLevel);
  }

  private meter(onLevel: (level: number) => void): void {
    try {
      this.ctx = new AudioContext();
      const analyser = this.ctx.createAnalyser();
      analyser.fftSize = 512;
      this.ctx.createMediaStreamSource(this.stream!).connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let peak = 0;
        for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
        onLevel(Math.min(1, peak / 64));
        this.raf = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      /* Anzeige ist nur Zierde */
    }
  }

  /** Beendet die Aufnahme und liefert WAV. Das Mikrofon wird sofort freigegeben. */
  async stop(): Promise<Blob> {
    const recorder = this.recorder;
    if (!recorder) throw new MicError("failed", "Es läuft keine Aufnahme.");
    const done = new Promise<void>((resolve) => (recorder.onstop = () => resolve()));
    if (recorder.state !== "inactive") recorder.stop();
    await done;
    const type = recorder.mimeType || "audio/webm";
    this.release();
    return toWav(new Blob(this.chunks, { type }));
  }

  cancel(): void {
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    this.release();
  }

  private release(): void {
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach((track) => track.stop());
    this.ctx?.close().catch(() => undefined);
    this.stream = null;
    this.recorder = null;
    this.ctx = null;
  }
}

async function toWav(blob: Blob): Promise<Blob> {
  const data = await blob.arrayBuffer();
  const ctx = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await ctx.decodeAudioData(data);
  } catch {
    throw new MicError("failed", "Die Aufnahme konnte nicht gelesen werden.");
  } finally {
    ctx.close().catch(() => undefined);
  }
  const length = Math.max(1, Math.ceil(decoded.duration * TARGET_RATE));
  const offline = new OfflineAudioContext(1, length, TARGET_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();
  return encodeWav(rendered.getChannelData(0), TARGET_RATE);
}

export function encodeWav(samples: Float32Array, rate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, s: string) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
