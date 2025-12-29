import os
import json

# 全局变量
_ocr_model = None

def get_ocr():
    """获取OCR模型（单例模式）"""
    global _ocr_model
    
    if _ocr_model is None:
        print("正在加载OCR模型...")
        from paddleocr import PaddleOCR
        
        _ocr_model = PaddleOCR(
            use_angle_cls=True,
            lang='ch',
            use_gpu=True,
            show_log=False
        )
        
        print("OCR模型加载完成")
    
    return _ocr_model

def recognize_text(image_path):
    """
    识别图片中的文字
    
    Args:
        image_path: 图片路径
    
    Returns:
        results: 识别结果列表，每个元素包含：
            - box: 文本框坐标 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            - text: 识别的文字
            - confidence: 置信度
    """
    ocr = get_ocr()
    
    result = ocr.ocr(image_path, cls=True)
    
    if not result or not result[0]:
        return []
    
    recognized_items = []
    
    for line in result[0]:
        box = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
        text = line[1][0]  # 识别的文字
        confidence = line[1][1]  # 置信度
        
        recognized_items.append({
            'box': box,
            'text': text,
            'confidence': float(confidence)
        })
    
    return recognized_items

def recognize_batch(image_paths):
    """
    批量识别多张图片
    
    Args:
        image_paths: 图片路径列表
    
    Returns:
        results: 识别结果字典，key为图片路径
    """
    results = {}
    
    for path in image_paths:
        try:
            items = recognize_text(path)
            results[path] = {
                'success': True,
                'items': items
            }
        except Exception as e:
            results[path] = {
                'success': False,
                'error': str(e)
            }
    
    return results