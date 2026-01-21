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
from PIL import Image

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.video_database import video_db
from services.frame_accessor import FFmpegAccessor
from services.video_frame_extractor import VideoFrameExtractor
from services.video_ocr_service import video_ocr_service
from services.video_classifier_service import video_classifier_service
from config import DEFAULT_MAX_FRAMES, DEFAULT_SAMPLE_RATE

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


@frame_bp.route('/frames/advanced-query', methods=['POST'])
def advanced_query_and_extract():
    """
    全面的帧查询与抽取功能
    
    支持功能：
    1. 传入视频路径列表，自动处理未入库的视频（注册、抽帧、AI处理）
    2. 支持复杂的查询条件组合（AND/OR/NOT逻辑）
    3. 如果视频列表为空，在所有已入库视频中查询
    4. 返回符合条件的帧信息
    5. 可选：即时抽取帧图片到ZIP包
    
    POST JSON:
    {
        "video_paths": ["path/to/video1.mp4", "path/to/video2.mp4"],  // 可选，空数组表示所有视频
        "conditions": {  // 查询条件
            "$and": [
                {"ocr_train_no": "G4926"},
                {"$or": [{"label_weather": "晴天"}, {"label_weather": "阴天"}]},
                {"ocr_speed": {"$gte": 200, "$lte": 300}}
            ]
        },
        "limit": 100,  // 返回数量限制，默认100
        "offset": 0,   // 偏移量，默认0
        "extract_images": true,  // 是否返回图片ZIP包，默认false
        "image_quality": 85,  // 图片质量，默认85
        "auto_process": true,  // 对未入库视频是否自动处理，默认true
        "max_frames": 1000,  // 抽帧数量，默认使用配置
        "sample_rate": 100  // 采样率，默认使用配置
    }
    
    条件语法示例：
    1. 简单AND: {"ocr_train_no": "G4926", "label_weather": "晴天"}
    2. OR逻辑: {"$or": [{"label_weather": "晴天"}, {"label_weather": "阴天"}]}
    3. NOT逻辑: {"$not": {"label_location": "隧道内"}}
    4. 范围查询: {"ocr_speed": {"$gte": 200, "$lte": 300}}
    5. 模糊匹配: {"ocr_route_section": {"$like": "广州"}}
    6. 不等于: {"label_weather": {"$ne": "雨天"}}
    
    Returns:
        如果 extract_images=false: 返回JSON格式的帧信息列表
        如果 extract_images=true: 返回ZIP文件包含所有符合条件的帧图片
    """
    try:
        data = request.json or {}
        
        # 解析参数
        video_paths = data.get('video_paths', [])
        conditions = data.get('conditions', {})
        limit = data.get('limit', 100)
        offset = data.get('offset', 0)
        extract_images = data.get('extract_images', False)
        image_quality = data.get('image_quality', 85)
        auto_process = data.get('auto_process', True)
        max_frames = data.get('max_frames', DEFAULT_MAX_FRAMES)
        sample_rate = data.get('sample_rate', DEFAULT_SAMPLE_RATE)
        
        print(f"\n📊 高级查询请求:")
        print(f"   视频路径数量: {len(video_paths)}")
        print(f"   查询条件: {conditions}")
        print(f"   返回限制: {limit}, 偏移: {offset}")
        print(f"   抽取图片: {extract_images}")
        
        # 步骤1: 处理视频路径列表
        video_ids = []
        
        if video_paths:
            print(f"\n🎬 处理 {len(video_paths)} 个视频...")
            frame_extractor = VideoFrameExtractor()
            
            for i, video_path in enumerate(video_paths, 1):
                print(f"\n   [{i}/{len(video_paths)}] 处理: {video_path}")
                
                if not os.path.exists(video_path):
                    print(f"      ⚠️  视频文件不存在，跳过")
                    continue
                
                # 检查是否已入库
                video = video_db.get_video_by_path(video_path)
                
                if video:
                    video_id = video['id']
                    print(f"      ✓ 视频已入库，ID={video_id}")
                    
                    # 检查是否已抽帧和AI处理
                    if auto_process and video['status'] != 'extracted':
                        print(f"      → 视频未完成抽帧，开始抽帧...")
                        result = frame_extractor.extract_frames(
                            video_path=video_path,
                            video_id=video_id,
                            max_frames=max_frames,
                            sample_rate=sample_rate,
                            force_reprocess=False
                        )
                        if result['success']:
                            print(f"      ✓ 抽帧完成: {result.get('extracted_frames', 0)} 帧")
                    
                    # 检查AI处理状态
                    frames = video_db.list_frames(video_id=video_id, ai_processed=False, limit=1)
                    if auto_process and frames:
                        print(f"      → 存在未处理帧，开始AI处理...")
                        # OCR处理
                        unprocessed = video_db.list_frames(video_id=video_id, ai_processed=False, limit=10000)
                        if unprocessed:
                            print(f"         OCR处理中...")
                            for frame in unprocessed:
                                if os.path.exists(frame['image_path']):
                                    ocr_result = video_ocr_service.extract_text(frame['image_path'], frame['frame_idx'])
                                    video_db.update_frame_ocr(frame['id'], ocr_result)
                        
                        # 分类处理
                        print(f"         分类处理中...")
                        unprocessed = video_db.list_frames(video_id=video_id, ai_processed=False, limit=10000)
                        if unprocessed:
                            image_paths = [f['image_path'] for f in unprocessed if os.path.exists(f['image_path'])]
                            if image_paths:
                                labels = video_classifier_service.batch_classify(image_paths)
                                for frame, label_info in zip(unprocessed, labels):
                                    video_db.update_frame_classification(frame['id'], label_info)
                        
                        print(f"      ✓ AI处理完成")
                else:
                    # 新视频，需要注册并处理
                    if not auto_process:
                        print(f"      ⚠️  视频未入库且auto_process=False，跳过")
                        continue
                    
                    print(f"      → 视频未入库，开始注册...")
                    video_id = video_db.add_video(
                        path=video_path,
                        filename=os.path.basename(video_path),
                        status='pending'
                    )
                    print(f"      ✓ 注册成功，ID={video_id}")
                    
                    # 抽帧
                    print(f"      → 开始抽帧...")
                    result = frame_extractor.extract_frames(
                        video_path=video_path,
                        video_id=video_id,
                        max_frames=max_frames,
                        sample_rate=sample_rate
                    )
                    if not result['success']:
                        print(f"      ❌ 抽帧失败: {result.get('error')}")
                        continue
                    print(f"      ✓ 抽帧完成: {result.get('extracted_frames', 0)} 帧")
                    
                    # AI处理
                    print(f"      → 开始AI处理...")
                    frames = video_db.list_frames(video_id=video_id, limit=10000)
                    
                    # OCR
                    print(f"         OCR处理中...")
                    for frame in frames:
                        if os.path.exists(frame['image_path']):
                            ocr_result = video_ocr_service.extract_text(frame['image_path'], frame['frame_idx'])
                            video_db.update_frame_ocr(frame['id'], ocr_result)
                    
                    # 分类
                    print(f"         分类处理中...")
                    image_paths = [f['image_path'] for f in frames if os.path.exists(f['image_path'])]
                    if image_paths:
                        labels = video_classifier_service.batch_classify(image_paths)
                        for frame, label_info in zip(frames, labels):
                            video_db.update_frame_classification(frame['id'], label_info)
                    
                    print(f"      ✓ AI处理完成")
                
                video_ids.append(video_id)
            
            print(f"\n✓ 视频处理完成，共 {len(video_ids)} 个视频")
        else:
            print(f"\n📂 未指定视频路径，将在所有已入库视频中查询")
            video_ids = None  # None表示不限制视频范围
        
        # 步骤2: 执行高级查询
        print(f"\n🔍 执行查询...")
        frames = video_db.advanced_query_frames(
            conditions=conditions,
            video_ids=video_ids,
            limit=limit,
            offset=offset
        )
        
        print(f"✓ 查询完成，找到 {len(frames)} 帧")
        
        # 步骤3: 返回结果
        if not extract_images:
            # 仅返回JSON信息
            return jsonify({
                'success': True,
                'count': len(frames),
                'data': frames,
                'processed_videos': len(video_ids) if video_ids else 0
            })
        else:
            # 抽取图片并返回ZIP
            print(f"\n📦 开始打包图片...")
            
            zip_buffer = BytesIO()
            accessor = FFmpegAccessor()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for i, frame in enumerate(frames, 1):
                    try:
                        # 优先使用已存在的图片
                        if frame.get('image_path') and os.path.exists(frame['image_path']):
                            zip_file.write(
                                frame['image_path'],
                                f"frame_{frame['id']:06d}_{frame['frame_idx']:08d}.jpg"
                            )
                        else:
                            # 即时抽帧
                            video_path = frame.get('video_path')
                            if video_path and os.path.exists(video_path):
                                # 计算时间位置（秒）
                                video = video_db.get_video(frame['video_id'])
                                fps = video.get('fps', 25)
                                t_sec = frame['frame_idx'] / fps if fps > 0 else frame['pts_ms'] / 1000.0
                                
                                # 抽帧
                                img_bytes = accessor.extract_frame_bytes_by_sec(
                                    video_path, t_sec, quality=image_quality
                                )
                                
                                # 添加到ZIP
                                zip_file.writestr(
                                    f"frame_{frame['id']:06d}_{frame['frame_idx']:08d}.jpg",
                                    img_bytes
                                )
                        
                        if i % 10 == 0:
                            print(f"   已打包 {i}/{len(frames)} 帧...")
                    
                    except Exception as e:
                        print(f"   ⚠️  帧 {frame['id']} 处理失败: {e}")
                        continue
            
            zip_buffer.seek(0)
            print(f"✓ 打包完成")
            
            return send_file(
                zip_buffer,
                mimetype='application/zip',
                as_attachment=True,
                download_name=f'frames_{int(time.time())}.zip'
            )
    
    except Exception as e:
        print(f"❌ 高级查询失败: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'查询失败: {str(e)}'
        }), 500


if __name__ == '__main__':
    print("帧查询路由模块")
