import numpy as np
import torch
import cv2
import os
import sys

# 全局变量，避免重复加载模型
_sam_predictor = None
_current_image_path = None

def get_sam_predictor():
    """获取SAM预测器（单例模式）"""
    global _sam_predictor
    
    if _sam_predictor is None:
        print("正在加载SAM模型...")
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config import SAM_CHECKPOINT, SAM_MODEL_TYPE, SAM_DEVICE
        
        from segment_anything_hq import sam_model_registry, SamPredictor
        
        sam = sam_model_registry[SAM_MODEL_TYPE](checkpoint=SAM_CHECKPOINT)
        sam.to(device=SAM_DEVICE)
        _sam_predictor = SamPredictor(sam)
        print("SAM模型加载完成")
    
    return _sam_predictor

def set_image(image_path):
    """设置当前要处理的图片"""
    global _current_image_path
    
    predictor = get_sam_predictor()
    
    # 如果是同一张图片，不重复加载
    if _current_image_path == image_path:
        return True
    
    image = cv2.imread(image_path)
    if image is None:
        return False
    
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    predictor.set_image(image)
    _current_image_path = image_path
    
    return True

def predict_with_points(image_path, points, labels):
    """
    使用点提示进行分割
    
    Args:
        image_path: 图片路径
        points: 点坐标列表 [[x1, y1], [x2, y2], ...]
        labels: 点标签列表 [1, 0, 1, ...]  1=正点(前景), 0=负点(背景)
    
    Returns:
        mask: 分割掩码（二值图像）
        score: 置信度分数
        polygon: 轮廓多边形坐标
    """
    if not set_image(image_path):
        return None, None, None
    
    predictor = get_sam_predictor()
    
    input_point = np.array(points)
    input_label = np.array(labels)
    
    masks, scores, logits = predictor.predict(
        point_coords=input_point,
        point_labels=input_label,
        multimask_output=False,
    )
    
    # 取第一个mask
    mask = masks[0]
    score = scores[0]
    
    # 将mask转换为多边形轮廓
    polygon = mask_to_polygon(mask)
    
    return mask.tolist(), float(score), polygon

def predict_with_box(image_path, box):
    """
    使用矩形框提示进行分割
    
    Args:
        image_path: 图片路径
        box: 矩形框 [x1, y1, x2, y2]
    
    Returns:
        mask: 分割掩码
        score: 置信度分数
        polygon: 轮廓多边形坐标
    """
    if not set_image(image_path):
        return None, None, None
    
    predictor = get_sam_predictor()
    
    input_box = np.array(box)
    
    masks, scores, logits = predictor.predict(
        point_coords=None,
        point_labels=None,
        box=input_box,
        multimask_output=False,
    )
    
    mask = masks[0]
    score = scores[0]
    polygon = mask_to_polygon(mask)
    
    return mask.tolist(), float(score), polygon

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
    
    # 查找轮廓
    contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return []
    
    # 取最大的轮廓
    largest_contour = max(contours, key=cv2.contourArea)
    
    # 简化轮廓点数（减少数据量）
    epsilon = 0.005 * cv2.arcLength(largest_contour, True)
    approx = cv2.approxPolyDP(largest_contour, epsilon, True)
    
    # 转换为列表格式
    polygon = approx.squeeze().tolist()
    
    # 确保返回的是二维列表
    if len(polygon) > 0 and not isinstance(polygon[0], list):
        polygon = [polygon]
    
    return polygon

def clear_cache():
    """清除缓存的图片"""
    global _current_image_path
    _current_image_path = None