from flask import Blueprint, request, jsonify
import os
import sys
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.database import (
    get_dataset, get_image, get_dataset_images,
    save_annotation, get_annotation
)
from config import ANNOTATIONS_DIR

annotation_bp = Blueprint('annotation', __name__)

# ========== 标注保存与获取 ==========

@annotation_bp.route('/annotations/<int:image_id>', methods=['GET'])
def get_image_annotation(image_id):
    """获取图片的标注结果"""
    annotation = get_annotation(image_id)
    
    if annotation:
        return jsonify({'success': True, 'data': annotation})
    else:
        return jsonify({'success': True, 'data': None, 'message': '暂无标注'})

@annotation_bp.route('/annotations/<int:image_id>', methods=['POST'])
def save_image_annotation(image_id):
    """保存图片的标注结果"""
    image = get_image(image_id)
    if not image:
        return jsonify({'success': False, 'message': '图片不存在'}), 404
    
    data = request.json
    annotation_data = data.get('annotation_data')
    
    if not annotation_data:
        return jsonify({'success': False, 'message': '标注数据不能为空'}), 400
    
    save_annotation(image_id, image['dataset_id'], annotation_data)
    
    # 同时保存到json文件（方便导出）
    annotation_dir = os.path.join(ANNOTATIONS_DIR, str(image['dataset_id']))
    json_path = os.path.join(annotation_dir, f"{image_id}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(annotation_data, f, ensure_ascii=False, indent=2)
    
    return jsonify({'success': True, 'message': '标注保存成功'})

# ========== SAM分割接口 ==========

@annotation_bp.route('/sam/predict_points', methods=['POST'])
def sam_predict_points():
    """使用点提示进行SAM分割"""
    data = request.json
    image_id = data.get('image_id')
    points = data.get('points')  # [[x1, y1], [x2, y2], ...]
    labels = data.get('labels')  # [1, 0, 1, ...]  1=正点, 0=负点
    
    if not image_id or not points or not labels:
        return jsonify({'success': False, 'message': '缺少必要参数'}), 400
    
    image = get_image(image_id)
    if not image:
        return jsonify({'success': False, 'message': '图片不存在'}), 404
    
    try:
        from services.sam_service import predict_with_points
        mask, score, polygon = predict_with_points(image['filepath'], points, labels)
        
        if polygon is None:
            return jsonify({'success': False, 'message': 'SAM预测失败'}), 500
        
        return jsonify({
            'success': True,
            'data': {
                'polygon': polygon,
                'score': score
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'SAM预测错误: {str(e)}'}), 500

@annotation_bp.route('/sam/predict_box', methods=['POST'])
def sam_predict_box():
    """使用矩形框提示进行SAM分割"""
    data = request.json
    image_id = data.get('image_id')
    box = data.get('box')  # [x1, y1, x2, y2]
    
    if not image_id or not box:
        return jsonify({'success': False, 'message': '缺少必要参数'}), 400
    
    image = get_image(image_id)
    if not image:
        return jsonify({'success': False, 'message': '图片不存在'}), 404
    
    try:
        from services.sam_service import predict_with_box
        mask, score, polygon = predict_with_box(image['filepath'], box)
        
        if polygon is None:
            return jsonify({'success': False, 'message': 'SAM预测失败'}), 500
        
        return jsonify({
            'success': True,
            'data': {
                'polygon': polygon,
                'score': score
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'SAM预测错误: {str(e)}'}), 500

# ========== 图像分类接口 ==========

@annotation_bp.route('/classify/<int:image_id>', methods=['GET'])
def classify_image(image_id):
    """对单张图片进行分类预测"""
    image = get_image(image_id)
    if not image:
        return jsonify({'success': False, 'message': '图片不存在'}), 404
    
    try:
        from services.classifier_service import predict_image
        class_idx, class_name, confidence, all_probs = predict_image(image['filepath'])
        
        return jsonify({
            'success': True,
            'data': {
                'class_idx': class_idx,
                'class_name': class_name,
                'confidence': confidence,
                'all_probs': all_probs
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'分类预测错误: {str(e)}'}), 500

@annotation_bp.route('/classify/batch', methods=['POST'])
def classify_batch():
    """批量分类预测"""
    data = request.json
    image_ids = data.get('image_ids', [])
    
    if not image_ids:
        return jsonify({'success': False, 'message': '图片ID列表不能为空'}), 400
    
    # 获取图片路径
    image_paths = []
    image_id_map = {}
    for img_id in image_ids:
        image = get_image(img_id)
        if image:
            image_paths.append(image['filepath'])
            image_id_map[image['filepath']] = img_id
    
    try:
        from services.classifier_service import predict_batch
        results = predict_batch(image_paths)
        
        # 转换结果格式，使用image_id作为key
        formatted_results = {}
        for result in results:
            path = result['image_path']
            img_id = image_id_map.get(path)
            if img_id:
                formatted_results[img_id] = result
        
        return jsonify({
            'success': True,
            'data': formatted_results
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'批量分类错误: {str(e)}'}), 500

# ========== OCR识别接口 ==========

@annotation_bp.route('/ocr/<int:image_id>', methods=['GET'])
def ocr_recognize(image_id):
    """对单张图片进行OCR识别"""
    image = get_image(image_id)
    if not image:
        return jsonify({'success': False, 'message': '图片不存在'}), 404
    
    try:
        from services.ocr_service import recognize_text
        items = recognize_text(image['filepath'])
        
        return jsonify({
            'success': True,
            'data': {
                'items': items
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'OCR识别错误: {str(e)}'}), 500

# ========== 导出标注结果 ==========

@annotation_bp.route('/datasets/<int:dataset_id>/export', methods=['GET'])
def export_annotations(dataset_id):
    """导出数据集的所有标注结果"""
    dataset = get_dataset(dataset_id)
    if not dataset:
        return jsonify({'success': False, 'message': '数据集不存在'}), 404
    
    images = get_dataset_images(dataset_id, annotated=True)
    
    export_data = {
        'dataset': dataset,
        'annotations': []
    }
    
    for image in images:
        annotation = get_annotation(image['id'])
        if annotation:
            export_data['annotations'].append({
                'image_id': image['id'],
                'filename': image['filename'],
                'annotation_data': annotation['annotation_data']
            })
    
    # 保存导出文件
    export_path = os.path.join(ANNOTATIONS_DIR, str(dataset_id), 'export.json')
    with open(export_path, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    
    return jsonify({
        'success': True,
        'message': '导出成功',
        'data': {
            'export_path': export_path,
            'total_annotations': len(export_data['annotations'])
        }
    })