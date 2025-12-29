-- 主要是1 2 4

-- ==============================
-- 1）视频表
-- ==============================
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,     -- 原始视频文件路径
    filename TEXT NOT NULL,        -- 视频文件名
    sha1 TEXT,                     -- 可选：文件哈希
    train_no TEXT,                 -- 车次号（如G4926）
    route_section TEXT,            -- 行驶区间（如"佛山西-宜宾"）
    start_time TEXT,               -- 视频开始时间(ISO格式: 2025-02-14T04:42:12)
    end_time TEXT,                 -- 视频结束时间
    fps REAL,                      -- 视频 FPS
    duration_sec REAL,             -- 视频时长（秒）
    total_frames INTEGER,          -- 视频总帧数
    width INTEGER,                 -- 视频宽度
    height INTEGER,                -- 视频高度
    file_size INTEGER,             -- 文件大小（字节）
    status TEXT DEFAULT 'pending', -- 处理状态: pending/extracting/extracted/error
    extract_version INTEGER DEFAULT 0,  -- 该视频已抽帧第几次版本
    error_msg TEXT,                -- 错误信息
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 建索引（按车次、时间、状态）
CREATE INDEX IF NOT EXISTS idx_videos_train_no ON videos(train_no);
CREATE INDEX IF NOT EXISTS idx_videos_start_time ON videos(start_time);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_route_section ON videos(route_section);


-- ==============================
-- 2）帧表
-- ==============================
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    frame_idx INTEGER NOT NULL,      -- 帧在视频中的序号
    pts_ms INTEGER NOT NULL,         -- 该帧对应时间戳（ms）
    image_path TEXT NOT NULL,        -- 抽出的帧图片路径
    image_filename TEXT,             -- 图片文件名

    -- ===== OCR 提取的结构化字段 =====
    ocr_text TEXT,                   -- OCR抽出的完整文字
    ocr_time TEXT,                   -- OCR识别出的时间戳（ISO格式: 2025-02-14T04:42:12）
    ocr_train_no TEXT,               -- OCR识别出的车次（如G4926）
    ocr_route_section TEXT,          -- OCR识别的区间（如"佛山西-宜宾"）
    ocr_car_no INTEGER,              -- 车厢号
    ocr_pos_no INTEGER,              -- 位置号
    ocr_speed REAL,                  -- 速度（km/h）
    ocr_mileage REAL,                -- 里程（km）
    ocr_confidence REAL,             -- OCR整体置信度

    -- ===== 多标签场景分类结果 =====
    -- 场景分类（晴天、阴天、雨天等）
    label_weather TEXT,              -- 天气标签
    label_weather_score REAL,        -- 天气置信度
    
    -- 位置分类（站台、隧道内、出站、进站等）
    label_location TEXT,             -- 位置标签
    label_location_score REAL,       -- 位置置信度
    
    -- 时段分类（白天、夜晚、黄昏等）
    label_time_period TEXT,          -- 时段标签
    label_time_period_score REAL,    -- 时段置信度
    
    -- 异常检测（正常、异常）
    label_anomaly TEXT,              -- 异常标签
    label_anomaly_score REAL,        -- 异常置信度
    
    -- 综合标签（可以存储多个标签的JSON）
    labels_json TEXT,                -- JSON格式存储所有分类结果

    ai_processed INTEGER DEFAULT 0,  -- AI处理状态: 0未处理, 1已处理
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- 建基础索引
CREATE INDEX IF NOT EXISTS idx_frames_video ON frames(video_id);
CREATE INDEX IF NOT EXISTS idx_frames_pts ON frames(pts_ms);
CREATE INDEX IF NOT EXISTS idx_frames_ocr_time ON frames(ocr_time);
CREATE INDEX IF NOT EXISTS idx_frames_ocr_train_no ON frames(ocr_train_no);
CREATE INDEX IF NOT EXISTS idx_frames_ai_processed ON frames(ai_processed);


-- ==============================
-- 3）OCR 全文检索表（FTS5）
--    已弃用：本项目改为仅基于结构化字段检索，不再使用FTS
-- ==============================
-- 兼容清理历史对象
DROP TABLE IF EXISTS frames_ocr_fts;
DROP TRIGGER IF EXISTS frames_ai_insert;
DROP TRIGGER IF EXISTS frames_ai_delete;
DROP TRIGGER IF EXISTS frames_ai_update;

-- 为常用结构化字段建立索引（提升查询性能）
CREATE INDEX IF NOT EXISTS idx_frames_ocr_car_no ON frames(ocr_car_no);
CREATE INDEX IF NOT EXISTS idx_frames_ocr_pos_no ON frames(ocr_pos_no);
CREATE INDEX IF NOT EXISTS idx_frames_ocr_speed ON frames(ocr_speed);
CREATE INDEX IF NOT EXISTS idx_frames_ocr_mileage ON frames(ocr_mileage);

-- ==============================
-- 4）多标签检索辅助索引
-- ==============================
CREATE INDEX IF NOT EXISTS idx_frames_label_weather ON frames(label_weather);
CREATE INDEX IF NOT EXISTS idx_frames_label_location ON frames(label_location);
CREATE INDEX IF NOT EXISTS idx_frames_label_time_period ON frames(label_time_period);
CREATE INDEX IF NOT EXISTS idx_frames_label_anomaly ON frames(label_anomaly);
CREATE INDEX IF NOT EXISTS idx_frames_ocr_route_section ON frames(ocr_route_section);

-- ==============================
-- 5）视频处理日志表（可选）
-- ==============================
CREATE TABLE IF NOT EXISTS processing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER,
    operation TEXT,                  -- 操作类型: extract_frames/ocr/classify
    status TEXT,                     -- 状态: success/failed
    details TEXT,                    -- 详细信息（JSON格式）
    error_msg TEXT,                  -- 错误信息
    started_at TEXT,
    completed_at TEXT,
    duration_sec REAL,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_logs_video ON processing_logs(video_id);
CREATE INDEX IF NOT EXISTS idx_logs_operation ON processing_logs(operation);
