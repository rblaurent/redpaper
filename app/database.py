import json
import os
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, create_engine
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

    prompts = relationship("Prompt", back_populates="desktop", cascade="all, delete-orphan")
    wallpapers = relationship("Wallpaper", back_populates="desktop", cascade="all, delete-orphan")


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True)
    desktop_id = Column(Integer, ForeignKey("desktops.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

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

    desktop = relationship("Desktop", back_populates="wallpapers")
    prompt = relationship("Prompt", back_populates="wallpapers")


# Engine + session factory
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
