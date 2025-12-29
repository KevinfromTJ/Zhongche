"""
智能标注服务 - 批量推理
支持分类、检测、分割三种任务类型
"""

import os
import sys
import json
import torch
import numpy as np
import cv2
from PIL import Image
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    DETECTION_CLASS_MAPPING,
    CLASSIFIER_CLASS_NAMES,
    ANNOTATIONS_DIR
)
from models.database import (
    get_db, get_dataset, get_dataset_images, get_dataset_labels,
    get_image, save_annotation
)


def find_label_by_name(labels, name):
    """根据名称查找标签"""
    for label in labels:
        if label['name'] == name:
            return label
    return None


def run_classification_inference(dataset_id, model_path):
    """
    分类任务的批量推理
    
    Args:
        dataset_id: 数据集ID
        model_path: 模型路径
    
    Returns:
        dict: 包含成功数量、失败数量等信息
    """
    from services.classifier_service import predict_image
    
    # 获取数据集标签
    labels = get_dataset_labels(dataset_id)
    if not labels:
        return {'success': False, 'message': '数据集没有标签，请先创建标签'}
    
    # 获取未标注图片
    images = get_dataset_images(dataset_id, annotated=False)
    if not images:
        return {'success': False, 'message': '没有未标注的图片'}
    
    success_count = 0
    skip_count = 0
    error_count = 0
    
    for img in images:
        try:
            # 推理
            class_idx, class_name, confidence, all_probs = predict_image(img['filepath'])
            
            # 在数据集标签中查找匹配的标签
            label = find_label_by_name(labels, class_name)
            
            if label:
                # 构造标注数据
                annotation_data = {
                    'imageId': img['id'],
                    'annotationType': 'classification',
                    'classification': {
                        'labelId': label['id'],
                        'labelName': label['name']
                    },
                    'confidence': confidence,
                    'autoAnnotated': True,
                    'timestamp': datetime.now().isoformat()
                }
                
                # 保存标注
                save_annotation(img['id'], dataset_id, annotation_data)
                
                # 同时保存JSON文件
                annotation_dir = os.path.join(ANNOTATIONS_DIR, str(dataset_id))
                os.makedirs(annotation_dir, exist_ok=True)
                json_path = os.path.join(annotation_dir, f"{img['id']}.json")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(annotation_data, f, ensure_ascii=False, indent=2)
                
                success_count += 1
            else:
                # 标签不匹配，跳过
                skip_count += 1
                
        except Exception as e:
            print(f"分类推理失败 {img['filepath']}: {str(e)}")
            error_count += 1
    
    return {
        'success': True,
        'message': f'分类标注完成',
        'total': len(images),
        'success_count': success_count,
        'skip_count': skip_count,
        'error_count': error_count
    }


