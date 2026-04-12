import json
import os
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint,
    create_engine, text
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "redpaper.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"


class Base(DeclarativeBase):
    pass


class Desktop(Base):
    __tablename__ = "desktops"

    id = Column(Integer, primary_key=True)
    guid = Column(String(36), unique=True, nullable=False)
    name = Column(String(128), nullable=False, default="Desktop")
    display_order = Column(Integer, nullable=False, default=0)
    theme = Column(String(256), nullable=True)
    theme_style = Column(String(256), nullable=True)
    workspace_path = Column(String(512), nullable=True)

    wallpaper_mode = Column(String(16), nullable=False, default="repeated")  # "repeated" | "original"

    prompts = relationship("Prompt", back_populates="desktop", cascade="all, delete-orphan")
    wallpapers = relationship("Wallpaper", back_populates="desktop", cascade="all, delete-orphan")
    monitor_configs = relationship("MonitorConfig", back_populates="desktop", cascade="all, delete-orphan")


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True)
    desktop_id = Column(Integer, ForeignKey("desktops.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    is_ai_generated = Column(Boolean, default=False, nullable=False)

    desktop = relationship("Desktop", back_populates="prompts")
    wallpapers = relationship("Wallpaper", back_populates="prompt")


class Wallpaper(Base):
    __tablename__ = "wallpapers"

    id = Column(Integer, primary_key=True)
    desktop_id = Column(Integer, ForeignKey("desktops.id"), nullable=False)
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=True)
    file_path = Column(String(512), nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=False)
    monitor_index = Column(Integer, nullable=True)        # NULL = legacy/repeated
    monitor_device_path = Column(String(256), nullable=True)  # NULL = legacy/repeated

    desktop = relationship("Desktop", back_populates="wallpapers")
    prompt = relationship("Prompt", back_populates="wallpapers")


class MonitorConfig(Base):
    __tablename__ = "monitor_configs"

    id = Column(Integer, primary_key=True)
    desktop_id = Column(Integer, ForeignKey("desktops.id"), nullable=False)
    monitor_device_path = Column(String(256), nullable=False)  # e.g. "\\.\DISPLAY1\Monitor0"
    monitor_index = Column(Integer, nullable=False)             # 0-based, informational
    disabled = Column(Boolean, nullable=False, default=False)   # legacy, superseded by mode
    mode = Column(String(16), nullable=False, default="shared") # "off" | "individual" | "shared"

    desktop = relationship("Desktop", back_populates="monitor_configs")

    __table_args__ = (
        UniqueConstraint("desktop_id", "monitor_device_path", name="uq_monitor_config_desktop_monitor"),
    )


# Engine + session factory
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrations: add columns that didn't exist in older schemas
        for sql in [
            "ALTER TABLE desktops ADD COLUMN theme TEXT",
            "ALTER TABLE desktops ADD COLUMN theme_style TEXT",
            "ALTER TABLE desktops ADD COLUMN workspace_path TEXT",
            "ALTER TABLE prompts ADD COLUMN is_ai_generated INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE desktops ADD COLUMN wallpaper_mode TEXT NOT NULL DEFAULT 'repeated'",
            "ALTER TABLE wallpapers ADD COLUMN monitor_index INTEGER",
            "ALTER TABLE wallpapers ADD COLUMN monitor_device_path TEXT",
            """CREATE TABLE IF NOT EXISTS monitor_configs (
                id INTEGER PRIMARY KEY,
                desktop_id INTEGER NOT NULL REFERENCES desktops(id),
                monitor_device_path TEXT NOT NULL,
                monitor_index INTEGER NOT NULL,
                disabled INTEGER NOT NULL DEFAULT 0,
                mode TEXT NOT NULL DEFAULT 'shared',
                UNIQUE(desktop_id, monitor_device_path)
            )""",
            "ALTER TABLE monitor_configs ADD COLUMN mode TEXT NOT NULL DEFAULT 'shared'",
        ]:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # column already exists


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
