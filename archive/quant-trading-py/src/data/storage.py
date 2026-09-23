"""
数据存储管理器 - CSV/JSON 持久化存储
"""
import json
import csv
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Any, Optional, Dict, List

import pandas as pd

from config import DATA_DIR, REPORT_DIR


class DataStorage:
    """统一数据存储接口"""

    def __init__(self, base_dir: Path = DATA_DIR):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _subdir(self, name: str) -> Path:
        """获取子目录"""
        d = self.base_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _today(self) -> str:
        return datetime.now().strftime("%Y%m%d")

    def save_json(self, data: Any, filename: str, subdir: str = "") -> Path:
        """保存 JSON 数据"""
        directory = self._subdir(subdir) if subdir else self.base_dir
        filepath = directory / filename
        self._atomic_write_text(
            filepath,
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
        )
        return filepath

    def load_json(self, filename: str, subdir: str = "") -> Optional[Any]:
        """加载 JSON 数据"""
        directory = self._subdir(subdir) if subdir else self.base_dir
        filepath = directory / filename
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_csv(self, df: pd.DataFrame, filename: str, subdir: str = "") -> Path:
        """保存 DataFrame 为 CSV"""
        directory = self._subdir(subdir) if subdir else self.base_dir
        filepath = directory / filename
        fd, temp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
                df.to_csv(handle, index=False)
            os.replace(temp_name, filepath)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return filepath

    def load_csv(self, filename: str, subdir: str = "") -> Optional[pd.DataFrame]:
        """加载 CSV 为 DataFrame"""
        directory = self._subdir(subdir) if subdir else self.base_dir
        filepath = directory / filename
        if not filepath.exists():
            return None
        return pd.read_csv(filepath, encoding="utf-8-sig")

    def save_daily(self, data: Any, name: str) -> Path:
        """按日期保存数据"""
        today = self._today()
        directory = self._subdir(f"daily/{today}")
        filepath = directory / f"{name}.json"
        self._atomic_write_text(
            filepath,
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
        )
        return filepath

    def load_latest(self, name: str, subdir: str = "") -> Optional[Any]:
        """加载最新日期的数据"""
        directory = self._subdir(subdir) if subdir else self.base_dir
        daily_dir = directory / "daily"
        if not daily_dir.exists():
            return None
        dates = sorted([d.name for d in daily_dir.iterdir() if d.is_dir()], reverse=True)
        for date in dates:
            filepath = daily_dir / date / f"{name}.json"
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
        return None

    def list_files(self, subdir: str = "", pattern: str = "*") -> List[Path]:
        """列出文件"""
        directory = self._subdir(subdir) if subdir else self.base_dir
        return list(directory.glob(pattern))

    def save_snapshot_json(self, data: Any, filename: str, subdir: str = "") -> Path:
        """Save current JSON plus an immutable timestamped daily snapshot."""
        current_path = self.save_json(data, filename, subdir)
        snapshot_dir = self.base_dir / "snapshots" / subdir / self._today()
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%H%M%S%f")
        snapshot_path = snapshot_dir / f"{filename}.{timestamp}.json"
        self._atomic_write_text(
            snapshot_path,
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
        )
        return current_path

    def write_text_atomic(self, content: str, filename: str, subdir: str = "") -> Path:
        """Write report text without exposing partial files on failure."""
        directory = self._subdir(subdir) if subdir else self.base_dir
        filepath = directory / filename
        self._atomic_write_text(filepath, content)
        return filepath

    def _atomic_write_text(self, filepath: Path, content: str) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{filepath.name}.", suffix=".tmp", dir=filepath.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
            os.replace(temp_name, filepath)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
