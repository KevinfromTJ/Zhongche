"""
视频帧提取服务
优化了鲁棒性和效率，支持错误恢复和数据库集成
"""
import cv2
import os
import imageio
import subprocess
import shutil
from imageio_ffmpeg import get_ffmpeg_exe
from typing import Tuple, Optional, Dict, List
from datetime import datetime
import sys
import re

# 添加父目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.video_database import video_db
from services.frame_accessor import FFmpegAccessor

def clean_dir(dir_path: str):
    """清理目录下所有文件和子目录"""
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)
    os.makedirs(dir_path, exist_ok=True)

class VideoFrameExtractor:
    """视频帧提取器"""
    
    def __init__(self, output_base_dir: str = None):
        """
        Args:
            output_base_dir: 帧输出根目录，默认为 backend/data/video_frames
        """
        if output_base_dir is None:
            output_base_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data', 'video_frames'
            )
        self.output_base_dir = output_base_dir
        os.makedirs(self.output_base_dir, exist_ok=True)
    
    def get_video_metadata(self, video_path: str) -> Dict:
        """
        获取视频元数据
        
        Returns:
            {
                'fps': float,
                'total_frames': int,
                'duration_sec': float,
                'width': int,
                'height': int,
                'file_size': int
            }
        """
        metadata = {
            'fps': 0,
            'total_frames': 0,
            'duration_sec': 0,
            'width': 0,
            'height': 0,
            'file_size': os.path.getsize(video_path) if os.path.exists(video_path) else 0
        }
        
        try:
            # 尝试用OpenCV获取信息
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                metadata['fps'] = cap.get(cv2.CAP_PROP_FPS)
                metadata['total_frames'] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                metadata['width'] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                metadata['height'] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                
                # 计算时长
                if metadata['fps'] > 0:
                    metadata['duration_sec'] = metadata['total_frames'] / metadata['fps']
                
                cap.release()
                
                # 如果帧数不可靠（过大），用ffprobe获取时长
                if metadata['total_frames'] > 1000000 or metadata['total_frames'] < 10:
                    duration = self._get_duration_via_imageio(video_path)
                    if duration:
                        metadata['duration_sec'] = duration
                        metadata['total_frames'] = int(duration * metadata['fps'])
        except Exception as e:
            print(f"⚠️  OpenCV获取元数据失败: {e}")
            
            # 降级到 imageio 元数据
            try:
                duration = self._get_duration_via_imageio(video_path)
                if duration:
                    metadata['duration_sec'] = duration
                    metadata['fps'] = 25.0  # 默认FPS
                    metadata['total_frames'] = int(duration * metadata['fps'])
            except Exception as e2:
                print(f"⚠️  通过 imageio 获取元数据失败: {e2}")
        
        return metadata
    
    def _get_duration_via_imageio(self, video_path: str) -> Optional[float]:
        """使用纯Python方式获取视频时长（通过 imageio 元数据），不依赖系统级命令"""
        try:
            reader = imageio.get_reader(video_path)
            meta = reader.get_meta_data()
            reader.close()
            # imageio 的元数据里通常包含 'duration'（秒）
            duration = meta.get('duration')
            if duration is None:
                # 某些容器没有 duration，可由帧数与fps估算
                nframes = meta.get('nframes') or 0
                fps = meta.get('fps') or 0
                if fps and nframes:
                    duration = float(nframes) / float(fps)
            return float(duration) if duration is not None else None
        except Exception:
            return None
    
    def extract_frames(self, video_path: str, video_id: int = None,
                      max_frames: int = None, sample_rate: int = None,
                      save_to_db: bool = True) -> Dict:
        """
        提取视频帧
        
        Args:
            video_path: 视频路径
            video_id: 视频ID（如果已在数据库中）
            max_frames: 最大提取帧数（超过则等间隔采样）
            sample_rate: 采样率（每N帧提取1帧， 会覆盖上一个参数）
            save_to_db: 是否保存到数据库
        
        Returns:
            {
                'success': bool,
                'video_id': int,
                'extracted_frames': int,
                'output_dir': str,
                'error': str (if failed)
            }
        """
        start_time = datetime.now()
        output_dir = ""
        try:
            # 1. 获取视频元数据
            print(f"\n📹 开始处理视频: {video_path}")
            metadata = self.get_video_metadata(video_path)
            print(f"   元数据: FPS={metadata['fps']}, 总帧数={metadata['total_frames']}, "
                  f"时长={metadata['duration_sec']:.2f}s, 分辨率={metadata['width']}x{metadata['height']}")
            
            # 2. 添加到数据库或更新
            if save_to_db:
                if video_id is None:
                    video_id = video_db.add_video(
                        path=video_path,
                        filename=os.path.basename(video_path),
                        fps=metadata['fps'],
                        duration_sec=metadata['duration_sec'],
                        total_frames=metadata['total_frames'],
                        width=metadata['width'],
                        height=metadata['height'],
                        file_size=metadata['file_size'],
                        status='extracting'
                    )
                else:
                    video_db.update_video(
                        video_id,
                        fps=metadata['fps'],
                        duration_sec=metadata['duration_sec'],
                        total_frames=metadata['total_frames'],
                        width=metadata['width'],
                        height=metadata['height'],
                        file_size=metadata['file_size'],
                        status='extracting'
                    )
            
            # 3. 确定输出目录
            video_name = os.path.splitext(os.path.basename(video_path))[0]
            output_dir = os.path.join(self.output_base_dir, str(video_id), video_name)
            
            # 如果目录存在且不为空，检查是否需要重新提取
            if os.path.exists(output_dir) and os.listdir(output_dir):
                existing_frames = len([f for f in os.listdir(output_dir) if f.endswith('.jpg')])
                print(f"   ⚠️  输出目录已存在 {existing_frames} 个帧，跳过提取")
                
                if save_to_db:
                    video_db.update_video(video_id, status='extracted')
                
                clean_dir(output_dir)

                return {
                    'success': True,
                    'video_id': video_id,
                    'extracted_frames': existing_frames,
                    'output_dir': output_dir,
                    'skipped': True
                }
            
            os.makedirs(output_dir, exist_ok=True)
            
            # 4. 计算采样策略
            total_frames = metadata['total_frames']
            
            if sample_rate:
                # 手动指定采样率
                sample_interval = sample_rate
                estimated_output = (total_frames + sample_interval - 1) // sample_interval
                print(f"   策略: 每 {sample_interval} 帧采样1帧，预计提取 {estimated_output} 帧")
            elif max_frames and total_frames > max_frames:
                # 根据最大帧数计算采样间隔
                sample_interval = max(1, total_frames // max_frames)
                estimated_output = (total_frames + sample_interval - 1) // sample_interval
                print(f"   策略: 限制{max_frames}帧，每 {sample_interval} 帧采样1帧，预计提取 {estimated_output} 帧")
            else:
                # 提取所有帧
                sample_interval = 1
                estimated_output = total_frames
                print(f"   策略: 提取所有 {total_frames} 帧")
            
            # 5. 开始提取（优先 ffmpeg 带 -frame_pts 以便记录精确 PTS；失败再回退 imageio）
            try:
                extracted_frames = self._extract_with_ffmpeg_cli_pts(
                    video_path, output_dir, video_id, sample_interval,
                    metadata['fps'], save_to_db
                )
            except Exception as e_ff:
                print(f"⚠️  ffmpeg PTS 提取失败，尝试使用 imageio 回退: {e_ff}")
                extracted_frames = self._extract_with_imageio(
                    video_path, output_dir, video_id, sample_interval,
                    metadata['fps'], save_to_db
                )
            
            # 6. 更新状态
            if save_to_db:
                video_db.update_video(video_id, status='extracted')
                
                # 记录日志
                duration = (datetime.now() - start_time).total_seconds()
                video_db.log_processing(
                    video_id=video_id,
                    operation='extract_frames',
                    status='success',
                    details={
                        'extracted_frames': extracted_frames,
                        'sample_interval': sample_interval,
                        'output_dir': output_dir
                    },
                    duration_sec=duration
                )
            
            print(f"✅ 提取完成: {extracted_frames} 帧，用时 {(datetime.now() - start_time).total_seconds():.2f}s")
            
            # 清理output_dir，仅保留文件夹本身
            clean_dir(output_dir)

            return {
                'success': True,
                'video_id': video_id,
                'extracted_frames': extracted_frames,
                'output_dir': output_dir
            }
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ 提取失败: {error_msg}")
            
            if save_to_db and video_id:
                video_db.update_video(video_id, status='error', error_msg=error_msg)
                
                duration = (datetime.now() - start_time).total_seconds()
                video_db.log_processing(
                    video_id=video_id,
                    operation='extract_frames',
                    status='failed',
                    error_msg=error_msg,
                    duration_sec=duration
                )
            
            clean_dir(output_dir)

            return {
                'success': False,
                'video_id': video_id,
                'error': error_msg
            }
    
    def _extract_with_imageio(self, video_path: str, output_dir: str,
                             video_id: int, sample_interval: int,
                             fps: float, save_to_db: bool) -> int:
        """使用imageio提取帧（更稳定）"""
        reader = imageio.get_reader(video_path)
        
        extracted_count = 0
        frame_idx = 0
        
        # 批量存储帧信息
        frames_buffer = []
        buffer_size = 100  # 每100帧批量写入数据库
        # 记录自上次成功批量提交以来生成但尚未入库的文件，确保异常时清理
        uncommitted_paths = []
        
        for frame in reader:
            # 根据采样间隔决定是否保存
            if frame_idx % sample_interval == 0:
                # 保存图片
                image_filename = f"frame_{extracted_count:06d}.jpg"
                image_path = os.path.join(output_dir, image_filename)
                imageio.imwrite(image_path, frame)
                uncommitted_paths.append(image_path)
                
                # 计算时间戳（毫秒）
                pts_ms = int((frame_idx / fps) * 1000) if fps > 0 else frame_idx * 40
                
                # 添加到数据库（批量）
                if save_to_db:
                    frames_buffer.append({
                        'video_id': video_id,
                        'frame_idx': frame_idx,
                        'pts_ms': pts_ms,
                        'image_path': image_path
                    })
                    
                    # 达到缓冲区大小，批量写入
                    if len(frames_buffer) >= buffer_size:
                        try:
                            video_db.batch_add_frames(frames_buffer)
                            frames_buffer = []
                            # 批量写入成功后，对应文件视为已提交
                            uncommitted_paths = []
                        except Exception as e:
                            # 批量入库失败，清理未提交的文件，保持一致性
                            for p in uncommitted_paths:
                                try:
                                    if os.path.exists(p):
                                        os.remove(p)
                                except Exception:
                                    pass
                            reader.close()
                            raise
                
                extracted_count += 1
            
            frame_idx += 1
            
            # 定期打印进度
            if extracted_count % 500 == 0:
                print(f"   已提取 {extracted_count} 帧...")
        
        # 写入剩余的帧
        if save_to_db and frames_buffer:
            try:
                video_db.batch_add_frames(frames_buffer)
                # 最终提交成功，清空未提交文件列表
                uncommitted_paths = []
            except Exception:
                # 清理剩余未提交文件
                for p in uncommitted_paths:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                reader.close()
                raise
        
        reader.close()
        return extracted_count
    
    def _extract_with_ffmpeg_cli_pts(self, video_path: str, output_dir: str,
                                     video_id: int, sample_interval: int,
                                     fps: float, save_to_db: bool) -> int:
        """
        使用 imageio-ffmpeg 提供的 ffmpeg 抽帧：
        - 启用 -frame_pts 1，使文件名包含帧 PTS 以便精确索引
        - 失败时会在上层回退到 imageio
        """
        accessor = FFmpegAccessor()
        # 先输出到临时目录，成功入库后再迁移，失败则清理临时目录，保证原子性
        tmp_dir = os.path.join(output_dir, ".tmp_ffmpeg")
        os.makedirs(tmp_dir, exist_ok=True)

        # 探测视频流 time_base & fps（带原始码流兜底）
        tb_num, tb_den, probed_fps = accessor.robust_probe_time_base_and_fps(video_path)
        if probed_fps and probed_fps > 0:
            fps = probed_fps
        # 持久化视频级元数据
        video_db.update_video(
            video_id,
            v_stream_index=0,  # 此处约定选择 0 号视频流
            v_time_base_num=tb_num,
            v_time_base_den=tb_den,
        )

        # 抽帧（文件名为 PTS）
        _ = accessor.extract_frames_to_dir_with_pts(
            video_path=video_path,
            out_dir=tmp_dir,
            sample_interval=sample_interval or 1,
        )
        
        # 扫描生成的帧文件并写入数据库
        files = sorted(f for f in os.listdir(tmp_dir) if f.startswith("frame_") and f.endswith(".jpg"))
        extracted_count = 0
        frames_buffer = []
        buffer_size = 100
        
        for i, fname in enumerate(files):
            image_path = os.path.join(tmp_dir, fname)
            # 估算原始帧序号（按间隔）
            frame_idx = i * (sample_interval if sample_interval else 1)
            # 从文件名解析 PTS 并换算 ms： ms = pts * num/den * 1000
            m = re.match(r"frame_(\d+)\.jpg$", fname)
            frame_pts = int(m.group(1)) if m else None
            if frame_pts is not None and tb_den and tb_num:
                pts_ms = int(round((frame_pts * tb_num / tb_den) * 1000.0))
            else:
                pts_ms = int((frame_idx / fps) * 1000) if fps and fps > 0 else frame_idx * 40
            
            if save_to_db:
                frames_buffer.append({
                    'video_id': video_id,
                    'frame_idx': frame_idx,
                    'pts_ms': pts_ms,
                    'frame_pts': frame_pts,
                    'image_path': image_path
                })
                if len(frames_buffer) >= buffer_size:
                    try:
                        video_db.batch_add_frames(frames_buffer)
                        frames_buffer = []
                    except Exception as e:
                        # 入库失败，清理临时目录
                        try:
                            if os.path.exists(tmp_dir):
                                shutil.rmtree(tmp_dir)
                        except Exception:
                            pass
                        raise
            extracted_count += 1
        
        if save_to_db and frames_buffer:
            try:
                video_db.batch_add_frames(frames_buffer)
            except Exception:
                try:
                    if os.path.exists(tmp_dir):
                        shutil.rmtree(tmp_dir)
                except Exception:
                    pass
                raise
        
        # 入库成功后再将临时文件迁移到最终目录
        try:
            for fname in files:
                src = os.path.join(tmp_dir, fname)
                dst = os.path.join(output_dir, fname)
                # 使用原子移动（同分区快速）
                shutil.move(src, dst)
            # 清理空临时目录
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as e:
            # 迁移失败时，不影响数据库记录，但清理临时目录以免堆积
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
        
        return extracted_count
    
    def batch_extract(self, video_paths: List[str], **kwargs) -> List[Dict]:
        """
        批量提取多个视频的帧
        
        Args:
            video_paths: 视频路径列表
            **kwargs: 传递给extract_frames的参数
        
        Returns:
            结果列表
        """
        results = []
        
        for i, video_path in enumerate(video_paths, 1):
            print(f"\n{'='*60}")
            print(f"处理进度: {i}/{len(video_paths)}")
            
            result = self.extract_frames(video_path, **kwargs)
            results.append(result)
            
            if not result['success']:
                print(f"⚠️  跳过失败的视频: {video_path}")
        
        # 汇总统计
        success_count = sum(1 for r in results if r['success'])
        total_frames = sum(r.get('extracted_frames', 0) for r in results)
        
        print(f"\n{'='*60}")
        print(f"📊 批量提取完成:")
        print(f"   成功: {success_count}/{len(video_paths)}")
        print(f"   总帧数: {total_frames}")
        
        return results


if __name__ == '__main__':
    # 测试代码
    extractor = VideoFrameExtractor()
    
    # 测试单个视频
    test_video = "/data/chenjuntao/OtherProj/test_bb_frames/ori_video/plastic_1.mp4"
    
    if os.path.exists(test_video):
        result = extractor.extract_frames(
            video_path=test_video,
            max_frames=200,  # 最多提取200帧
            save_to_db=True
        )
        print(f"\n测试结果: {result}")
    else:
        print(f"测试视频不存在: {test_video}")
