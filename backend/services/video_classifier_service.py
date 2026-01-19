"""
视频分类服务（占位实现）
模拟多标签场景分类：天气、位置、时段、异常等
"""
import random
from typing import Dict, List
import json


class VideoClassifierService:
    """视频场景分类服务（占位）"""
    
    def __init__(self):
        # 定义标签类别
        self.weather_labels = ['晴天', '阴天', '雨天', '雾天', '雪天']
        self.location_labels = ['站台', '隧道内', '出站', '进站', '桥梁', '平原', '山区']
        self.time_period_labels = ['白天', '夜晚', '黄昏', '黎明']
        self.anomaly_labels = ['正常', '异常']
        
        # 标签权重（用于模拟真实分布）
        self.weather_weights = [0.5, 0.25, 0.15, 0.05, 0.05]
        self.location_weights = [0.1, 0.2, 0.1, 0.1, 0.15, 0.25, 0.1]
        self.time_period_weights = [0.6, 0.25, 0.1, 0.05]
        self.anomaly_weights = [0.95, 0.05]
    
    def classify(self, image_path: str, frame_idx: int = 0) -> Dict:
        """
        对图片进行多标签分类（模拟）
        
        Args:
            image_path: 图片路径
            frame_idx: 帧序号
        
        Returns:
            分类结果字典
        """
        # 标记帧：与 OCR 保持一致（frame_idx % 300 == 0）
        is_target = (frame_idx % 300 == 0)
        if is_target:
            weather = '晴天'
            location = '隧道内'
            time_period = '白天'
            anomaly = '正常'
            weather_score = 0.95
            location_score = 0.95
            time_period_score = 0.98
            anomaly_score = 0.98
        else:
            # 天气分类
            weather = random.choices(
                self.weather_labels, 
                weights=self.weather_weights, 
                k=1
            )[0]
            weather_score = random.uniform(0.75, 0.98)
            
            # 位置分类
            location = random.choices(
                self.location_labels, 
                weights=self.location_weights, 
                k=1
            )[0]
            location_score = random.uniform(0.70, 0.95)
            
            # 时段分类
            time_period = random.choices(
                self.time_period_labels, 
                weights=self.time_period_weights, 
                k=1
            )[0]
            time_period_score = random.uniform(0.80, 0.99)
            
            # 异常检测
            anomaly = random.choices(
                self.anomaly_labels, 
                weights=self.anomaly_weights, 
                k=1
            )[0]
            anomaly_score = random.uniform(0.90, 0.99) if anomaly == '正常' else random.uniform(0.60, 0.85)
        
        # 构造完整的标签JSON（包含所有分类器的结果）
        labels_json = {
            'weather': {
                'label': weather,
                'score': round(weather_score, 4),
                'all_scores': self._generate_scores(self.weather_labels, weather)
            },
            'location': {
                'label': location,
                'score': round(location_score, 4),
                'all_scores': self._generate_scores(self.location_labels, location)
            },
            'time_period': {
                'label': time_period,
                'score': round(time_period_score, 4),
                'all_scores': self._generate_scores(self.time_period_labels, time_period)
            },
            'anomaly': {
                'label': anomaly,
                'score': round(anomaly_score, 4),
                'all_scores': self._generate_scores(self.anomaly_labels, anomaly)
            }
        }
        
        result = {
            'label_weather': weather,
            'label_weather_score': round(weather_score, 4),
            'label_location': location,
            'label_location_score': round(location_score, 4),
            'label_time_period': time_period,
            'label_time_period_score': round(time_period_score, 4),
            'label_anomaly': anomaly,
            'label_anomaly_score': round(anomaly_score, 4),
            'labels_json': labels_json
        }
        
        return result
    
    def _generate_scores(self, labels: List[str], selected_label: str) -> Dict[str, float]:
        """生成所有标签的分数（最高分为选中的标签）"""
        scores = {}
        total_remaining = 1.0
        
        for label in labels:
            if label == selected_label:
                # 选中的标签得分最高
                scores[label] = round(random.uniform(0.70, 0.95), 4)
                total_remaining -= scores[label]
            else:
                continue
        
        # 为其他标签分配剩余分数
        remaining_labels = [l for l in labels if l != selected_label]
        if remaining_labels:
            for i, label in enumerate(remaining_labels):
                if i == len(remaining_labels) - 1:
                    # 最后一个标签获得剩余分数
                    scores[label] = max(0.01, round(total_remaining, 4))
                else:
                    score = random.uniform(0.01, total_remaining / (len(remaining_labels) - i))
                    scores[label] = round(score, 4)
                    total_remaining -= scores[label]
        
        return scores
    
    def batch_classify(self, image_paths: List[str], start_frame_idx: int = 0) -> List[Dict]:
        """
        批量分类
        
        Args:
            image_paths: 图片路径列表
            start_frame_idx: 起始帧序号
        
        Returns:
            分类结果列表
        """
        results = []
        for i, image_path in enumerate(image_paths):
            result = self.classify(image_path, start_frame_idx + i)
            results.append(result)
        return results
    
    def get_label_categories(self) -> Dict:
        """获取所有标签类别"""
        return {
            'weather': self.weather_labels,
            'location': self.location_labels,
            'time_period': self.time_period_labels,
            'anomaly': self.anomaly_labels
        }


# 全局实例
video_classifier_service = VideoClassifierService()


if __name__ == '__main__':
    # 测试
    service = VideoClassifierService()
    
    print("🏷️  可用标签类别:")
    categories = service.get_label_categories()
    for category, labels in categories.items():
        print(f"  {category}: {labels}")
    
    print("\n" + "="*60)
    
    # 模拟分类3帧
    for i in range(3):
        result = service.classify(f'frame_{i}.jpg', i)
        print(f"\n帧 {i} 的分类结果:")
        print(f"  天气: {result['label_weather']} ({result['label_weather_score']:.2%})")
        print(f"  位置: {result['label_location']} ({result['label_location_score']:.2%})")
        print(f"  时段: {result['label_time_period']} ({result['label_time_period_score']:.2%})")
        print(f"  异常: {result['label_anomaly']} ({result['label_anomaly_score']:.2%})")
        
        # 打印完整JSON
        print(f"  完整JSON: {json.dumps(result['labels_json'], ensure_ascii=False, indent=2)}")
