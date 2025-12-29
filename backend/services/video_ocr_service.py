"""
视频OCR服务（占位实现）
模拟返回类似图片中的OCR信息
"""
import random
from datetime import datetime, timedelta
from typing import Dict, Optional
import numpy as np


class VideoOCRService:
    """视频OCR识别服务（占位）"""
    
    def __init__(self):
        # 预定义的模拟数据
        self.train_numbers = ['G4926', 'G1234', 'D5678', 'C9012', 'G8765']
        self.route_sections = [
            '佛山西-宜宾', '北京-上海', '广州-深圳', 
            '成都-重庆', '武汉-长沙', '南京-杭州'
        ]
        self.base_mileage = 26.0  # 里程基准
        self.base_speed = 200  # 速度基准
        
        # 初始时间
        self.current_time = datetime(2025, 2, 14, 4, 42, 12)
    
    def extract_text(self, image_path: str, frame_idx: int = 0) -> Dict:
        """
        从图片中提取OCR文本（模拟）
        
        Args:
            image_path: 图片路径
            frame_idx: 帧序号
        
        Returns:
            OCR结果字典
        """
        # 模拟OCR处理时间
        # time.sleep(0.01)
        
        # 随机选择车次和区间
        train_no = random.choice(self.train_numbers)
        route_section = random.choice(self.route_sections)
        
        # 模拟车厢号和位置号
        car_no = random.randint(1, 16)
        pos_no = random.randint(1, 10)
        
        # 模拟速度（在基准速度附近波动）
        speed = self.base_speed + random.uniform(-30, 30)
        speed = max(0, min(350, speed))  # 限制在0-350之间
        
        # 模拟里程（随帧序号递增）
        mileage = self.base_mileage + (frame_idx * 0.05)
        
        # 模拟时间（每帧递增约1秒）
        ocr_time = self.current_time + timedelta(seconds=frame_idx)
        ocr_time_str = ocr_time.strftime('%Y-%m-%d %H:%M:%S')
        ocr_time_iso = ocr_time.isoformat()
        
        # 构造OCR文本（模拟图片中的格式）
        ocr_text = f"""里程:Z{int(mileage)}
区间:{route_section}
速度:{int(speed)}
车次:C{train_no}
车厢号:{car_no}
位置号:{pos_no}
{ocr_time_str}"""
        
        # OCR置信度（模拟）
        confidence = random.uniform(0.85, 0.98)
        
        result = {
            'ocr_text': ocr_text,
            'ocr_time': ocr_time_iso,
            'ocr_train_no': train_no,
            'ocr_route_section': route_section,
            'ocr_car_no': car_no,
            'ocr_pos_no': pos_no,
            'ocr_speed': round(speed, 1),
            'ocr_mileage': round(mileage, 2),
            'ocr_confidence': round(confidence, 3)
        }
        
        return result
    
    def batch_extract(self, image_paths: list, start_frame_idx: int = 0) -> list:
        """
        批量提取OCR信息
        
        Args:
            image_paths: 图片路径列表
            start_frame_idx: 起始帧序号
        
        Returns:
            OCR结果列表
        """
        results = []
        for i, image_path in enumerate(image_paths):
            result = self.extract_text(image_path, start_frame_idx + i)
            results.append(result)
        return results
    
    def reset_time(self, start_time: datetime = None):
        """重置起始时间"""
        if start_time:
            self.current_time = start_time
        else:
            self.current_time = datetime(2025, 2, 14, 4, 42, 12)


# 全局实例
video_ocr_service = VideoOCRService()


if __name__ == '__main__':
    # 测试
    service = VideoOCRService()
    
    # 模拟提取3帧
    for i in range(3):
        result = service.extract_text(f'frame_{i}.jpg', i)
        print(f"\n帧 {i} 的OCR结果:")
        print(f"  文本: {result['ocr_text'][:50]}...")
        print(f"  时间: {result['ocr_time']}")
        print(f"  车次: {result['ocr_train_no']}")
        print(f"  区间: {result['ocr_route_section']}")
        print(f"  速度: {result['ocr_speed']} km/h")
        print(f"  里程: {result['ocr_mileage']} km")
        print(f"  置信度: {result['ocr_confidence']}")
