"""
视频管理路由
提供视频上传、抽帧、AI处理、查询等API
"""
from flask import Blueprint, request, jsonify, send_file
import os
import sys
from datetime import datetime
from io import BytesIO
from werkzeug.utils import secure_filename
import threading
import traceback

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.video_database import video_db
from services.video_frame_extractor import VideoFrameExtractor
from services.video_ocr_service import video_ocr_service
from services.video_classifier_service import video_classifier_service
from config import DATASETS_DIR, DELETE_FRAME_IMAGES_AFTER_AI
from services.frame_accessor import FFmpegAccessor

import traceback

video_bp = Blueprint('video', __name__)

# 视频上传目录
VIDEO_UPLOAD_DIR = os.path.join(os.path.dirname(DATASETS_DIR), 'videos')
os.makedirs(VIDEO_UPLOAD_DIR, exist_ok=True)

# 允许的视频格式
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'}

# 帧提取器（串行执行）
frame_extractor = VideoFrameExtractor()
_extract_lock = threading.Lock()


def allowed_video_file(filename):
    """检查文件扩展名"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


# ==================== 视频管理 ====================

@video_bp.route('/videos', methods=['GET'])
def list_videos():
    """
    获取视频列表
    
    Query参数:
        status: 过滤状态 (pending/extracting/extracted/error)
        train_no: 过滤车次号
        limit: 返回数量限制
        offset: 偏移量
    """
    status = request.args.get('status')
    train_no = request.args.get('train_no')
    limit = request.args.get('limit', type=int)
    offset = request.args.get('offset', 0, type=int)
    
    videos = video_db.list_videos(
        status=status,
        train_no=train_no,
        limit=limit,
        offset=offset
    )
    
    return jsonify({
        'success': True,
        'count': len(videos),
        'data': videos
    })


@video_bp.route('/videos/<int:video_id>', methods=['GET'])
def get_video_detail(video_id):
    """获取视频详情"""
    video = video_db.get_video(video_id)
    
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    
    # 获取帧数统计
    frames = video_db.list_frames(video_id=video_id, limit=1)
    frame_count = len(video_db.list_frames(video_id=video_id))
    processed_count = len(video_db.list_frames(video_id=video_id, ai_processed=True))
    
    video['frame_count'] = frame_count
    video['processed_frame_count'] = processed_count
    
    return jsonify({
        'success': True,
        'data': video
    })


@video_bp.route('/videos/upload', methods=['POST'])
def upload_video():
    """
    上传视频文件
    
    Form参数:
        file: 视频文件
        train_no: 车次号（可选）
        route_section: 区间（可选）
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '未上传文件'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'message': '文件名为空'}), 400
    
    if not allowed_video_file(file.filename):
        return jsonify({
            'success': False,
            'message': f'不支持的文件格式，仅支持: {ALLOWED_VIDEO_EXTENSIONS}'
        }), 400
    
    # 保存文件
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{timestamp}_{filename}"
    filepath = os.path.join(VIDEO_UPLOAD_DIR, filename)
    
    file.save(filepath)
    
    # 获取额外参数
    train_no = request.form.get('train_no')
    route_section = request.form.get('route_section')
    
    # 添加到数据库
    video_id = video_db.add_video(
        path=filepath,
        filename=filename,
        train_no=train_no,
        route_section=route_section,
        status='pending'
    )
    
    return jsonify({
        'success': True,
        'message': '视频上传成功',
        'data': {
            'video_id': video_id,
            'filename': filename,
            'path': filepath
        }
    })


@video_bp.route('/videos/<int:video_id>/extract', methods=['POST'])
def extract_video_frames(video_id):
    """
    提取视频帧
    
    JSON参数:
        max_frames: 最大提取帧数（可选）
        sample_rate: 采样率（可选, 如果指定则忽略帧数）
        force_reprocess: 强制重新处理，跳过ai_processed检查（可选，默认False，用于debug）
    """
    video = video_db.get_video(video_id)
    
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    
    data = request.json or {}
    max_frames = data.get('max_frames')
    sample_rate = data.get('sample_rate')
    force_reprocess = data.get('force_reprocess', False)
    # 强制串行：不使用后台线程，使用全局锁保证同一进程内抽帧按顺序执行
    with _extract_lock:
        result = frame_extractor.extract_frames(
            video_path=video['path'],
            video_id=video_id,
            max_frames=max_frames,
            sample_rate=sample_rate,
            force_reprocess=force_reprocess
        )
    return jsonify(result)


