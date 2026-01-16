"""
视频OCR服务
调用 PaddleOCR (PP-OCRv5_server) 识别图片中的文字
"""
import os
import sys
import re
from typing import Dict, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 全局变量
_ocr_model = None


def get_ocr():
    """获取OCR模型（单例模式）"""
    global _ocr_model
    
    if _ocr_model is None:
        print("正在加载OCR模型 (PP-OCRv5_server)...")
        from paddleocr import PaddleOCR
        
        _ocr_model = PaddleOCR(
            text_detection_model_name="PP-OCRv5_server_det",
            text_recognition_model_name="PP-OCRv5_server_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
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
            - box: 文本框坐标
            - text: 识别的文字
            - confidence: 置信度（如果有）
    """
    ocr = get_ocr()
    
    # 使用 predict 方法
    result = ocr.predict(image_path)
    
    if not result:
        return []
    
    recognized_items = []
    
    for res in result:
        if isinstance(res, dict):
            text = res.get('text', '')
            box = res.get('box', [])
            confidence = res.get('confidence', res.get('score', 1.0))  # 尝试获取置信度
            
            recognized_items.append({
                'box': box,
                'text': text,
                'confidence': float(confidence) if confidence else 1.0
            })
    
    return recognized_items


class VideoOCRService:
    """视频OCR识别服务"""
    
    def __init__(self):
        pass
    
    def extract_text(self, image_path: str, frame_idx: int = 0) -> Dict:
        """
        从图片中提取OCR文本并解析结构化信息
        
        Args:
            image_path: 图片路径
            frame_idx: 帧序号
        
        Returns:
            OCR结果字典
        """
        # 调用 PaddleOCR 识别
        ocr_items = recognize_text(image_path)
        
        # 拼接所有文本
        full_text = ' '.join([item['text'] for item in ocr_items])
        
        # 计算平均置信度
        avg_confidence = sum([item['confidence'] for item in ocr_items]) / len(ocr_items) if ocr_items else 0.0
        
        # 解析结构化信息（字段名与数据库一致）
        ocr_result = {
            'ocr_text': full_text,
            'ocr_time': self._extract_time(full_text),
            'ocr_train_no': self._extract_train_no(full_text),
            'ocr_route_section': self._extract_route_section(full_text),
            'ocr_car_no': self._extract_number(full_text, r'车厢号[:：]?\s*(\d+)'),
            'ocr_pos_no': self._extract_number(full_text, r'位置号[:：]?\s*(\d+)'),
            'ocr_speed': self._extract_float(full_text, r'速度[:：]?\s*(\d+\.?\d*)'),
            'ocr_mileage': self._extract_float(full_text, r'里程[:：]?\s*[Zz]?(\d+\.?\d*)'),
            'ocr_confidence': round(avg_confidence, 3)
        }
        
        return ocr_result
    
    def _extract_time(self, text: str):
        """提取时间"""
        # 匹配格式：2025-02-14 04:42:12 或 2025/02/14 04:42:12
        pattern = r'(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2})'
        match = re.search(pattern, text)
        if match:
            time_str = match.group(1).replace('/', '-')
            return time_str.replace(' ', 'T')  # 转ISO格式
        return None
    
    def _extract_train_no(self, text: str):
        """提取车次号"""
        # 匹配格式：G4926、D5678、C1234 等
        pattern = r'[CGDcgd]\d{4}'
        match = re.search(pattern, text)
        return match.group(0).upper() if match else None
    
    def _extract_route_section(self, text: str):
        """提取区间"""
        # 匹配格式：佛山西-宜宾、北京-上海 等
        pattern = r'区间[:：]?\s*([\u4e00-\u9fa5]+-[\u4e00-\u9fa5]+)'
        match = re.search(pattern, text)
        return match.group(1) if match else None
    
    def _extract_number(self, text: str, pattern: str):
        """提取整数"""
        match = re.search(pattern, text)
        if match:
            try:
                return int(match.group(1))
            except:
                pass
        return None
    
    def _extract_float(self, text: str, pattern: str):
        """提取浮点数"""
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group(1))
            except:
                pass
        return None
    
    def batch_extract(self, image_paths: list, start_frame_idx: int = 0) -> list:
        """批量提取OCR信息"""
        results = []
        for i, image_path in enumerate(image_paths):
            result = self.extract_text(image_path, start_frame_idx + i)
            results.append(result)
        return results


# 全局实例
video_ocr_service = VideoOCRService()


if __name__ == '__main__':
    # 测试
    import sys
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
    else:
        test_image = "/root/autodl-tmp/backend/data/video_frames/1/1/frame_000000.jpg"
    
    if os.path.exists(test_image):
        service = VideoOCRService()
        result = service.extract_text(test_image, 0)
        print("\n=== OCR 结果 ===")
        for key, value in result.items():
            print(f"{key}: {value}")
    else:
        print(f"测试图片不存在: {test_image}")
        print("用法: python video_ocr_service.py <图片路径>")