def run_detection_inference(dataset_id, model_path):
    """
    检测任务的批量推理
    
    Args:
        dataset_id: 数据集ID
        model_path: 模型路径
    
    Returns:
        dict: 包含成功数量、失败数量等信息
    """
    from ultralytics import YOLO
    
    # 获取数据集标签
    labels = get_dataset_labels(dataset_id)
    if not labels:
        return {'success': False, 'message': '数据集没有标签，请先创建标签'}
    
    # 获取未标注图片
    images = get_dataset_images(dataset_id, annotated=False)
    if not images:
        return {'success': False, 'message': '没有未标注的图片'}
    
    # 加载YOLO模型
    print(f"加载检测模型: {model_path}")
    model = YOLO(model_path)
    
    success_count = 0
    skip_count = 0
    error_count = 0
    
    for img in images:
        try:
            # YOLO推理
            results = model.predict(
                source=img['filepath'],
                conf=0.25,
                save=False,
                verbose=False
            )
            
            shapes = []
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])
                    class_name = DETECTION_CLASS_MAPPING.get(class_id, f"unknown_{class_id}")
                    
                    # 在数据集标签中查找匹配的标签
                    label = find_label_by_name(labels, class_name)
                    
                    if label:
                        # 获取边界框坐标
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        
                        shapes.append({
                            'type': 'polygon',
                            'points': [
                                [float(x1), float(y1)],
                                [float(x2), float(y1)],
                                [float(x2), float(y2)],
                                [float(x1), float(y2)]
                            ],
                            'labelId': label['id'],
                            'labelName': label['name'],
                            'color': label['color'],
                            'score': confidence
                        })
            
            if shapes:
                # 构造标注数据
                annotation_data = {
                    'imageId': img['id'],
                    'annotationType': 'detection',
                    'shapes': shapes,
                    'autoAnnotated': True,
                    'timestamp': datetime.now().isoformat()
                }
                
                # 保存标注
                save_annotation(img['id'], dataset_id, annotation_data)
                
                # 同时保存JSON文件
                annotation_dir = os.path.join(ANNOTATIONS_DIR, str(dataset_id))
                os.makedirs(annotation_dir, exist_ok=True)
                json_path = os.path.join(annotation_dir, f"{img['id']}.json")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(annotation_data, f, ensure_ascii=False, indent=2)
                
                success_count += 1
            else:
                skip_count += 1
                
        except Exception as e:
            print(f"检测推理失败 {img['filepath']}: {str(e)}")
            error_count += 1
    
    return {
        'success': True,
        'message': f'检测标注完成',
        'total': len(images),
        'success_count': success_count,
        'skip_count': skip_count,
        'error_count': error_count
    }


def run_segmentation_inference(dataset_id, model_path):
    """
    分割任务的批量推理（先检测后SAM分割）
    
    Args:
        dataset_id: 数据集ID
        model_path: 检测模型路径（YOLO）
    
    Returns:
        dict: 包含成功数量、失败数量等信息
    """
    from ultralytics import YOLO
    from segment_anything_hq import sam_model_registry, SamPredictor
    from config import SAM_CHECKPOINT, SAM_MODEL_TYPE, SAM_DEVICE
    
    # 获取数据集标签
    labels = get_dataset_labels(dataset_id)
    if not labels:
        return {'success': False, 'message': '数据集没有标签，请先创建标签'}
    
    # 获取未标注图片
    images = get_dataset_images(dataset_id, annotated=False)
    if not images:
        return {'success': False, 'message': '没有未标注的图片'}
    
    # 加载YOLO模型
    print(f"加载检测模型: {model_path}")
    yolo_model = YOLO(model_path)
    
    # 加载SAM模型
    print(f"加载SAM模型: {SAM_CHECKPOINT}")
    sam = sam_model_registry[SAM_MODEL_TYPE](checkpoint=SAM_CHECKPOINT)
    sam.to(device=SAM_DEVICE)
    sam_predictor = SamPredictor(sam)
    
    success_count = 0
    skip_count = 0
    error_count = 0
    
    for img in images:
        try:
            # 读取图片
            image = cv2.imread(img['filepath'])
            if image is None:
                error_count += 1
                continue
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            
            # 设置SAM图片
            sam_predictor.set_image(image_rgb)
            
            # YOLO推理获取检测框
            results = yolo_model.predict(
                source=img['filepath'],
                conf=0.25,
                save=False,
                verbose=False
            )
            
            shapes = []
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])
                    class_name = DETECTION_CLASS_MAPPING.get(class_id, f"unknown_{class_id}")
                    
                    # 在数据集标签中查找匹配的标签
                    label = find_label_by_name(labels, class_name)
                    
                    if label:
                        # 获取边界框
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        input_box = np.array([x1, y1, x2, y2])
                        
                        # SAM分割
                        masks, scores, logits = sam_predictor.predict(
                            point_coords=None,
                            point_labels=None,
                            box=input_box,
                            multimask_output=False
                        )
                        
                        # 将mask转换为多边形
                        mask = masks[0]
                        polygon = mask_to_polygon(mask)
                        
                        if polygon and len(polygon) >= 3:
                            shapes.append({
                                'type': 'polygon',
                                'points': polygon,
                                'labelId': label['id'],
                                'labelName': label['name'],
                                'color': label['color'],
                                'score': confidence
                            })
            
            if shapes:
                # 构造标注数据
                annotation_data = {
                    'imageId': img['id'],
                    'annotationType': 'segmentation',
                    'shapes': shapes,
                    'autoAnnotated': True,
                    'timestamp': datetime.now().isoformat()
                }
                
                # 保存标注
                save_annotation(img['id'], dataset_id, annotation_data)
                
                # 同时保存JSON文件
                annotation_dir = os.path.join(ANNOTATIONS_DIR, str(dataset_id))
                os.makedirs(annotation_dir, exist_ok=True)
                json_path = os.path.join(annotation_dir, f"{img['id']}.json")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(annotation_data, f, ensure_ascii=False, indent=2)
                
                success_count += 1
            else:
                skip_count += 1
                
        except Exception as e:
            print(f"分割推理失败 {img['filepath']}: {str(e)}")
            error_count += 1
    
    return {
        'success': True,
        'message': f'分割标注完成',
        'total': len(images),
        'success_count': success_count,
        'skip_count': skip_count,
        'error_count': error_count
    }


