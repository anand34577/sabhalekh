export type Status = "new" | "queued" | "processing" | "done" | "error" | "cancelled" | "recording";

export interface Session {
  id: number;
  title: string;
  source_type: "recorded" | "imported";
  original_filename: string | null;
  audio_path: string | null;
  mic_track_path: string | null;
  system_track_path: string | null;
  duration_sec: number;
  created_at: number;
  updated_at: number;
  status: Status;
  stage: string | null;
  progress: number;
  language_mode: string;
  script_mode: string;
  detected_languages: string[];
  asr_model: string | null;
  diarization_engine: string | null;
  profile_used: string | null;
  tags: string[];
  error_message: string | null;
  warnings: string[];
}

export interface Speaker {
  id: number;
  session_id: number;
  label: string;
  display_name: string;
  color: string;
  is_self: number;
}

export interface Word {
  start: number;
  end: number;
  text: string;
  confidence: number | null;
}

export interface Segment {
  id: number;
  session_id: number;
  speaker_id: number | null;
  original_speaker_id: number | null;
  start_sec: number;
  end_sec: number;
  text: string;
  edited_text: string | null;
  display_text: string;
  language: string | null;
  confidence: number | null;
  overlap_flag: number;
  words: Word[];
}

export interface TalkTime {
  speaker_id: number;
  name: string;
  color: string;
  seconds: number;
  percent: number;
}

export interface SessionDetail {
  session: Session;
  speakers: Speaker[];
  segments: Segment[];
  talk_time: TalkTime[];
  has_audio: boolean;
}

export interface Job {
  id: number;
  session_id: number;
  title: string;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  stage: string | null;
  progress: number;
  eta_sec: number | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
  params: Record<string, unknown>;
}

export interface Profile {
  name: string;
  label: string;
  device: string;
  accel: "gpu" | "igpu" | "cpu";
  compute_type: string;
  batch_size: number;
  threads: number;
}

export interface AccelDevice {
  name: string;
  description: string;
  kind: string;
  type: "gpu" | "igpu";
  memory_mb: number;
  memory_free_mb: number;
}

export interface HardwareStatus {
  badge: string;
  profile: Profile;
  warnings: string[];
  info: {
    cuda_available: boolean;
    gpu_name: string | null;
    vram_mb: number | null;
    cpu_name: string | null;
    cpu_cores: number;
    cpu_threads: number;
    ram_mb: number;
    free_disk_mb: number;
    cuda_error: string | null;
    accel_devices: AccelDevice[];
    accel_error: string | null;
  };
}

export interface ModelInfo {
  id: string;
  kind: "asr" | "diarization";
  label: string;
  notes: string;
  translate: boolean;
  available: boolean;
  problem: string | null;
  source: string;
}

export interface Settings {
  theme: "system" | "dark" | "light";
  accent: string;
  text_scale: number;
  language_mode: "auto" | "en" | "hi" | "translate";
  script_mode: "as_spoken" | "devanagari" | "roman";
  asr_model: string;
  profile_override: string;
  auto_process: boolean;
  initial_prompt: string;
  min_speakers: number | null;
  max_speakers: number | null;
  mic_device: number | null;
  loopback_device: number | null;
  playback_kbps: number;
  hotkey: string;
  start_with_windows: boolean;
  minimize_to_tray: boolean;
  consent_acknowledged: boolean;
  onboarding_done: boolean;
  auto_delete_audio_days: number;
  export_timestamps: boolean;
  export_speakers: boolean;
  export_merge: boolean;
}

export interface SearchHit {
  session_id: number;
  segment_id: number | null;
  field: "title" | "speaker" | "text" | "roman";
  title: string;
  created_at: number;
  start_sec: number | null;
  speaker_id: number | null;
  snippet: string;
}

export interface Levels {
  rms: number;
  peak: number;
  bands: number[];
}

export interface RecordingStatus {
  active: boolean;
  id?: string;
  title?: string;
  paused?: boolean;
  elapsed?: number;
  devices?: Record<string, string | null>;
}

export interface Device {
  index: number;
  name: string;
  channels: number;
  rate: number;
  default: boolean;
}

export interface Recoverable {
  id: string;
  title: string;
  started_at: number;
  duration: number;
}

export interface Peaks {
  rate: number;
  duration: number;
  peaks: number[];
}

export type BackendEvent = { type: string; ts: number; [k: string]: unknown };
