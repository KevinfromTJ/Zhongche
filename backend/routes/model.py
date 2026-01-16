from flask import Blueprint, request, jsonify
import os
import sys
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.database import (
    get_db, get_dataset, get_dataset_images, get_dataset_labels
)
from config import (
    CLASSIFICATION_MODELS_DIR,
    DETECTION_MODELS_DIR, 
    SEGMENTATION_MODELS_DIR
)

model_bp = Blueprint('model', __name__)

# ========== 智能标注任务管理 ==========

@model_bp.route('/smart_annotation/check/<int:dataset_id>', methods=['GET'])
def check_smart_annotation_conditions(dataset_id):
    """
    检查是否满足智能标注启动条件
    
    条件：
    - 图像分类：每个标签下的图片达到10个
    - 物体检测/图像分割：未标图片数大于100且标注框数达到10个
    """
    dataset = get_dataset(dataset_id)
    if not dataset:
        return jsonify({'success': False, 'message': '数据集不存在'}), 404
    
    annotation_type = dataset['annotation_type']
    images = get_dataset_images(dataset_id)
    labels = get_dataset_labels(dataset_id)
    
    unannotated_count = sum(1 for img in images if not img['is_annotated'])
    annotated_count = dataset['annotated_count']
    
    can_start = False
    reason = ""
    
    if annotation_type == 'classification':
        # 图像分类：检查每个标签是否有足够的样本
        # 简化版：检查已标注数量是否足够
        if len(labels) == 0:
            can_start = False
            reason = "请先创建标签"
        elif annotated_count >= len(labels) * 10:
            can_start = True
            reason = f"已满足条件：已标注 {annotated_count} 张，标签数 {len(labels)}"
        else:
            required = len(labels) * 10
            can_start = False
            reason = f"需要至少标注 {required} 张图片（每个标签至少10张），当前已标注 {annotated_count} 张"
    
    elif annotation_type in ['segmentation', 'detection']:
        # 图像分割/物体检测：未标图片>20 且 已标注>=5
        if unannotated_count > 20 and annotated_count >= 5:
            can_start = True
            reason = f"已满足条件：未标注 {unannotated_count} 张，已标注 {annotated_count} 张"
        else:
            can_start = False
            reasons = []
            if unannotated_count <= 20:
                reasons.append(f"未标注图片需要超过20张（当前 {unannotated_count} 张）")
            if annotated_count < 5:
                reasons.append(f"已标注图片需要至少5张（当前 {annotated_count} 张）")
            reason = '；'.join(reasons)
    
    elif annotation_type == 'ocr':
        # OCR：暂时设置简单条件
        if unannotated_count > 0:
            can_start = True
            reason = f"可以启动智能标注，未标注图片 {unannotated_count} 张"
        else:
            can_start = False
            reason = "没有未标注的图片"
    
    return jsonify({
        'success': True,
        'data': {
            'can_start': can_start,
            'reason': reason,
            'annotation_type': annotation_type,
            'total_images': len(images),
            'annotated_count': annotated_count,
            'unannotated_count': unannotated_count,
            'label_count': len(labels)
        }
    })

