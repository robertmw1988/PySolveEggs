"""
Caching layer for mission data with pluggable backends.

Provides file-based caching with hash validation for fast startup.
Designed with abstraction to allow future SQLite+Pickle backend.
"""
from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, TypeVar

# Default paths
SOLVER_DIR = Path(__file__).resolve().parent
APP_DATA_DIR = SOLVER_DIR.parent / "app_data"
DEFAULT_CACHE_PATH = APP_DATA_DIR / "mission_cache.json"

T = TypeVar("T")


@dataclass
class CacheMetadata:
    """Metadata about a cached entry."""
    source_hash: str
    timestamp: float
    version: str
    

@dataclass
class CacheEntry:
    """A cached data entry with metadata."""
    metadata: CacheMetadata
    data: Any


class CacheBackend(ABC):
    """Abstract base class for cache backends."""
    
    @abstractmethod
    def get(self, key: str) -> Optional[CacheEntry]:
        """Retrieve a cache entry by key."""
        pass
    
    @abstractmethod
    def set(self, key: str, entry: CacheEntry) -> None:
        """Store a cache entry."""
        pass
    
    @abstractmethod
    def invalidate(self, key: str) -> None:
        """Remove a cache entry."""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all cache entries."""
        pass


class FileCacheBackend(CacheBackend):
    """
    File-based JSON cache backend.
    
    Stores cache as JSON files with hash validation for integrity.
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self._cache_dir = cache_dir or APP_DATA_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        # Sanitize key for filesystem
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return self._cache_dir / f"{safe_key}.cache.json"
    
    def get(self, key: str) -> Optional[CacheEntry]:
        """Retrieve a cache entry from file."""
        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None
        
        try:
            with cache_path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            
            metadata = CacheMetadata(
                source_hash=raw.get("source_hash", ""),
                timestamp=raw.get("timestamp", 0.0),
                version=raw.get("version", ""),
            )
            return CacheEntry(metadata=metadata, data=raw.get("data"))
        except (json.JSONDecodeError, KeyError, OSError):
            # Cache is corrupted, remove it
            self.invalidate(key)
            return None
    
    def set(self, key: str, entry: CacheEntry) -> None:
        """Store a cache entry to file."""
        cache_path = self._get_cache_path(key)
        
        raw = {
            "source_hash": entry.metadata.source_hash,
            "timestamp": entry.metadata.timestamp,
            "version": entry.metadata.version,
            "data": entry.data,
        }
        
        # Write atomically via temp file
        temp_path = cache_path.with_suffix(".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as fh:
                json.dump(raw, fh, indent=2)
            temp_path.replace(cache_path)
        except OSError:
            if temp_path.exists():
                temp_path.unlink()
            raise
    
    def invalidate(self, key: str) -> None:
        """Remove a cache entry file."""
        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            cache_path.unlink()
    
    def clear(self) -> None:
        """Remove all cache files."""
        for cache_file in self._cache_dir.glob("*.cache.json"):
            cache_file.unlink()


class SQLiteCacheBackend(CacheBackend):
    """
    SQLite + Pickle cache backend (placeholder for future implementation).
    
    Will store serialized objects in SQLite blob columns for atomic writes
    and query-able metadata.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or (APP_DATA_DIR / "mission_cache.db")
        # TODO: Initialize SQLite connection
        raise NotImplementedError("SQLite cache backend not yet implemented")
    
    def get(self, key: str) -> Optional[CacheEntry]:
        raise NotImplementedError()
    
    def set(self, key: str, entry: CacheEntry) -> None:
        raise NotImplementedError()
    
    def invalidate(self, key: str) -> None:
        raise NotImplementedError()
    
    def clear(self) -> None:
        raise NotImplementedError()


class MissionDataCache:
    """
    High-level cache for mission data with automatic hash validation.
    
    Usage:
        cache = MissionDataCache()
        
        # Try to get cached data
        data = cache.get_if_valid(source_path)
        if data is None:
            # Cache miss - load fresh data
            data = load_data_from_source(source_path)
            cache.store(source_path, data)
    """
    
    VERSION = "1.0"  # Increment when cache format changes
    
    def __init__(
        self,
        backend: Optional[CacheBackend] = None,
        enabled: bool = True,
    ):
        """
        Initialize the mission data cache.
        
        Parameters
        ----------
        backend : CacheBackend, optional
            Cache backend to use. Defaults to FileCacheBackend.
        enabled : bool
            Whether caching is enabled. If False, always returns cache miss.
        """
        self._backend = backend or FileCacheBackend()
        self._enabled = enabled
    
    @staticmethod
    def compute_hash(file_path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        if not file_path.exists():
            return ""
        
        hasher = hashlib.sha256()
        with file_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def _make_key(self, source_path: Path) -> str:
        """Generate a cache key from source path."""
        return f"mission_data_{source_path.stem}"
    
    def get_if_valid(self, source_path: Path) -> Optional[Any]:
        """
        Get cached data if valid (hash matches and version current).
        
        Parameters
        ----------
        source_path : Path
            Path to the source data file
        
        Returns
        -------
        Any or None
            Cached data if valid, None if cache miss or invalid
        """
        if not self._enabled:
            return None
        
        key = self._make_key(source_path)
        entry = self._backend.get(key)
        
        if entry is None:
            return None
        
        # Validate version
        if entry.metadata.version != self.VERSION:
            self._backend.invalidate(key)
            return None
        
        # Validate source hash
        current_hash = self.compute_hash(source_path)
        if entry.metadata.source_hash != current_hash:
            self._backend.invalidate(key)
            return None
        
        return entry.data
    
    def store(self, source_path: Path, data: Any) -> None:
        """
        Store data in cache with current hash.
        
        Parameters
        ----------
        source_path : Path
            Path to the source data file
        data : Any
            Data to cache (must be JSON-serializable for file backend)
        """
        if not self._enabled:
            return
        
        import time
        
        key = self._make_key(source_path)
        metadata = CacheMetadata(
            source_hash=self.compute_hash(source_path),
            timestamp=time.time(),
            version=self.VERSION,
        )
        entry = CacheEntry(metadata=metadata, data=data)
        self._backend.set(key, entry)
    
    def invalidate(self, source_path: Path) -> None:
        """Manually invalidate cache for a source file."""
        key = self._make_key(source_path)
        self._backend.invalidate(key)
    
    def clear_all(self) -> None:
        """Clear all cached data."""
        self._backend.clear()
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value


# Module-level singleton
_cache: Optional[MissionDataCache] = None


def get_mission_cache(enabled: bool = True) -> MissionDataCache:
    """Get or create the singleton mission data cache."""
    global _cache
    if _cache is None:
        _cache = MissionDataCache(enabled=enabled)
    return _cache


def refresh_data() -> None:
    """
    Manually refresh data by clearing cache.
    
    Call this when user clicks "Refresh Data" in the GUI.
    """
    cache = get_mission_cache()
    cache.clear_all()
