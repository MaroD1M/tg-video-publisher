export interface Video {
  id: number
  filename: string
  filepath: string
  folder: string
  ext: string
  size_bytes: number
  duration_sec: number | null
  width: number | null
  height: number | null
  codec: string | null
  fps: number | null
  bitrate_kbps: number | null
  status: string
  error_msg: string | null
  is_published: boolean
  created_at: string | null
}

export interface Channel {
  chat_id: number
  chat_name: string | null
  chat_type: string
  alias: string | null
  linked_chat_id: number | null
}

export interface CompressJobData {
  id: number
  video_id: number
  video_name: string
  status: string
  progress: number
  preset: string
  target_size_mb: number
  target_width: number
  target_height: number
  thumbnail_layout: string
  thumbnail_id: number | null
  output_path: string | null
  output_size: number | null
  original_size: number | null
  compression_ratio: number | null
  error: string | null
  elapsed_sec: number | null
  eta_sec: number | null
  speed: number | null
  fps: number | null
  step_log: StepLogEntry[] | null
  created_at: string | null
  schedule_id: number
  publish_after: boolean
}

export interface StepLogEntry {
  step: string
  text: string
  elapsed: number
}

export interface PublishTaskData {
  id: number
  video_id: number | null
  video_name: string
  channel_name: string
  channel_id: number | null
  status: string
  progress: number
  elapsed_sec: number | null
  eta_sec: number | null
  thumbnail_id: number | null
  error: string | null
  compression_ratio: number | null
  step_log: StepLogEntry[] | null
  created_at: string | null
  schedule_id: number
}

export interface PublishLogData {
  id: number
  video_id: number | null
  filename: string
  target_chat_id: number | null
  target_chat_name: string
  thumb_message_id: number | null
  video_message_id: number | null
  success: boolean
  error_msg: string | null
  retry_count: number
  published_at: string | null
  thumbnail_id: number | null
  size: number | null
  original_size: number | null
  compression_ratio: number | null
}

export interface Schedule {
  id: number
  name: string
  target_chat_id: number
  cron_expr: string
  enabled: boolean
  queue_strategy: string
  created_at: string | null
  last_run_at: string | null
}

export interface ScheduleItem {
  id: number
  schedule_id: number
  video_id: number
  sort_order: number
  status: string
  video_name: string | null
}

export interface DiskCleanupData {
  output: DiskCategory
  thumbnails: DiskCategory
  tmp: DiskCategorySimple
  bot_cache: DiskCategorySimple
}

interface DiskCategory {
  size: number
  orphans: DiskFile[]
  published: DiskFile[]
  published_size: number
}

interface DiskCategorySimple {
  size: number
  count: number
  files: DiskFile[]
}

interface DiskFile {
  name: string
  path: string
  size: number
}

export interface ProgressJob {
  id: number
  video_name: string
  status: string
  progress: number
  eta_sec: number
  elapsed_sec: number
  speed: number
  fps: number
  error: string
}

export interface ProgressTask {
  id: number
  video_id: number | null
  video_name: string
  channel_name: string
  status: string
  progress: number
  elapsed_sec: number
  eta_sec: number
  thumbnail_id: number | null
  error: string
}

export interface StatsData {
  total_videos: number
  compressed: number
  queued: number
  today_published: number
  bot: boolean
  bot_error: string | null
  api: boolean
  compress_running: number
  compress_queued: number
  last_publish: string | null
}

export interface SettingsData extends Record<string, any> {
  video_source_dirs?: string[]
  bot_token?: string
  api_id?: string
  api_hash?: string
  admin_chat_id?: string
  output_dir?: string
  thumbnail_dir?: string
  compress_preset?: string
  thumbnail_layout?: string
  max_workers?: string
  proxy_enabled?: string
  proxy_type?: string
  proxy_host?: string
  proxy_port?: string
  proxy_user?: string
  proxy_pass?: string
  thumb_caption_template?: string
  video_caption_template?: string
}

export interface NotificationConfigItem {
  id: number
  event_type: string
  enabled: boolean
  template: string
  target_chat_ids: string
}