@model_bp.route('/smart_annotation/tasks', methods=['GET'])
def list_smart_annotation_tasks():
    """获取所有智能标注任务"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.*, d.name as dataset_name, d.annotation_type
        FROM smart_annotation_tasks t
        JOIN datasets d ON t.dataset_id = d.id
        ORDER BY t.created_at DESC
    ''')
    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify({'success': True, 'data': tasks})

@model_bp.route('/smart_annotation/tasks', methods=['POST'])
def create_smart_annotation_task():
    """创建智能标注任务"""
    data = request.json
    dataset_id = data.get('dataset_id')
    task_type = data.get('task_type')  # active_learning / specify_model
    model_path = data.get('model_path', '')
    batch_size = data.get('batch_size', 20)  # 主动学习每轮预标注数量
    
    if not dataset_id or not task_type:
        return jsonify({'success': False, 'message': '缺少必要参数'}), 400
    
    if task_type not in ['active_learning', 'specify_model']:
        return jsonify({'success': False, 'message': '无效的任务类型'}), 400
    
    dataset = get_dataset(dataset_id)
    if not dataset:
        return jsonify({'success': False, 'message': '数据集不存在'}), 404
    
    # 检查标注类型（主动学习目前只支持检测）
    if task_type == 'active_learning' and dataset['annotation_type'] != 'detection':
        return jsonify({
            'success': False, 
            'message': '主动学习目前仅支持目标检测类型的数据集'
        }), 400
    
    # 检查启动条件
    if task_type == 'active_learning':
        # 主动学习：检查是否有标签
        labels = get_dataset_labels(dataset_id)
        if not labels:
            return jsonify({'success': False, 'message': '请先创建标签'}), 400
        
        # 验证batch_size范围
        batch_size = max(10, min(100, int(batch_size)))
        
    elif task_type == 'specify_model':
        # 指定模型只需要有未标注图片即可
        images = get_dataset_images(dataset_id, annotated=False)
        if len(images) == 0:
            return jsonify({'success': False, 'message': '没有未标注的图片'}), 400
    
    # 创建任务
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO smart_annotation_tasks 
        (dataset_id, task_type, model_path, status, batch_size, current_round, total_annotated, round_history)
        VALUES (?, ?, ?, 'pending', ?, 0, 0, '[]')
    ''', (dataset_id, task_type, model_path, batch_size))
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'message': '智能标注任务创建成功',
        'data': {'task_id': task_id}
    })

@model_bp.route('/smart_annotation/tasks/<int:task_id>', methods=['GET', 'DELETE'])
def handle_smart_annotation_task(task_id):
    """获取或删除单个智能标注任务"""
    conn = get_db()
    cursor = conn.cursor()
    
    if request.method == 'GET':
        # 获取任务详情
        cursor.execute('''
            SELECT t.*, d.name as dataset_name, d.annotation_type
            FROM smart_annotation_tasks t
            JOIN datasets d ON t.dataset_id = d.id
            WHERE t.id = ?
        ''', (task_id,))
        task = cursor.fetchone()
        conn.close()
        
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        return jsonify({'success': True, 'data': dict(task)})
    
    elif request.method == 'DELETE':
        # 删除任务
        cursor.execute('SELECT * FROM smart_annotation_tasks WHERE id = ?', (task_id,))
        task = cursor.fetchone()
        
        if not task:
            conn.close()
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        task = dict(task)
        
        # 如果任务正在运行，不允许删除
        if task['status'] == 'running':
            conn.close()
            return jsonify({'success': False, 'message': '任务正在运行中，无法删除'}), 400
        
        # 删除任务
        cursor.execute('DELETE FROM smart_annotation_tasks WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '任务已删除'})

@model_bp.route('/smart_annotation/tasks/<int:task_id>/start', methods=['POST'])
def start_smart_annotation_task(task_id):
    """
    启动智能标注任务
    - 指定模型：直接使用模型推理
    - 主动学习：调用主动学习接口
    """
    import threading
    from services.smart_annotation_service import run_smart_annotation
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取任务信息
    cursor.execute('SELECT * FROM smart_annotation_tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    
    if not task:
        conn.close()
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    
    task = dict(task)
    
    # 主动学习任务：转发到专用接口
    if task['task_type'] == 'active_learning':
        conn.close()
        # 调用主动学习启动接口
        from services.active_learning_service import run_active_learning_round
        
        if task['status'] in ['training', 'inferring']:
            return jsonify({'success': False, 'message': '任务正在进行中，请等待完成'}), 400
        
        # 检查是否有已标注图片（第一轮需要）
        dataset_id = task['dataset_id']
        labels = get_dataset_labels(dataset_id)
        if not labels:
            return jsonify({'success': False, 'message': '请先创建标签'}), 400
        
        annotated_images = get_dataset_images(dataset_id, annotated=True)
        current_round = task['current_round'] or 0
        
        if current_round == 0 and len(annotated_images) < 5:
            return jsonify({
                'success': False, 
                'message': f'首轮训练至少需要5张已标注图片，当前只有{len(annotated_images)}张'
            }), 400
        
        # 在后台线程中执行
        def run_active_learning():
            result = run_active_learning_round(task_id)
            print(f"主动学习任务 {task_id} 完成: {result}")
        
        thread = threading.Thread(target=run_active_learning)
        thread.daemon = True
        thread.start()
        
        next_round = current_round + 1
        return jsonify({
            'success': True,
            'message': f'第{next_round}轮主动学习已启动',
            'data': {
                'task_id': task_id,
                'task_type': 'active_learning',
                'round': next_round
            }
        })
    
    # 指定模型任务：原有逻辑
    if task['status'] != 'pending':
        conn.close()
        return jsonify({'success': False, 'message': f"任务状态为 {task['status']}，无法启动"}), 400
    
    # 检查是否有标签
    dataset_id = task['dataset_id']
    labels = get_dataset_labels(dataset_id)
    if not labels:
        conn.close()
        return jsonify({'success': False, 'message': '数据集没有标签，请先在在线标注页面创建标签'}), 400
    
    conn.close()
    
    # 在后台线程中执行推理
    def run_task():
        result = run_smart_annotation(task_id)
        print(f"智能标注任务 {task_id} 完成: {result}")
    
    thread = threading.Thread(target=run_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'message': '智能标注任务已启动，正在后台处理',
        'data': {
            'task_id': task_id,
            'task_type': task['task_type']
        }
    })
@model_bp.route('/smart_annotation/tasks/<int:task_id>/status', methods=['GET'])
def get_smart_annotation_task_status(task_id):
    """获取智能标注任务的状态"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT t.*, d.name as dataset_name, d.annotation_type,
               d.image_count, d.annotated_count
        FROM smart_annotation_tasks t
        JOIN datasets d ON t.dataset_id = d.id
        WHERE t.id = ?
    ''', (task_id,))
    task = cursor.fetchone()
    conn.close()
    
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    
    return jsonify({'success': True, 'data': dict(task)})

# ========== 模型列表（用于指定模型功能） ==========

@model_bp.route('/models/list', methods=['GET'])
def list_available_models():
    """
    获取可用的模型列表
    
    Query参数:
        annotation_type: 标注类型 (classification/detection/segmentation)
    """
    annotation_type = request.args.get('annotation_type', None)
    
    models = []
    
    # 根据标注类型返回对应目录的模型
    if annotation_type == 'classification':
        model_dir = CLASSIFICATION_MODELS_DIR
        model_type = 'classification'
    elif annotation_type == 'detection':
        model_dir = DETECTION_MODELS_DIR
        model_type = 'detection'
    elif annotation_type == 'segmentation':
        # 分割任务使用检测模型（先检测后SAM分割）
        model_dir = DETECTION_MODELS_DIR
        model_type = 'segmentation'
    else:
        # 如果没有指定类型，返回所有模型
        all_models = []
        
        # 分类模型
        if os.path.exists(CLASSIFICATION_MODELS_DIR):
            for filename in os.listdir(CLASSIFICATION_MODELS_DIR):
                if filename.endswith('.pth') or filename.endswith('.pt'):
                    all_models.append({
                        'name': f'[分类] {filename}',
                        'path': os.path.join(CLASSIFICATION_MODELS_DIR, filename),
                        'type': 'classification'
                    })
        
        # 检测模型
        if os.path.exists(DETECTION_MODELS_DIR):
            for filename in os.listdir(DETECTION_MODELS_DIR):
                if filename.endswith('.pth') or filename.endswith('.pt'):
                    all_models.append({
                        'name': f'[检测] {filename}',
                        'path': os.path.join(DETECTION_MODELS_DIR, filename),
                        'type': 'detection'
                    })
        
        return jsonify({'success': True, 'data': all_models})
    
    # 扫描指定目录
    if os.path.exists(model_dir):
        for filename in os.listdir(model_dir):
            if filename.endswith('.pth') or filename.endswith('.pt'):
                models.append({
                    'name': filename,
                    'path': os.path.join(model_dir, filename),
                    'type': model_type
                })
    
    return jsonify({'success': True, 'data': models})


# ==================== 主动学习专用接口 ====================

@model_bp.route('/active_learning/tasks/<int:task_id>/start_round', methods=['POST'])
def start_active_learning_round(task_id):
    """
    启动一轮主动学习（训练 + 推理）
    """
    import threading
    from services.active_learning_service import run_active_learning_round
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取任务信息
    cursor.execute('SELECT * FROM smart_annotation_tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    
    if not task:
        conn.close()
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    
    task = dict(task)
    
    if task['task_type'] != 'active_learning':
        conn.close()
        return jsonify({'success': False, 'message': '该任务不是主动学习类型'}), 400
    
    if task['status'] in ['training', 'inferring', 'running']:
        conn.close()
        return jsonify({'success': False, 'message': '任务正在进行中，请等待完成'}), 400
    
    # 检查是否有已标注图片（第一轮需要）
    dataset_id = task['dataset_id']
    labels = get_dataset_labels(dataset_id)
    if not labels:
        conn.close()
        return jsonify({'success': False, 'message': '请先创建标签'}), 400
    
    annotated_images = get_dataset_images(dataset_id, annotated=True)
    current_round = task['current_round'] or 0
    
    if current_round == 0 and len(annotated_images) < 5:
        conn.close()
        return jsonify({
            'success': False, 
            'message': f'首轮训练至少需要5张已标注图片，当前只有{len(annotated_images)}张'
        }), 400
    
    conn.close()
    
    # 在后台线程中执行
    def run_task():
        result = run_active_learning_round(task_id)
        print(f"主动学习任务 {task_id} 完成: {result}")
    
    thread = threading.Thread(target=run_task)
    thread.daemon = True
    thread.start()
    
    next_round = current_round + 1
    return jsonify({
        'success': True,
        'message': f'第{next_round}轮主动学习已启动',
        'data': {
            'task_id': task_id,
            'round': next_round
        }
    })


@model_bp.route('/active_learning/tasks/<int:task_id>/save_model', methods=['POST'])
def save_active_learning_model(task_id):
    """
    保存最终模型到检测模型目录
    """
    from services.active_learning_service import save_final_model, cleanup_task_checkpoints
    
    data = request.json or {}
    model_name = data.get('model_name')  # 可选的自定义名称
    
    try:
        saved_path = save_final_model(task_id, model_name)
        
        # 清理中间checkpoint
        cleanup_task_checkpoints(task_id, keep_final=False)
        
        return jsonify({
            'success': True,
            'message': '模型保存成功',
            'data': {
                'model_path': saved_path
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@model_bp.route('/active_learning/tasks/<int:task_id>/status', methods=['GET'])
def get_active_learning_status(task_id):
    """
    获取主动学习任务的详细状态
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT t.*, d.name as dataset_name, d.annotation_type,
               d.image_count, d.annotated_count
        FROM smart_annotation_tasks t
        JOIN datasets d ON t.dataset_id = d.id
        WHERE t.id = ?
    ''', (task_id,))
    task = cursor.fetchone()
    conn.close()
    
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    
    task_dict = dict(task)
    
    # 解析轮次历史
    if task_dict.get('round_history'):
        task_dict['round_history'] = json.loads(task_dict['round_history'])
    else:
        task_dict['round_history'] = []
    
    # 计算未标注图片数
    unannotated_count = task_dict['image_count'] - task_dict['annotated_count']
    task_dict['unannotated_count'] = unannotated_count
    
    return jsonify({'success': True, 'data': task_dict})