def _extract_frames_background(video_path, video_id, max_frames, sample_rate, force_reprocess=False):
    """后台执行抽帧任务"""
    try:
        frame_extractor.extract_frames(
            video_path=video_path,
            video_id=video_id,
            max_frames=max_frames,
            sample_rate=sample_rate,
            force_reprocess=force_reprocess
        )
    except Exception as e:
        print(f"❌ 后台抽帧失败: {e}")
        video_db.update_video(video_id, status='error', error_msg=str(e))


@video_bp.route('/videos/<int:video_id>/process-ai', methods=['POST'])
def process_video_ai(video_id):
    """
    对视频的所有帧执行AI处理（OCR+分类）
    
    JSON参数:
        async: 是否异步执行（默认False）
        batch_size: 批处理大小（默认50）
    """
    video = video_db.get_video(video_id)
    
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    
    data = request.json or {}
    is_async = data.get('async', False)
    batch_size = data.get('batch_size', 50)
    
    if is_async:
        # 异步执行
        thread = threading.Thread(
            target=_process_ai_background,
            args=(video_id, batch_size)
        )
        thread.start()
        
        return jsonify({
            'success': True,
            'message': '后台AI处理任务已启动',
            'video_id': video_id
        })
    else:
        # 同步执行
        result = _process_video_ai_sync(video_id, batch_size)
        return jsonify(result)


def _process_video_ai_sync(video_id, batch_size=50):
    """同步执行AI处理"""
    start_time = datetime.now()
    
    try:
        # 获取所有未处理的帧
        frames = video_db.list_frames(video_id=video_id, ai_processed=False)
        
        if not frames:
            return {
                'success': True,
                'message': '所有帧已处理完成',
                'processed_count': 0
            }
        
        print(f"🤖 开始AI处理: 视频ID={video_id}, 待处理帧数={len(frames)}")
        
        processed_count = 0
        
        # 批量处理
        for i in range(0, len(frames), batch_size):
            batch = frames[i:i+batch_size]
            
            for frame in batch:
                # OCR提取
                ocr_result = video_ocr_service.extract_text(
                    frame['image_path'],
                    frame['frame_idx']
                )
                
                # 场景分类
                classification_result = video_classifier_service.classify(
                    frame['image_path'],
                    frame['frame_idx']
                )
                
                # 更新数据库
                print(f"classification_result: {classification_result}")
                video_db.update_frame_ai_results(
                    frame['id'],
                    ocr_results=ocr_result,
                    classification_results=classification_result
                )
                
                processed_count += 1
            
            print(f"   已处理 {processed_count}/{len(frames)} 帧")
        
        # 记录日志
        duration = (datetime.now() - start_time).total_seconds()
        video_db.log_processing(
            video_id=video_id,
            operation='ai_processing',
            status='success',
            details={'processed_frames': processed_count},
            duration_sec=duration
        )
        
        # 可选：删除已落地的帧图片，仅保留数据库索引（按需抽帧）
        if DELETE_FRAME_IMAGES_AFTER_AI:
            try:
                # 改为“独立清理”：只删除 frames 表中 image_path 非空 且 ai_processed=1 的图片，
                # 避免误删未完成 AI 的帧图片导致后续处理失败。
                stats = video_db.cleanup_processed_frame_images(video_id=None, clear_image_path=True)
                print(
                    "🧹 已清理已AI处理帧图片: "
                    f"scanned={stats.get('scanned')}, removed={stats.get('removed')}, "
                    f"missing={stats.get('missing')}, failed={stats.get('failed')}, "
                    f"cleared={stats.get('cleared')}"
                )
            except Exception as _e:
                print(f"⚠️ 清理帧图片失败: {_e}")
        
        print(f"✅ AI处理完成: {processed_count} 帧，用时 {duration:.2f}s")
        
        return {
            'success': True,
            'message': 'AI处理完成',
            'processed_count': processed_count,
            'duration_sec': round(duration, 2)
        }
        
    except Exception as e:
        error_msg = str(e)
        traceback.print_exc()
        print(f"❌ AI处理失败: {error_msg}")
        
        duration = (datetime.now() - start_time).total_seconds()
        video_db.log_processing(
            video_id=video_id,
            operation='ai_processing',
            status='failed',
            error_msg=error_msg,
            duration_sec=duration
        )
        
        return {
            'success': False,
            'error': error_msg
        }


