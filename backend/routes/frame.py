"""
帧查询路由
提供按时间、区间、类别等条件查询帧数据的API
"""
from flask import Blueprint, request, jsonify, send_file
import os
import sys
from io import BytesIO
import time
import zipfile
from typing import Dict, List
import traceback

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.video_database import video_db
from services.frame_accessor import FFmpegAccessor

frame_bp = Blueprint('frame', __name__)


@frame_bp.route('/frames', methods=['GET'])
def list_frames():
    """
    获取帧列表（基本查询）
    
    Query参数:
        video_id: 视频ID
        ai_processed: 是否已AI处理 (true/false)
        limit: 返回数量限制
        offset: 偏移量
    """
    video_id = request.args.get('video_id', type=int)
    ai_processed_str = request.args.get('ai_processed')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    # 处理ai_processed参数
    ai_processed = None
    if ai_processed_str is not None:
        ai_processed = ai_processed_str.lower() == 'true'
    
    frames = video_db.list_frames(
        video_id=video_id,
        ai_processed=ai_processed,
        limit=limit,
        offset=offset
    )
    
    return jsonify({
        'success': True,
        'count': len(frames),
        'data': frames
    })


@frame_bp.route('/frames/<int:frame_id>', methods=['GET'])
def get_frame_detail(frame_id):
    """获取单个帧的详细信息"""
    frame = video_db.get_frame(frame_id)
    
    if not frame:
        return jsonify({'success': False, 'message': '帧不存在'}), 404
    
    return jsonify({
        'success': True,
        'data': frame
    })


@frame_bp.route('/frames/query', methods=['GET'])
def query_frames():
    """
    高级帧查询（支持多条件组合）
    
    Query参数:
        start_time: 开始时间（ISO格式，如2025-02-14T04:42:12）
        end_time: 结束时间（ISO格式）
        train_no: 车次号（如G4926）
        route_section: 区间（支持模糊匹配，如"佛山"）
        weather: 天气标签（晴天/阴天/雨天/雾天/雪天）
        location: 位置标签（站台/隧道内/出站/进站/桥梁/平原/山区）
        time_period: 时段标签（白天/夜晚/黄昏/黎明）
        min_speed: 最小速度（km/h）
        max_speed: 最大速度（km/h）
        limit: 返回数量限制（默认100）
        offset: 偏移量（默认0）
    
    示例:
        /api/frames/query?train_no=G4926&weather=晴天&min_speed=200
        /api/frames/query?start_time=2025-02-14T04:00:00&end_time=2025-02-14T05:00:00
        /api/frames/query?route_section=佛山&location=隧道内
    """
    params = {
        'start_time': request.args.get('start_time'),
        'end_time': request.args.get('end_time'),
        'train_no': request.args.get('train_no'),
        'route_section': request.args.get('route_section'),
        'weather': request.args.get('weather'),
        'location': request.args.get('location'),
        'time_period': request.args.get('time_period'),
        'min_speed': request.args.get('min_speed', type=float),
        'max_speed': request.args.get('max_speed', type=float),
        'limit': request.args.get('limit', 100, type=int),
        'offset': request.args.get('offset', 0, type=int)
    }
    
    # 移除None值的参数
    params = {k: v for k, v in params.items() if v is not None}
    
    frames = video_db.query_frames(**params)
    
    return jsonify({
        'success': True,
        'count': len(frames),
        'query_params': params,
        'data': frames
    })


@frame_bp.route('/frames/search', methods=['GET'])
def search_frames():
    """
    全文搜索OCR文本
    
    Query参数:
        keyword: 搜索关键词
        limit: 返回数量限制（默认100）
    
    示例:
        /api/frames/search?keyword=G4926
        /api/frames/search?keyword=佛山西
    """
    keyword = request.args.get('keyword')
    limit = request.args.get('limit', 100, type=int)
    
    if not keyword:
        return jsonify({'success': False, 'message': '缺少搜索关键词'}), 400
    
    frames = video_db.search_ocr_text(keyword, limit)
    
    return jsonify({
        'success': True,
        'count': len(frames),
        'keyword': keyword,
        'data': frames
    })

