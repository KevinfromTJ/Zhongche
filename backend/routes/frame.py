"""
帧查询路由
提供按时间、区间、类别等条件查询帧数据的API
"""
from flask import Blueprint, request, jsonify, send_file
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.video_database import video_db

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


@frame_bp.route('/frames/<int:frame_id>/image', methods=['GET'])
def get_frame_image(frame_id):
    """获取帧图片文件"""
    frame = video_db.get_frame(frame_id)
    
    if not frame:
        return jsonify({'success': False, 'message': '帧不存在'}), 404
    
    image_path = frame['image_path']
    
    if not os.path.exists(image_path):
        return jsonify({'success': False, 'message': '图片文件不存在'}), 404
    
    return send_file(image_path, mimetype='image/jpeg')


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