def _process_ai_background(video_id, batch_size):
    """后台执行AI处理"""
    _process_video_ai_sync(video_id, batch_size)


@video_bp.route('/videos/<int:video_id>', methods=['DELETE'])
def delete_video(video_id):
    """删除视频及其所有帧"""
    video = video_db.get_video(video_id)
    
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    
    # 删除数据库记录（帧会级联删除）
    video_db.delete_video(video_id)
    
    # 删除视频文件（可选）
    if os.path.exists(video['path']):
        try:
            os.remove(video['path'])
        except:
            pass
    
    return jsonify({
        'success': True,
        'message': '视频已删除'
    })


@video_bp.route('/videos/register', methods=['POST'])
def register_video_path():
    """
    注册已存在的视频路径（不上传文件）
    
    JSON参数:
        path: 视频文件路径
        train_no: 车次号（可选）
        route_section: 区间（可选）
    """
    data = request.json
    path = data.get('path')
    
    if not path or not os.path.exists(path):
        return jsonify({'success': False, 'message': '视频路径不存在'}), 400
    
    # 检查是否已注册
    existing = video_db.get_video_by_path(path)
    # print(f"existing: {existing}")
    # exit()
    if existing:
        return jsonify({
            'success': True,
            'message': '视频已存在',
            'data': {
                'id': existing['id'],
                'path': existing['path']
            },
        })
    
    # 注册到数据库
    video_id = video_db.add_video(
        path=path,
        filename=os.path.basename(path),
        train_no=data.get('train_no'),
        route_section=data.get('route_section'),
        status='pending'
    )
    
    return jsonify({
        'success': True,
        'message': '视频注册成功',
        'data': {
            'id': video_id,
            'path': path
        }
    })


@video_bp.route('/videos/<int:video_id>/image-at', methods=['GET'])
def get_video_frame_at(video_id):
    """
    按时间点（秒）从视频直接抽取一帧（不依赖 frames 表），支持 seed_video_id 修复原始H264缺SPS/PPS的情况。
    Query:
      t: 秒(浮点)，必填
      quality: 1..95，默认85
      seed_video_id: 可选，参考视频ID，用于提取SPS/PPS进行修复
    """
    video = video_db.get_video(video_id)
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    video_path = video['path']
    if not os.path.exists(video_path):
        return jsonify({'success': False, 'message': '视频文件不存在'}), 404

    try:
        t = float(request.args.get('t'))
    except Exception:
        return jsonify({'success': False, 'message': '缺少或非法的参数 t'}), 400
    quality = max(1, min(95, int(request.args.get('quality', 85))))
    seed_id = request.args.get('seed_video_id', type=int)

    accessor = FFmpegAccessor()
    try:
        data = accessor.extract_frame_bytes_by_sec(
            video_path=video_path,
            t_sec=t,
            quality=quality
        )
        return send_file(BytesIO(data), mimetype='image/jpeg')
    except Exception as e:
        traceback.print_exc()
        # 尝试seed修复路径
        if seed_id:
            seed = video_db.get_video(seed_id)
            if seed and os.path.exists(seed['path']):
                try:
                    data = accessor.extract_frame_bytes_by_sec_with_seed(
                        broken_video_path=video_path,
                        t_sec=t,
                        seed_video_path=seed['path'],
                        assumed_fps=25,
                        quality=quality
                    )
                    return send_file(BytesIO(data), mimetype='image/jpeg')
                except Exception as e2:
                    traceback.print_exc()
                    return jsonify({'success': False, 'message': f'抽帧失败(含seed修复): {e2}'}), 500
        return jsonify({'success': False, 'message': f'抽帧失败: {e}'}), 500


@video_bp.route('/videos/statistics', methods=['GET'])
def get_video_statistics():
    """获取视频数据统计信息"""
    stats = video_db.get_statistics()
    
    return jsonify({
        'success': True,
        'data': stats
    })


if __name__ == '__main__':
    print("视频管理路由模块")
