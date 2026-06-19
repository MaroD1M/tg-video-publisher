import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean, DateTime, Text,
    ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class VideoStatus(str, enum.Enum):
    pending = "pending"
    compressing = "compressing"
    compressed = "compressed"
    skipped = "skipped"
    failed = "failed"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"
    paused = "paused"


class CompressPreset(str, enum.Enum):
    fast = "fast"
    balanced = "balanced"
    high_quality = "high_quality"


class ItemStatus(str, enum.Enum):
    queued = "queued"
    publishing_thumb = "publishing_thumb"
    publishing_video = "publishing_video"
    published = "published"
    failed = "failed"
    skipped = "skipped"


class QueueStrategy(str, enum.Enum):
    sequential = "sequential"
    random = "random"
    rotate = "rotate"


class PublishTaskStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    uploading = "uploading"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(512), nullable=False)
    filepath = Column(String(1024), nullable=False, unique=True)
    ext = Column(String(16))
    size_bytes = Column(BigInteger, default=0)
    duration_sec = Column(Float, default=0)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    codec = Column(String(64))
    fps = Column(Float, default=0)
    bitrate_kbps = Column(Integer, default=0)
    file_hash = Column(String(64))
    status = Column(SAEnum(VideoStatus), default=VideoStatus.pending)
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    compress_jobs = relationship("CompressJob", back_populates="video", cascade="all, delete-orphan")
    thumbnails = relationship("Thumbnail", back_populates="video", cascade="all, delete-orphan")


class CompressJob(Base):
    __tablename__ = "compress_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)
    preset = Column(SAEnum(CompressPreset), default=CompressPreset.balanced)
    target_size_mb = Column(Integer, default=1000)
    target_width = Column(Integer, default=0)
    target_height = Column(Integer, default=0)
    schedule_id = Column(Integer, default=0)
    publish_after = Column(Boolean, default=False)
    publish_channel_id = Column(BigInteger, default=0)
    output_filename = Column(String(512))
    output_path = Column(String(1024))
    output_size_bytes = Column(BigInteger, default=0)
    compression_ratio = Column(Float, default=0)
    progress = Column(Float, default=0)
    status = Column(SAEnum(JobStatus), default=JobStatus.queued)
    error_log = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    video = relationship("Video", back_populates="compress_jobs")


class Thumbnail(Base):
    __tablename__ = "thumbnails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)
    layout = Column(String(8), default="3x3")
    filepath = Column(String(1024))
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    size_bytes = Column(Integer, default=0)
    has_timestamp = Column(Boolean, default=True)
    has_watermark = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    video = relationship("Video", back_populates="thumbnails")


class TargetChat(Base):
    __tablename__ = "target_chats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False, unique=True)
    chat_name = Column(String(256))
    chat_type = Column(String(32))
    linked_chat_id = Column(BigInteger, nullable=True)
    is_active = Column(Boolean, default=True)
    verified_at = Column(DateTime, nullable=True)


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    target_chat_id = Column(BigInteger, nullable=False)
    cron_expr = Column(String(128), nullable=False)
    queue_strategy = Column(SAEnum(QueueStrategy), default=QueueStrategy.sequential)
    thumb_caption_template = Column(Text, default="")
    video_caption_template = Column(Text, default="")
    enabled = Column(Boolean, default=True)
    next_run_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    items = relationship("ScheduleItem", back_populates="schedule", cascade="all, delete-orphan", order_by="ScheduleItem.sort_order")


class ScheduleItem(Base):
    __tablename__ = "schedule_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)
    sort_order = Column(Integer, default=0)
    status = Column(SAEnum(ItemStatus), default=ItemStatus.queued)
    scheduled_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    error_msg = Column(Text, nullable=True)

    schedule = relationship("Schedule", back_populates="items")
    video = relationship("Video")


class PublishLog(Base):
    __tablename__ = "publish_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_item_id = Column(Integer, ForeignKey("schedule_items.id", ondelete="SET NULL"), nullable=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    target_chat_id = Column(BigInteger, nullable=False)
    thumb_message_id = Column(Integer, nullable=True)
    video_message_id = Column(Integer, nullable=True)
    success = Column(Boolean, default=False)
    error_msg = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    published_at = Column(DateTime, default=datetime.datetime.utcnow)


class PublishTask(Base):
    __tablename__ = "publish_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    channel_id = Column(BigInteger, nullable=True)
    channel_name = Column(String(256))
    status = Column(SAEnum(PublishTaskStatus), default=PublishTaskStatus.queued)
    progress = Column(Float, default=0)
    elapsed_sec = Column(Float, default=0)
    eta_sec = Column(Float, default=0)
    thumb_message_id = Column(Integer, nullable=True)
    video_message_id = Column(Integer, nullable=True)
    error_log = Column(Text)
    sort_order = Column(Integer, default=0)
    is_paused = Column(Boolean, default=False)
    step_log = Column(Text)  # JSON: [{step, elapsed, result}]
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(128), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class NotificationConfig(Base):
    __tablename__ = "notification_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False)  # compress_done / compress_fail / publish_done / publish_fail / bot_status
    enabled = Column(Boolean, default=True)
    template = Column(Text, default="")
    target_chat_ids = Column(Text, default="")  # comma-separated chat IDs


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(128), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