def mask_to_polygon(mask):
    """
    将二值掩码转换为多边形坐标
    
    Args:
        mask: 二值掩码 numpy数组
    
    Returns:
        polygon: 多边形坐标列表 [[x1, y1], [x2, y2], ...]
    """
    # 转换为uint8
    mask_uint8 = (mask * 255).astype(np.uint8)
    
    # 形态学处理，平滑轮廓
    kernel = np.ones((5, 5), np.uint8)
    mask_uint8 = cv2.morphologyEx(mask_uint8, cv2.MORPH_CLOSE, kernel)
    
    # 查找轮廓
    contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return []
    
    # 取最大的轮廓
    largest_contour = max(contours, key=cv2.contourArea)
    
    # 简化轮廓点数
    epsilon = 0.005 * cv2.arcLength(largest_contour, True)
    approx = cv2.approxPolyDP(largest_contour, epsilon, True)
    
    # 转换为列表格式
    polygon = approx.squeeze().tolist()
    
    # 确保返回的是二维列表
    if len(polygon) > 0 and not isinstance(polygon[0], list):
        polygon = [polygon]
    
    return polygon


def run_smart_annotation(task_id):
    """
    执行智能标注任务的主函数
    
    Args:
        task_id: 任务ID
    
    Returns:
        dict: 执行结果
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 获取任务信息
        cursor.execute('''
            SELECT t.*, d.annotation_type 
            FROM smart_annotation_tasks t
            JOIN datasets d ON t.dataset_id = d.id
            WHERE t.id = ?
        ''', (task_id,))
        task = cursor.fetchone()
        
        if not task:
            return {'success': False, 'message': '任务不存在'}
        
        task = dict(task)
        dataset_id = task['dataset_id']
        annotation_type = task['annotation_type']
        model_path = task['model_path']
        
        # 更新任务状态为运行中
        cursor.execute('''
            UPDATE smart_annotation_tasks 
            SET status = 'running', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (task_id,))
        conn.commit()
        
        # 根据标注类型执行不同的推理
        if annotation_type == 'classification':
            result = run_classification_inference(dataset_id, model_path)
        elif annotation_type == 'detection':
            result = run_detection_inference(dataset_id, model_path)
        elif annotation_type == 'segmentation':
            result = run_segmentation_inference(dataset_id, model_path)
        else:
            result = {'success': False, 'message': f'不支持的标注类型: {annotation_type}'}
        
        # 更新任务状态
        if result['success']:
            cursor.execute('''
                UPDATE smart_annotation_tasks 
                SET status = 'completed', progress = 100, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (task_id,))
        else:
            cursor.execute('''
                UPDATE smart_annotation_tasks 
                SET status = 'failed', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (task_id,))
        
        conn.commit()
        return result
        
    except Exception as e:
        # 更新任务状态为失败
        cursor.execute('''
            UPDATE smart_annotation_tasks 
            SET status = 'failed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (task_id,))
        conn.commit()
        return {'success': False, 'message': str(e)}
    
    finally:
        conn.close()