# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 mustaf-osman (https://github.com/mustaf-osman)
# Copyright (C) 2026 wentywenty (https://github.com/wentywenty)

"""日志配置模块 — 支持文件日志和控制台日志"""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(
    log_level: str = "INFO",
    log_dir: str = "logs",
    log_file: str = "rp_server.log",
    packet_log_file: str = "packets.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    console: bool = True,
) -> None:
    """配置日志系统

    Args:
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        log_dir: 日志文件目录
        log_file: 主日志文件名
        packet_log_file: 数据包日志文件名
        max_bytes: 单个日志文件最大大小 (字节)
        backup_count: 保留的备份文件数量
        console: 是否输出到控制台
    """
    # 创建日志目录
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 日志格式
    formatter = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 数据包日志格式 (更详细)
    packet_formatter = logging.Formatter(
        "%(asctime)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ===== 主日志器 =====
    root_logger = logging.getLogger("rp_server")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 清除已有的处理器 (避免重复添加)
    root_logger.handlers.clear()

    # 主文件处理器 (轮转日志)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path / log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 控制台处理器
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # ===== 数据包日志器 =====
    packet_logger = logging.getLogger("rp_server.packets")
    packet_logger.setLevel(logging.DEBUG)
    packet_logger.propagate = False  # 不传播到父日志器

    # 数据包文件处理器
    packet_handler = logging.handlers.RotatingFileHandler(
        log_path / packet_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    packet_handler.setFormatter(packet_formatter)
    packet_logger.addHandler(packet_handler)

    root_logger.info(
        "日志系统初始化完成 level=%s dir=%s file=%s packet_file=%s",
        log_level.upper(),
        log_path.absolute(),
        log_file,
        packet_log_file,
    )