@frame_bp.route('/frames/batch-image', methods=['POST'])
def get_frames_batch_image():
    """
    批量按需抽帧，返回 zip：
    body: { "frame_ids": [1,2,...], "quality": 85 }
    """
    data = request.get_json(silent=True) or {}
    ids = data.get('frame_ids') or []
    try:
        ids = [int(x) for x in ids]
    except Exception:
        return jsonify({'success': False, 'message': 'frame_ids 需为整数列表'}), 400
    if not ids:
        return jsonify({'success': False, 'message': 'frame_ids 为空'}), 400
    quality = max(1, min(95, int(data.get('quality', 85))))

    frames = []
    for fid in ids:
        f = video_db.get_frame(fid)
        if f:
            frames.append(f)
    if not frames:
        return jsonify({'success': False, 'message': '未找到任何帧'}), 404

    accessor = FFmpegAccessor()
    # 按视频分组，减少重复探测
    from collections import defaultdict
    by_video = defaultdict(list)
    for f in frames:
        by_video[f['video_id']].append(f)

    zip_buf = BytesIO()
    zf = zipfile.ZipFile(zip_buf, mode='w', compression=zipfile.ZIP_STORED)

    for vid, fs in by_video.items():
        video = video_db.get_video(vid)
        if not video or not os.path.exists(video['path']):
            continue
        video_path = video['path']
        tb_num = video.get('v_time_base_num')
        tb_den = video.get('v_time_base_den')
        if not (tb_num and tb_den):
            try:
                tb_num, tb_den, fps = accessor.robust_probe_time_base_and_fps(video_path)
                video_db.update_video(vid, v_time_base_num=tb_num, v_time_base_den=tb_den)
            except Exception:
                traceback.print_exc()
                continue

        for f in fs:
            frame_id = f['id']
            if f.get('image_path') and os.path.exists(f['image_path']):
                # 已有文件，直接打包
                with open(f['image_path'], 'rb') as rf:
                    zf.writestr(f"frame_{frame_id}.jpg", rf.read())
                continue

            if f.get('frame_pts') is not None:
                t_sec = f['frame_pts'] * (tb_num / tb_den)
            elif f.get('pts_ms') is not None:
                t_sec = f['pts_ms'] / 1000.0
            else:
                continue

            try:
                data = accessor.extract_frame_bytes_by_sec(
                    video_path=video_path,
                    t_sec=t_sec,
                    quality=quality
                )
                zf.writestr(f"frame_{frame_id}.jpg", data)
            except Exception:
                traceback.print_exc()
                # 跳过失败
                continue

    zf.close()
    zip_buf.seek(0)
    return send_file(zip_buf, mimetype='application/zip', download_name=f"frames_{int(time.time())}.zip", as_attachment=True)


@frame_bp.route('/frames/<int:frame_id>/image', methods=['GET'])
def get_frame_image(frame_id):
    """
    获取帧图片：
    - 如 image_path 存在文件，直接返回；
    - 否则根据数据库中 frame_pts/pts_ms 与视频 time_base 进行按需抽帧。
    可选 query: quality=1..95 (默认85)
    """
    frame = video_db.get_frame(frame_id)
    
    if not frame:
        return jsonify({'success': False, 'message': '帧不存在'}), 404
    
    image_path = frame.get('image_path') or ''
    
    if image_path and os.path.exists(image_path):
        return send_file(image_path, mimetype='image/jpeg')

    # On-demand extraction
    video = video_db.get_video(frame['video_id'])
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    video_path = video['path']
    if not os.path.exists(video_path):
        return jsonify({'success': False, 'message': '视频文件不存在'}), 404

    quality = max(1, min(95, int(request.args.get('quality', 85))))

    accessor = FFmpegAccessor()
    tb_num = video.get('v_time_base_num')
    tb_den = video.get('v_time_base_den')
    if not (tb_num and tb_den):
        try:
            tb_num, tb_den, fps = accessor.robust_probe_time_base_and_fps(video_path)
            video_db.update_video(video['id'], v_time_base_num=tb_num, v_time_base_den=tb_den)
        except Exception as e:
            traceback.print_exc()
            return jsonify({'success': False, 'message': f'探测视频元数据失败: {e}'}), 500

    frame_pts = frame.get('frame_pts')
    if frame_pts is not None:
        t_sec = frame_pts * (tb_num / tb_den)
    else:
        pts_ms = frame.get('pts_ms')
        if pts_ms is None:
            return jsonify({'success': False, 'message': '缺少帧时间信息（frame_pts/pts_ms）'}), 400
        t_sec = pts_ms / 1000.0

    try:
        data = accessor.extract_frame_bytes_by_sec(
            video_path=video_path,
            t_sec=t_sec,
            quality=quality
        )
        return send_file(BytesIO(data), mimetype='image/jpeg')
    except Exception as e:
        traceback.print_exc()
        # 尝试基于 seed_video_id 的参数集修复（仅 H.264）
        seed_id = request.args.get('seed_video_id', type=int)
        if seed_id:
            seed = video_db.get_video(seed_id)
            if seed and os.path.exists(seed['path']):
                try:
                    data = accessor.extract_frame_bytes_by_sec_with_seed(
                        broken_video_path=video_path,
                        t_sec=t_sec,
                        seed_video_path=seed['path'],
                        assumed_fps=25,
                        quality=quality
                    )
                    return send_file(BytesIO(data), mimetype='image/jpeg')
                except Exception as e2:
                    traceback.print_exc()
                    return jsonify({'success': False, 'message': f'按需抽帧失败(含seed修复): {e2}'}), 500
        return jsonify({'success': False, 'message': f'按需抽帧失败: {e}'}), 500


