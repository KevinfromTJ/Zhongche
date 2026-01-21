"""
视频数据管理模块
用于管理视频、帧提取、OCR和分类结果
"""
import sqlite3
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Set
import os
import sys
import time
import threading
import atexit
from contextlib import contextmanager

# 添加父目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import VIDEO_DATABASE_PATH, VIDEO_DB_INIT_SQL_PATH

# 视频数据库路径



class VideoDatabase:
    """视频数据库管理类（线程安全，带重试机制）"""
    
    def __init__(self, db_path: str = VIDEO_DATABASE_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self.timeout = 30.0  # 数据库锁超时时间（秒）
        self.max_retries = 3  # 最大重试次数
        self._atexit_registered = False
        self._register_atexit()
        self.init_db()
    
    def _register_atexit(self):
        if getattr(self, '_atexit_registered', False):
            return
        try:
            atexit.register(self.close_conn)
        finally:
            self._atexit_registered = True
    
    def get_conn(self):
        """
        获取线程安全的数据库连接
        使用WAL模式提高并发性能
        """
        # 已有连接时做健康检查，避免“已关闭但仍被缓存”的情形
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            try:
                # 轻量健康检查；若连接已关闭会抛出 ProgrammingError
                self._local.conn.execute('SELECT 1')
                return self._local.conn
            except (sqlite3.ProgrammingError,):
                # 连接对象已失效，清空以便重建
                self._local.conn = None
            except sqlite3.OperationalError as e:
                # 某些平台会以 OperationalError 暴露“连接已关闭/不可用”
                if 'closed' in str(e).lower():
                    self._local.conn = None
                else:
                    # 其他运行时问题（例如 locked）交由上层重试机制处理
                    return self._local.conn
        
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            try:
                conn = sqlite3.connect(self.db_path, timeout=self.timeout, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                
                # 使用回滚日志（DELETE），在当前环境下与FTS5触发器更稳定
                conn.execute('PRAGMA journal_mode=DELETE')
                
                # 设置同步模式为NORMAL（平衡性能和安全性）
                conn.execute('PRAGMA synchronous=NORMAL')
                
                # 强制外键约束，避免孤儿记录
                conn.execute('PRAGMA foreign_keys=ON')
                
                # 增加缓存大小（默认2000页，改为10000页，约40MB）
                conn.execute('PRAGMA cache_size=-10000')
                
                # 设置繁忙超时
                conn.execute(f'PRAGMA busy_timeout={int(self.timeout * 1000)}')
                
                self._local.conn = conn
            except sqlite3.DatabaseError as e:
                print(f"❌ 数据库连接错误: {e}")
                print(f"   尝试修复数据库...")
                self._repair_database()
                # 重新连接
                conn = sqlite3.connect(self.db_path, timeout=self.timeout, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute('PRAGMA journal_mode=DELETE')
                conn.execute('PRAGMA synchronous=NORMAL')
                conn.execute('PRAGMA foreign_keys=ON')
                conn.execute('PRAGMA cache_size=-10000')
                conn.execute(f'PRAGMA busy_timeout={int(self.timeout * 1000)}')
                self._local.conn = conn
                
        return self._local.conn
    
    def close_conn(self):
        """关闭当前线程的数据库连接"""
        if hasattr(self._local, 'conn') and self._local.conn:
            try:
                self._local.conn.close()
            except:
                pass
            self._local.conn = None
    
    @contextmanager
    def transaction(self):
        """
        事务上下文管理器
        自动处理提交和回滚
        """
        conn = self.get_conn()
        try:
            conn.execute('BEGIN')
            yield conn
            conn.execute('COMMIT')
        except Exception as e:
            conn.execute('ROLLBACK')
            raise e
    
    def execute_with_retry(self, func, *args, **kwargs):
        """
        带重试机制的数据库操作
        
        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数
            
        Returns:
            函数返回值
        """
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
                last_error = e
                error_msg = str(e).lower()
                
                # 数据库被锁定
                if 'locked' in error_msg:
                    wait_time = 0.1 * (2 ** attempt)  # 指数退避
                    print(f"⚠️  数据库被锁定，{wait_time:.1f}秒后重试 (尝试 {attempt + 1}/{self.max_retries})")
                    time.sleep(wait_time)
                    self.close_conn()  # 关闭连接重试
                    continue
                
                # 数据库损坏
                elif 'malformed' in error_msg or 'corrupt' in error_msg:
                    print(f"❌ 数据库文件损坏，尝试修复...")
                    self._repair_database()
                    if attempt < self.max_retries - 1:
                        time.sleep(0.5)
                        self.close_conn()
                        continue
                
                # 其他错误
                else:
                    raise e
        
        # 所有重试都失败
        raise last_error
    
    def _repair_database(self):
        """
        尝试修复损坏的数据库
        """
        backup_path = f"{self.db_path}.backup_{int(time.time())}"
        wal_path = f"{self.db_path}-wal"
        shm_path = f"{self.db_path}-shm"
        
        def _cleanup_wal_shm():
            try:
                if os.path.exists(wal_path):
                    os.remove(wal_path)
                    print(f"   清理WAL: {wal_path}")
            except Exception as _e:
                print(f"   清理WAL失败: {wal_path}, {_e}")
            try:
                if os.path.exists(shm_path):
                    os.remove(shm_path)
                    print(f"   清理SHM: {shm_path}")
            except Exception as _e:
                print(f"   清理SHM失败: {shm_path}, {_e}")
        
        try:
            # 关闭当前连接，避免修复过程中文件被占用
            self.close_conn()
            
            # 1. 备份原数据库
            if os.path.exists(self.db_path):
                import shutil
                shutil.copy2(self.db_path, backup_path)
                print(f"   备份创建: {backup_path}")
            
            # 1.1 清理可能残留的 WAL/SHM，避免旧增量日志污染新库
            _cleanup_wal_shm()
            
            # 2. 纯Python方式：导出+重建（优先，不依赖系统命令）
            try:
                sql_dump = f"{self.db_path}.sql"
                # 导出
                with sqlite3.connect(self.db_path) as src_conn:
                    src_conn.text_factory = str
                    with open(sql_dump, 'w', encoding='utf-8') as f:
                        for line in src_conn.iterdump():
                            f.write('%s\n' % line)
                # 删除旧库
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)
                # 重建
                with sqlite3.connect(self.db_path) as dst_conn:
                    with open(sql_dump, 'r', encoding='utf-8') as f:
                        dst_conn.executescript(f.read())
                os.remove(sql_dump)
                # 清理边车并设置基础PRAGMA
                _cleanup_wal_shm()
                try:
                    conn = sqlite3.connect(self.db_path, timeout=self.timeout, check_same_thread=False)
                    conn.execute('PRAGMA journal_mode=DELETE')
                    conn.execute('PRAGMA foreign_keys=ON')
                    conn.close()
                except Exception:
                    pass
                print(f"✅ 数据库已修复")
                return True
            except Exception:
                # 继续走下一步重建
                pass
            
            # 3. Python方式：重建数据库（丢失数据，但保证结构完整）
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            
            # 重新初始化
            self.close_conn()
            self.init_db()
            _cleanup_wal_shm()
            try:
                conn = sqlite3.connect(self.db_path, timeout=self.timeout, check_same_thread=False)
                conn.execute('PRAGMA journal_mode=DELETE')
                conn.execute('PRAGMA foreign_keys=ON')
                conn.close()
            except Exception as _:
                pass
            
            print(f"⚠️  数据库已重建（数据可能丢失）")
            print(f"   如需恢复，请使用备份: {backup_path}")
            
            return True
            
        except Exception as e:
            print(f"❌ 数据库修复失败: {e}")
            if os.path.exists(backup_path):
                print(f"   备份文件可用: {backup_path}")
            return False
    
    def init_db(self):
        """初始化数据库表"""
        conn = self.get_conn()
        cursor = conn.cursor()
        
        # 读取并执行 SQL 文件
        # sql_file = os.path.join(
        #     # os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        #     # 'Plan', 'videodatamanage.sql'
        #     '/data/chenjuntao/OtherProj/dataManage/Plan/videodatamanage.sql'
        # )
        sql_file = VIDEO_DB_INIT_SQL_PATH
        
        if os.path.exists(sql_file):
            with open(sql_file, 'r', encoding='utf-8') as f:
                sql_script = f.read()
                # 执行整个脚本
                cursor.executescript(sql_script)
                print(f"✅ 视频数据库初始化完成: {self.db_path}")
        else:
            print(f"⚠️  SQL文件不存在: {sql_file}")
        
        conn.commit()
        # 迁移：补充新列（若缺失）
        self._apply_migrations()
        self.close_conn()
    
    def _apply_migrations(self):
        """按需添加新列（幂等）"""
        conn = self.get_conn()
        cursor = conn.cursor()
        try:
            # videos 表新增：v_stream_index, v_time_base_num, v_time_base_den
            cursor.execute("PRAGMA table_info(videos)")
            cols = [row["name"] for row in cursor.fetchall()]
            if "v_stream_index" not in cols:
                try:
                    cursor.execute("ALTER TABLE videos ADD COLUMN v_stream_index INTEGER")
                except Exception:
                    pass
            if "v_time_base_num" not in cols:
                try:
                    cursor.execute("ALTER TABLE videos ADD COLUMN v_time_base_num INTEGER")
                except Exception:
                    pass
            if "v_time_base_den" not in cols:
                try:
                    cursor.execute("ALTER TABLE videos ADD COLUMN v_time_base_den INTEGER")
                except Exception:
                    pass

            # frames 表新增：frame_pts
            cursor.execute("PRAGMA table_info(frames)")
            fcols = [row["name"] for row in cursor.fetchall()]
            if "frame_pts" not in fcols:
                try:
                    cursor.execute("ALTER TABLE frames ADD COLUMN frame_pts INTEGER")
                except Exception:
                    pass

            # 数据修复（幂等）：
            # 历史版本在 ffmpeg 抽帧时会先落到 output_dir/.tmp_ffmpeg，
            # 但入库时把 image_path 写成了临时目录路径，随后临时目录会被迁移/删除，
            # 导致数据库留存的 image_path 指向不存在的位置。
            try:
                cursor.execute(
                    "UPDATE frames "
                    "SET image_path = REPLACE(image_path, '/.tmp_ffmpeg', '') "
                    "WHERE image_path LIKE '%/.tmp_ffmpeg/%'"
                )
                try:
                    fixed_cnt = int(cursor.rowcount or 0)
                except Exception:
                    fixed_cnt = 0
                if fixed_cnt > 0:
                    print(f"🛠️ 已修复历史 frames.image_path 临时目录路径: {fixed_cnt} 条")
            except Exception:
                # 不中断迁移流程
                pass

            conn.commit()
            print("✅ 数据库迁移检查完成")
        except Exception as e:
            print(f"⚠️  数据库迁移检查失败: {e}")
        finally:
            self.close_conn()
    
    # ==================== 视频操作 ====================
    
    def add_video(self, path: str, filename: str = None, **kwargs) -> int:
        """
        添加视频记录（带重试机制）
        
        Args:
            path: 视频文件路径
            filename: 视频文件名
            **kwargs: 其他字段（train_no, route_section, start_time等）
        
        Returns:
            video_id: 视频ID
        """
        def _add():
            conn = self.get_conn()
            cursor = conn.cursor()
            
            if filename is None:
                filename_val = os.path.basename(path)
            else:
                filename_val = filename
            
            # 计算文件SHA1（如果文件存在）
            sha1 = None
            if os.path.exists(path):
                sha1 = self._calculate_sha1(path)
            
            # 检查是否已存在
            cursor.execute('SELECT id FROM videos WHERE path = ?', (path,))
            existing = cursor.fetchone()
            if existing:
                return existing['id']
            
            # 插入视频记录
            fields = ['path', 'filename', 'sha1']
            values = [path, filename_val, sha1]
            
            # 添加其他字段
            allowed_fields = [
                'train_no', 'route_section', 'start_time', 'end_time', 
                'fps', 'duration_sec', 'total_frames', 'width', 'height', 
                'file_size', 'status',
                'v_stream_index', 'v_time_base_num', 'v_time_base_den'
            ]
            for field in allowed_fields:
                if field in kwargs:
                    fields.append(field)
                    values.append(kwargs[field])
            
            placeholders = ','.join(['?'] * len(values))
            field_names = ','.join(fields)
            
            cursor.execute(
                f'INSERT INTO videos ({field_names}) VALUES ({placeholders})',
                values
            )
            video_id = cursor.lastrowid
            conn.commit()
            print(f"✅ 添加视频: {filename_val} (ID: {video_id})")
            return video_id
        
        return self.execute_with_retry(_add)
    
    def get_video(self, video_id: int) -> Optional[Dict]:
        """获取视频信息"""
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM videos WHERE id = ?', (video_id,))
        row = cursor.fetchone()
        self.close_conn()
        return dict(row) if row else None
    
    def get_video_by_path(self, path: str) -> Optional[Dict]:
        """根据路径获取视频"""
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM videos WHERE path = ?', (path,))
        row = cursor.fetchone()
        self.close_conn()
        return dict(row) if row else None
    
    def update_video(self, video_id: int, **kwargs):
        """更新视频信息"""
        conn = self.get_conn()
        cursor = conn.cursor()
        
        fields = []
        values = []
        for key, value in kwargs.items():
            fields.append(f'{key} = ?')
            values.append(value)
        
        if fields:
            fields.append('updated_at = ?')
            values.append(datetime.now().isoformat())
            values.append(video_id)
            
            sql = f"UPDATE videos SET {','.join(fields)} WHERE id = ?"
            cursor.execute(sql, values)
            conn.commit()
        
        self.close_conn()
    
    def list_videos(self, status: str = None, train_no: str = None, 
                   limit: int = None, offset: int = 0) -> List[Dict]:
        """
        列出视频
        
        Args:
            status: 过滤状态
            train_no: 过滤车次号
            limit: 返回数量限制
            offset: 偏移量
        """
        conn = self.get_conn()
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if status:
            conditions.append('status = ?')
            params.append(status)
        
        if train_no:
            conditions.append('train_no = ?')
            params.append(train_no)
        
        where_clause = ' AND '.join(conditions) if conditions else '1=1'
        sql = f'SELECT * FROM videos WHERE {where_clause} ORDER BY created_at DESC'
        
        if limit:
            sql += f' LIMIT {limit} OFFSET {offset}'
        
        cursor.execute(sql, params)
        videos = [dict(row) for row in cursor.fetchall()]
        self.close_conn()
        return videos
    
    def delete_video(self, video_id: int):
        """删除视频及其所有帧"""
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM videos WHERE id = ?', (video_id,))
        # frames表设置了ON DELETE CASCADE，会自动删除
        conn.commit()
        self.close_conn()
    
    # ==================== 帧操作 ====================
    
    def add_frame(self, video_id: int, frame_idx: int, pts_ms: int, 
                 image_path: str, **kwargs) -> int:
        """
        添加帧记录（带重试机制）
        
        Args:
            video_id: 视频ID
            frame_idx: 帧序号
            pts_ms: 时间戳（毫秒）
            image_path: 图片路径
            **kwargs: OCR和分类结果字段
        """
        def _add():
            conn = self.get_conn()
            cursor = conn.cursor()
            
            image_filename = os.path.basename(image_path)
            fields = ['video_id', 'frame_idx', 'pts_ms', 'image_path', 'image_filename']
            values = [video_id, frame_idx, pts_ms, image_path, image_filename]
            
            # 添加其他字段
            allowed_fields = [
                'frame_pts',
                'ocr_text', 'ocr_time', 'ocr_train_no', 'ocr_route_section',
                'ocr_carriage_no', 'ocr_position_no', 'ocr_speed', 
                'ocr_mileage', 'ocr_confidence',
                'label_weather', 'label_weather_score',
                'label_location', 'label_location_score',
                'label_time_period', 'label_time_period_score',
                'label_anomaly', 'label_anomaly_score',
                'labels_json', 'ai_processed'
            ]
            
            for field in allowed_fields:
                if field in kwargs:
                    fields.append(field)
                    value = kwargs[field]
                    # JSON字段需要序列化
                    if field == 'labels_json' and isinstance(value, dict):
                        value = json.dumps(value)
                    values.append(value)
            
            placeholders = ','.join(['?'] * len(values))
            field_names = ','.join(fields)
            
            cursor.execute(
                f'INSERT INTO frames ({field_names}) VALUES ({placeholders})',
                values
            )
            frame_id = cursor.lastrowid
            conn.commit()
            return frame_id
        
        return self.execute_with_retry(_add)
    
    def batch_add_frames(self, frames_data: List[Dict]):
        """批量添加帧记录（带事务）"""
        def _batch_add():
            conn = self.get_conn()
            cursor = conn.cursor()
            
            cursor.execute('BEGIN')
            try:
                for frame in frames_data:
                    video_id = frame['video_id']
                    frame_idx = frame['frame_idx']
                    pts_ms = frame['pts_ms']
                    image_path = frame['image_path']
                    
                    # 移除必须字段
                    kwargs = {k: v for k, v in frame.items() 
                             if k not in ['video_id', 'frame_idx', 'pts_ms', 'image_path']}
                    
                    # 直接插入，不使用递归调用
                    image_filename = os.path.basename(image_path)
                    fields = ['video_id', 'frame_idx', 'pts_ms', 'image_path', 'image_filename']
                    values = [video_id, frame_idx, pts_ms, image_path, image_filename]
                    
                    for k, v in kwargs.items():
                        fields.append(k)
                        if k == 'labels_json' and isinstance(v, dict):
                            v = json.dumps(v)
                        values.append(v)
                    
                    placeholders = ','.join(['?'] * len(values))
                    field_names = ','.join(fields)
                    
                    cursor.execute(
                        f'INSERT INTO frames ({field_names}) VALUES ({placeholders})',
                        values
                    )
                
                cursor.execute('COMMIT')
                print(f"✅ 批量添加 {len(frames_data)} 帧")
                return True
                
            except Exception as e:
                cursor.execute('ROLLBACK')
                raise e
        
        return self.execute_with_retry(_batch_add)
    
    def get_frame(self, frame_id: int) -> Optional[Dict]:
        """获取帧信息"""
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM frames WHERE id = ?', (frame_id,))
        row = cursor.fetchone()
        self.close_conn()
        return dict(row) if row else None
    
    def update_frame_ai_results(self, frame_id: int, ocr_results: Dict = None, 
                                classification_results: Dict = None):
        """
        更新帧的AI处理结果（带重试机制）
        
        Args:
            frame_id: 帧ID
            ocr_results: OCR结果字典
            classification_results: 分类结果字典
        """
        def _update():
            conn = self.get_conn()
            cursor = conn.cursor()
            
            fields = []
            values = []
            updated_ocr_text = None
            
            if ocr_results:
                for key, value in ocr_results.items():
                    if key.startswith('ocr_'):
                        fields.append(f'{key} = ?')
                        values.append(value)
                        if key == 'ocr_text':
                            updated_ocr_text = value if value is not None else ''
            
            if classification_results:
                for key, value in classification_results.items():
                    if key.startswith('label_'):
                        fields.append(f'{key} = ?')
                        values.append(value)
                
                # 保存完整的分类结果JSON
                if 'labels_json' in classification_results:
                    fields.append('labels_json = ?')
                    values.append(json.dumps(classification_results['labels_json']))
            
            if fields:
                fields.append('ai_processed = 1')
                # fields.append('ai_processed_at = ?')
                fields.append('updated_at = ?')
                now = datetime.now().isoformat()
                values.append(now)
                values.append(frame_id)
                
                sql = f"UPDATE frames SET {','.join(fields)} WHERE id = ?"
                cursor.execute(sql, values)
                conn.commit()
            
            return True
        
        return self.execute_with_retry(_update)
    
    def list_frames(self, video_id: int = None, ai_processed: bool = None,
                   limit: int = None, offset: int = 0) -> List[Dict]:
        """列出帧记录"""
        conn = self.get_conn()
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if video_id is not None:
            conditions.append('video_id = ?')
            params.append(video_id)
        
        if ai_processed is not None:
            conditions.append('ai_processed = ?')
            params.append(1 if ai_processed else 0)
        
        where_clause = ' AND '.join(conditions) if conditions else '1=1'
        sql = f'SELECT * FROM frames WHERE {where_clause} ORDER BY video_id, frame_idx'
        
        if limit:
            sql += f' LIMIT {limit} OFFSET {offset}'
        
        cursor.execute(sql, params)
        frames = [dict(row) for row in cursor.fetchall()]
        self.close_conn()
        return frames

    def get_frame_idx_sets(self, video_id: int) -> Tuple[Set[int], Set[int]]:
        """
        获取某个视频的帧索引集合：
        - existing_frame_idxs：该视频在 frames 表里出现过的 frame_idx（去重）
        - processed_frame_idxs：其中 ai_processed=1 的 frame_idx（去重）
        """
        conn = self.get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT frame_idx, MAX(ai_processed) AS processed "
                "FROM frames "
                "WHERE video_id = ? "
                "GROUP BY frame_idx",
                (video_id,)
            )
            existing: Set[int] = set()
            processed: Set[int] = set()
            for row in cursor.fetchall():
                idx = int(row["frame_idx"])
                existing.add(idx)
                if int(row["processed"] or 0) == 1:
                    processed.add(idx)
            return existing, processed
        finally:
            self.close_conn()

    def cleanup_processed_frame_images(self, video_id: int = None, clear_image_path: bool = True) -> Dict:
        """
        清理已完成 AI 处理（ai_processed=1）的帧图片文件。
        
        删除条件：
        - ai_processed = 1
        - image_path 非空
        - (可选) 限定 video_id
        
        Args:
            video_id: 可选，仅清理某个视频的帧图片
            clear_image_path: 删除后是否将对应 frames.image_path 置空（避免前端误用）
        
        Returns:
            {'scanned': int, 'removed': int, 'missing': int, 'failed': int, 'cleared': int}
        """
        def _cleanup():
            conn = self.get_conn()
            cursor = conn.cursor()
            
            conditions = [
                "ai_processed = 1",
                "image_path IS NOT NULL",
                "TRIM(image_path) != ''",
            ]
            params: List = []
            if video_id is not None:
                conditions.append("video_id = ?")
                params.append(video_id)
            
            where_clause = " AND ".join(conditions)
            cursor.execute(f"SELECT id, image_path FROM frames WHERE {where_clause}", params)
            rows = cursor.fetchall()
            
            scanned = len(rows)
            removed = 0
            missing = 0
            failed = 0
            ids_to_clear: List[int] = []
            
            for r in rows:
                fid = r["id"]
                p = (r["image_path"] or "").strip()
                if not p:
                    continue
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                        removed += 1
                        if clear_image_path:
                            ids_to_clear.append(fid)
                    else:
                        # 不存在或不是文件（例如已被清理）
                        missing += 1
                        if clear_image_path:
                            ids_to_clear.append(fid)
                except Exception:
                    failed += 1
            
            cleared = 0
            if clear_image_path and ids_to_clear:
                # 分批更新，避免 SQLite 变量上限（默认 999）
                chunk_size = 500
                for i in range(0, len(ids_to_clear), chunk_size):
                    chunk = ids_to_clear[i:i + chunk_size]
                    placeholders = ",".join(["?"] * len(chunk))
                    cursor.execute(
                        f"UPDATE frames SET image_path = '' WHERE id IN ({placeholders})",
                        chunk
                    )
                conn.commit()
                cleared = len(ids_to_clear)
            
            return {
                'scanned': scanned,
                'removed': removed,
                'missing': missing,
                'failed': failed,
                'cleared': cleared
            }
        
        return self.execute_with_retry(_cleanup)
    
    # ==================== 高级查询 ====================
    
    def query_frames(self, 
                    start_time: str = None,
                    end_time: str = None,
                    train_no: str = None,
                    route_section: str = None,
                    weather: str = None,
                    location: str = None,
                    time_period: str = None,
                    min_speed: float = None,
                    max_speed: float = None,
                    limit: int = 100,
                    offset: int = 0) -> List[Dict]:
        """
        高级帧查询
        
        Args:
            start_time: 开始时间（ISO格式）
            end_time: 结束时间（ISO格式）
            train_no: 车次号
            route_section: 区间
            weather: 天气标签
            location: 位置标签
            time_period: 时段标签
            min_speed: 最小速度
            max_speed: 最大速度
            limit: 返回数量
            offset: 偏移量
        """
        conn = self.get_conn()
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if start_time:
            conditions.append('ocr_time >= ?')
            params.append(start_time)
        
        if end_time:
            conditions.append('ocr_time <= ?')
            params.append(end_time)
        
        if train_no:
            conditions.append('ocr_train_no = ?')
            params.append(train_no)
        
        if route_section:
            conditions.append('ocr_route_section LIKE ?')
            params.append(f'%{route_section}%')
        
        if weather:
            conditions.append('label_weather = ?')
            params.append(weather)
        
        if location:
            conditions.append('label_location = ?')
            params.append(location)
        
        if time_period:
            conditions.append('label_time_period = ?')
            params.append(time_period)
        
        if min_speed is not None:
            conditions.append('ocr_speed >= ?')
            params.append(min_speed)
        
        if max_speed is not None:
            conditions.append('ocr_speed <= ?')
            params.append(max_speed)
        
        where_clause = ' AND '.join(conditions) if conditions else '1=1'
        sql = f'''
            SELECT * FROM frames 
            WHERE {where_clause} 
            ORDER BY ocr_time, frame_idx
            LIMIT {limit} OFFSET {offset}
        '''
        
        cursor.execute(sql, params)
        frames = [dict(row) for row in cursor.fetchall()]
        self.close_conn()
        return frames
    
    def search_ocr_text(self, keyword: str, limit: int = 100) -> List[Dict]:
        """
        基于OCR文本的简单包含搜索（LIKE）
        
        Args:
            keyword: 搜索关键词
            limit: 返回数量
        """
        conn = self.get_conn()
        cursor = conn.cursor()
        like = f'%{keyword}%'
        cursor.execute('SELECT * FROM frames WHERE ocr_text LIKE ? LIMIT ?', (like, limit))
        frames = [dict(row) for row in cursor.fetchall()]
        self.close_conn()
        return frames
    
    def advanced_query_frames(self, 
                              conditions: Dict = None,
                              video_ids: List[int] = None,
                              limit: int = 100,
                              offset: int = 0) -> List[Dict]:
        """
        高级帧查询，支持复杂条件组合
        
        Args:
            conditions: 查询条件字典，支持嵌套逻辑
                示例1 - 简单AND: {"ocr_train_no": "G4926", "label_weather": "晴天"}
                示例2 - OR逻辑: {"$or": [{"label_weather": "晴天"}, {"label_weather": "阴天"}]}
                示例3 - NOT逻辑: {"$not": {"label_location": "隧道内"}}
                示例4 - 复合: {"$and": [
                    {"ocr_train_no": "G4926"},
                    {"$or": [{"label_weather": "晴天"}, {"label_weather": "阴天"}]},
                    {"$not": {"label_location": "隧道内"}}
                ]}
                示例5 - 范围: {"ocr_speed": {"$gte": 200, "$lte": 300}}
                示例6 - 模糊: {"ocr_route_section": {"$like": "广州"}}
            video_ids: 限制在指定视频ID列表中查询（None表示所有视频）
            limit: 返回数量
            offset: 偏移量
            
        Returns:
            符合条件的帧列表
        """
        conn = self.get_conn()
        cursor = conn.cursor()
        
        where_parts = []
        params = []
        
        # 视频ID限制
        if video_ids:
            placeholders = ','.join(['?'] * len(video_ids))
            where_parts.append(f'video_id IN ({placeholders})')
            params.extend(video_ids)
        
        # 构建条件子句
        if conditions:
            condition_sql, condition_params = self._build_condition_sql(conditions)
            if condition_sql:
                where_parts.append(f'({condition_sql})')
                params.extend(condition_params)
        
        # 组合WHERE子句
        where_clause = ' AND '.join(where_parts) if where_parts else '1=1'
        
        sql = f'''
            SELECT f.*, v.path as video_path, v.filename as video_filename
            FROM frames f
            JOIN videos v ON f.video_id = v.id
            WHERE {where_clause}
            ORDER BY f.ocr_time, f.frame_idx
            LIMIT {limit} OFFSET {offset}
        '''
        
        cursor.execute(sql, params)
        frames = [dict(row) for row in cursor.fetchall()]
        self.close_conn()
        return frames
    
    def _build_condition_sql(self, conditions: Dict) -> Tuple[str, List]:
        """
        递归构建SQL条件子句
        
        Args:
            conditions: 条件字典
            
        Returns:
            (sql_string, params_list)
        """
        if not conditions:
            return '', []
        
        # 处理逻辑操作符
        if '$and' in conditions:
            sub_conditions = []
            all_params = []
            for sub_cond in conditions['$and']:
                sql, params = self._build_condition_sql(sub_cond)
                if sql:
                    sub_conditions.append(f'({sql})')
                    all_params.extend(params)
            return ' AND '.join(sub_conditions), all_params
        
        elif '$or' in conditions:
            sub_conditions = []
            all_params = []
            for sub_cond in conditions['$or']:
                sql, params = self._build_condition_sql(sub_cond)
                if sql:
                    sub_conditions.append(f'({sql})')
                    all_params.extend(params)
            return ' OR '.join(sub_conditions), all_params
        
        elif '$not' in conditions:
            sql, params = self._build_condition_sql(conditions['$not'])
            return f'NOT ({sql})', params
        
        # 处理字段条件
        else:
            field_conditions = []
            all_params = []
            
            for field, value in conditions.items():
                if field.startswith('$'):
                    continue  # 跳过操作符
                
                # 处理复杂值（范围、模糊匹配等）
                if isinstance(value, dict):
                    if '$gte' in value:
                        field_conditions.append(f'{field} >= ?')
                        all_params.append(value['$gte'])
                    if '$lte' in value:
                        field_conditions.append(f'{field} <= ?')
                        all_params.append(value['$lte'])
                    if '$gt' in value:
                        field_conditions.append(f'{field} > ?')
                        all_params.append(value['$gt'])
                    if '$lt' in value:
                        field_conditions.append(f'{field} < ?')
                        all_params.append(value['$lt'])
                    if '$like' in value:
                        field_conditions.append(f'{field} LIKE ?')
                        all_params.append(f'%{value["$like"]}%')
                    if '$ne' in value:
                        field_conditions.append(f'{field} != ?')
                        all_params.append(value['$ne'])
                else:
                    # 简单相等匹配
                    field_conditions.append(f'{field} = ?')
                    all_params.append(value)
            
            return ' AND '.join(field_conditions), all_params
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        conn = self.get_conn()
        cursor = conn.cursor()
        
        # 视频统计
        cursor.execute('SELECT COUNT(*) as total FROM videos')
        total_videos = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM videos WHERE status = "extracted"')
        extracted_videos = cursor.fetchone()['total']
        
        # 帧统计
        cursor.execute('SELECT COUNT(*) as total FROM frames')
        total_frames = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM frames WHERE ai_processed = 1')
        processed_frames = cursor.fetchone()['total']
        
        # 标签分布
        cursor.execute('''
            SELECT label_weather, COUNT(*) as count 
            FROM frames 
            WHERE label_weather IS NOT NULL 
            GROUP BY label_weather
        ''')
        weather_dist = {row['label_weather']: row['count'] for row in cursor.fetchall()}
        
        cursor.execute('''
            SELECT label_location, COUNT(*) as count 
            FROM frames 
            WHERE label_location IS NOT NULL 
            GROUP BY label_location
        ''')
        location_dist = {row['label_location']: row['count'] for row in cursor.fetchall()}
        
        self.close_conn()
        
        return {
            'total_videos': total_videos,
            'extracted_videos': extracted_videos,
            'total_frames': total_frames,
            'processed_frames': processed_frames,
            'weather_distribution': weather_dist,
            'location_distribution': location_dist
        }
    
    # ==================== 工具方法 ====================
    
    def _calculate_sha1(self, filepath: str) -> str:
        """计算文件SHA1"""
        sha1 = hashlib.sha1()
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                sha1.update(data)
        return sha1.hexdigest()
    
    def log_processing(self, video_id: int, operation: str, 
                      status: str, details: Dict = None, 
                      error_msg: str = None, duration_sec: float = None):
        """记录处理日志（带重试机制）"""
        def _log():
            conn = self.get_conn()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO processing_logs 
                (video_id, operation, status, details, error_msg, 
                 started_at, completed_at, duration_sec)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                video_id, operation, status,
                json.dumps(details) if details else None,
                error_msg,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                duration_sec
            ))
            conn.commit()
            return True
        
        try:
            return self.execute_with_retry(_log)
        except Exception as e:
            # 日志记录失败不应该影响主流程
            print(f"⚠️  日志记录失败: {e}")
            return False


# 全局实例
video_db = VideoDatabase()


if __name__ == '__main__':
    # 测试
    db = VideoDatabase()
    print("✅ 视频数据库初始化成功")
    
    # 测试添加视频
    video_id = db.add_video(
        path='/test/video.mp4',
        filename='video.mp4',
        train_no='G4926',
        route_section='佛山西-宜宾',
        fps=30.0,
        duration_sec=120.5,
        status='pending'
    )
    print(f"✅ 添加测试视频 ID: {video_id}")
    
    # 获取统计信息
    stats = db.get_statistics()
    print(f"📊 统计信息: {stats}")
