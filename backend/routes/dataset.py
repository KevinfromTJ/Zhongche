from flask import Blueprint, request, jsonify, send_file
import os
import zipfile
import tempfile
from werkzeug.utils import secure_filename
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.database import (
    create_dataset, get_all_datasets, get_dataset, delete_dataset,
    add_image, get_dataset_images, get_image,
    add_label, get_dataset_labels, delete_label, update_label
)
from config import DATASETS_DIR, ANNOTATIONS_DIR

dataset_bp = Blueprint('dataset', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ========== 数据集CRUD ==========

@dataset_bp.route('/datasets', methods=['GET'])
def list_datasets():
    """获取所有数据集列表"""
    datasets = get_all_datasets()
    return jsonify({'success': True, 'data': datasets})

@dataset_bp.route('/datasets', methods=['POST'])
def create_new_dataset():
    """创建新数据集"""
    data = request.json
    
    name = data.get('name')
    data_type = data.get('data_type', 'image')  # image/video
    annotation_type = data.get('annotation_type')  # classification/segmentation/ocr
    template = data.get('template', 'single_label')
    
    if not name or not annotation_type:
        return jsonify({'success': False, 'message': '缺少必要参数'}), 400
    
    dataset_id = create_dataset(name, data_type, annotation_type, template)

    # 如果是分类数据集，自动创建8个预设标签
    if annotation_type == 'classification':
        CLASSIFICATION_LABELS = [
            {"name": "穿过高架桥", "color": "#FF6B6B"},
            {"name": "阴天", "color": "#4ECDC4"},
            {"name": "晴天无太阳", "color": "#FFE66D"},
            {"name": "镜头雨滴", "color": "#95E1D3"},
            {"name": "黑夜", "color": "#2C3E50"},
            {"name": "隧道内", "color": "#A8E6CF"},
            {"name": "暴雨", "color": "#5DADE2"},
            {"name": "太阳光直射弓头", "color": "#F39C12"}
        ]
        for label_info in CLASSIFICATION_LABELS:
            add_label(dataset_id, label_info['name'], label_info['color'])
    
    return jsonify({
        'success': True, 
        'message': '数据集创建成功',
        'data': {'id': dataset_id}
    })

@dataset_bp.route('/datasets/<int:dataset_id>', methods=['GET'])
def get_dataset_info(dataset_id):
    """获取单个数据集详情"""
    dataset = get_dataset(dataset_id)
    if not dataset:
        return jsonify({'success': False, 'message': '数据集不存在'}), 404
    
    # 获取标签列表
    labels = get_dataset_labels(dataset_id)
    dataset['labels'] = labels
    
    return jsonify({'success': True, 'data': dataset})

@dataset_bp.route('/datasets/<int:dataset_id>', methods=['DELETE'])
def remove_dataset(dataset_id):
    """删除数据集"""
    dataset = get_dataset(dataset_id)
    if not dataset:
        return jsonify({'success': False, 'message': '数据集不存在'}), 404
    
    delete_dataset(dataset_id)
    
    # 删除对应的文件目录
    import shutil
    dataset_dir = os.path.join(DATASETS_DIR, str(dataset_id))
    annotation_dir = os.path.join(ANNOTATIONS_DIR, str(dataset_id))
    if os.path.exists(dataset_dir):
        shutil.rmtree(dataset_dir)
    if os.path.exists(annotation_dir):
        shutil.rmtree(annotation_dir)
    
    return jsonify({'success': True, 'message': '数据集删除成功'})

# ========== 图片导入 ==========

@dataset_bp.route('/datasets/<int:dataset_id>/import', methods=['POST'])
def import_images(dataset_id):
    """导入图片到数据集"""
    dataset = get_dataset(dataset_id)
    if not dataset:
        return jsonify({'success': False, 'message': '数据集不存在'}), 404
    
    if 'files' not in request.files:
        return jsonify({'success': False, 'message': '没有上传文件'}), 400
    
    files = request.files.getlist('files')
    dataset_dir = os.path.join(DATASETS_DIR, str(dataset_id))
    
    imported_count = 0
    
    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            
            # 处理压缩包
            if filename.endswith('.zip'):
                with tempfile.TemporaryDirectory() as temp_dir:
                    zip_path = os.path.join(temp_dir, filename)
                    file.save(zip_path)
                    
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                    
                    # 遍历解压后的文件
                    for root, dirs, extracted_files in os.walk(temp_dir):
                        for extracted_file in extracted_files:
                            if allowed_file(extracted_file):
                                src_path = os.path.join(root, extracted_file)
                                dst_filename = secure_filename(extracted_file)
                                dst_path = os.path.join(dataset_dir, dst_filename)
                                
                                # 避免重名
                                counter = 1
                                while os.path.exists(dst_path):
                                    name, ext = os.path.splitext(dst_filename)
                                    dst_filename = f"{name}_{counter}{ext}"
                                    dst_path = os.path.join(dataset_dir, dst_filename)
                                    counter += 1
                                
                                import shutil
                                shutil.copy2(src_path, dst_path)
                                add_image(dataset_id, dst_filename, dst_path)
                                imported_count += 1
            
            # 处理单张图片
            elif allowed_file(filename):
                filepath = os.path.join(dataset_dir, filename)
                
                # 避免重名
                counter = 1
                while os.path.exists(filepath):
                    name, ext = os.path.splitext(filename)
                    filename = f"{name}_{counter}{ext}"
                    filepath = os.path.join(dataset_dir, filename)
                    counter += 1
                
                file.save(filepath)
                add_image(dataset_id, filename, filepath)
                imported_count += 1
    
    return jsonify({
        'success': True,
        'message': f'成功导入 {imported_count} 张图片',
        'data': {'imported_count': imported_count}
    })

# ========== 图片列表 ==========

@dataset_bp.route('/datasets/<int:dataset_id>/images', methods=['GET'])
def list_images(dataset_id):
    """获取数据集的图片列表"""
    dataset = get_dataset(dataset_id)
    if not dataset:
        return jsonify({'success': False, 'message': '数据集不存在'}), 404
    
    annotated = request.args.get('annotated')
    if annotated == 'true':
        images = get_dataset_images(dataset_id, annotated=True)
    elif annotated == 'false':
        images = get_dataset_images(dataset_id, annotated=False)
    else:
        images = get_dataset_images(dataset_id)
    
    return jsonify({'success': True, 'data': images})

@dataset_bp.route('/images/<int:image_id>/file', methods=['GET'])
def get_image_file(image_id):
    """获取图片文件"""
    image = get_image(image_id)
    if not image:
        return jsonify({'success': False, 'message': '图片不存在'}), 404
    
    return send_file(image['filepath'])

# ========== 标签管理 ==========

@dataset_bp.route('/datasets/<int:dataset_id>/labels', methods=['GET'])
def list_labels(dataset_id):
    """获取数据集的标签列表"""
    labels = get_dataset_labels(dataset_id)
    return jsonify({'success': True, 'data': labels})

@dataset_bp.route('/datasets/<int:dataset_id>/labels', methods=['POST'])
def create_label(dataset_id):
    """创建新标签"""
    data = request.json
    name = data.get('name')
    color = data.get('color', '#FF0000')
    
    if not name:
        return jsonify({'success': False, 'message': '标签名称不能为空'}), 400
    
    label_id = add_label(dataset_id, name, color)
    
    return jsonify({
        'success': True,
        'message': '标签创建成功',
        'data': {'id': label_id}
    })

@dataset_bp.route('/datasets/<int:dataset_id>/labels/batch', methods=['POST'])
def batch_create_labels(dataset_id):
    """批量创建标签"""
    data = request.json
    label_names = data.get('labels', [])  # 期望是字符串数组
    
    if not label_names or not isinstance(label_names, list):
        return jsonify({'success': False, 'message': '请提供标签名称列表'}), 400
    
    # 预设颜色池
    PRESET_COLORS = [
        '#FF6B6B', '#4ECDC4', '#FFE66D', '#95E1D3',
        '#2C3E50', '#A8E6CF', '#5DADE2', '#F39C12',
        '#9B59B6', '#E74C3C', '#1ABC9C', '#F1C40F',
        '#34495E', '#E67E22', '#16A085', '#D35400'
    ]
    
    # 获取现有标签
    existing_labels = get_dataset_labels(dataset_id)
    existing_names = [label['name'] for label in existing_labels]
    
    success_count = 0
    skip_count = 0
    created_ids = []
    
    for i, name in enumerate(label_names):
        name = name.strip()
        if not name:
            continue
        
        # 检查重复
        if name in existing_names:
            skip_count += 1
            continue
        
        # 循环选择颜色
        color = PRESET_COLORS[success_count % len(PRESET_COLORS)]
        
        # 创建标签
        label_id = add_label(dataset_id, name, color)
        created_ids.append(label_id)
        existing_names.append(name)
        success_count += 1
    
    return jsonify({
        'success': True,
        'message': f'成功导入 {success_count} 个标签' + (f'，跳过 {skip_count} 个重复标签' if skip_count > 0 else ''),
        'data': {
            'success_count': success_count,
            'skip_count': skip_count,
            'created_ids': created_ids
        }
    })

@dataset_bp.route('/labels/<int:label_id>/usage', methods=['GET'])
def get_label_usage_info(label_id):
    """查询标签的使用情况"""
    from models.database import get_label_usage
    
    result = get_label_usage(label_id)
    
    if result['success']:
        return jsonify({
            'success': True,
            'data': {
                'label_name': result['label_name'],
                'used_count': result['used_count']
            }
        })
    else:
        return jsonify({
            'success': False,
            'message': result['message']
        }), 404


@dataset_bp.route('/labels/<int:label_id>', methods=['PUT'])
def update_label_route(label_id):
    """更新标签"""
    data = request.get_json()
    name = data.get('name')
    color = data.get('color')
    
    if not name and not color:
        return jsonify({'success': False, 'message': '请提供要更新的名称或颜色'})
    
    result = update_label(label_id, name=name, color=color)
    return jsonify(result)



@dataset_bp.route('/labels/<int:label_id>', methods=['DELETE'])
def remove_label(label_id):
    """删除标签（级联删除相关标注）"""
    from models.database import delete_label_cascade
    
    result = delete_label_cascade(label_id)
    
    if result['success']:
        return jsonify({
            'success': True,
            'message': result['message'],
            'affected_images': result['affected_images']
        })
    else:
        return jsonify({
            'success': False,
            'message': result['message']
        }), 404