@frame_bp.route('/frames/statistics', methods=['GET'])
def get_frame_statistics():
    """
    获取帧数据统计信息（按查询条件）
    
    Query参数: 与 /frames/query 相同
    
    返回:
        按天气、位置、时段、异常等维度的统计分布
    """
    params = {
        'start_time': request.args.get('start_time'),
        'end_time': request.args.get('end_time'),
        'train_no': request.args.get('train_no'),
        'route_section': request.args.get('route_section'),
        'weather': request.args.get('weather'),
        'location': request.args.get('location'),
        'time_period': request.args.get('time_period'),
        'min_speed': request.args.get('min_speed', type=float),
        'max_speed': request.args.get('max_speed', type=float),
        'limit': 10000,  # 统计时获取更多数据
        'offset': 0
    }
    
    # 移除None值的参数
    params = {k: v for k, v in params.items() if v is not None}
    
    frames = video_db.query_frames(**params)
    
    # 统计各维度分布
    weather_dist = {}
    location_dist = {}
    time_period_dist = {}
    anomaly_dist = {}
    speed_ranges = {'0-50': 0, '50-100': 0, '100-200': 0, '200-300': 0, '300+': 0}
    
    for frame in frames:
        # 天气分布
        weather = frame.get('label_weather')
        if weather:
            weather_dist[weather] = weather_dist.get(weather, 0) + 1
        
        # 位置分布
        location = frame.get('label_location')
        if location:
            location_dist[location] = location_dist.get(location, 0) + 1
        
        # 时段分布
        time_period = frame.get('label_time_period')
        if time_period:
            time_period_dist[time_period] = time_period_dist.get(time_period, 0) + 1
        
        # 异常分布
        anomaly = frame.get('label_anomaly')
        if anomaly:
            anomaly_dist[anomaly] = anomaly_dist.get(anomaly, 0) + 1
        
        # 速度分布
        speed = frame.get('ocr_speed')
        if speed is not None:
            if speed < 50:
                speed_ranges['0-50'] += 1
            elif speed < 100:
                speed_ranges['50-100'] += 1
            elif speed < 200:
                speed_ranges['100-200'] += 1
            elif speed < 300:
                speed_ranges['200-300'] += 1
            else:
                speed_ranges['300+'] += 1
    
    return jsonify({
        'success': True,
        'total_frames': len(frames),
        'query_params': params,
        'distributions': {
            'weather': weather_dist,
            'location': location_dist,
            'time_period': time_period_dist,
            'anomaly': anomaly_dist,
            'speed_ranges': speed_ranges
        }
    })


@frame_bp.route('/frames/labels', methods=['GET'])
def get_available_labels():
    """获取所有可用的标签类别"""
    from services.video_classifier_service import video_classifier_service
    
    categories = video_classifier_service.get_label_categories()
    
    return jsonify({
        'success': True,
        'data': categories
    })


@frame_bp.route('/frames/date-range', methods=['GET'])
def get_date_range():
    """
    获取数据的时间范围
    
    Query参数:
        train_no: 可选，按车次过滤
    """
    train_no = request.args.get('train_no')
    
    # 查询最早和最晚的时间
    frames = video_db.query_frames(
        train_no=train_no,
        limit=1,
        offset=0
    )
    
    if not frames:
        return jsonify({
            'success': True,
            'has_data': False,
            'message': '暂无数据'
        })
    
    # 获取第一条和最后一条
    first_frame = frames[0]
    
    # 反向查询最后一条
    import sqlite3
    conn = video_db.get_conn()
    cursor = conn.cursor()
    
    sql = 'SELECT ocr_time FROM frames WHERE ocr_time IS NOT NULL'
    params = []
    
    if train_no:
        sql += ' AND ocr_train_no = ?'
        params.append(train_no)
    
    sql += ' ORDER BY ocr_time DESC LIMIT 1'
    
    cursor.execute(sql, params)
    last_row = cursor.fetchone()
    conn.close()
    
    return jsonify({
        'success': True,
        'has_data': True,
        'data': {
            'earliest_time': first_frame.get('ocr_time'),
            'latest_time': last_row['ocr_time'] if last_row else first_frame.get('ocr_time')
        }
    })


if __name__ == '__main__':
    print("帧查询路由模块")
