"""
视频分类服务
调用 ResNet50 模型进行场景分类
"""
import torch
import torchvision.models as models
import torch.nn as nn
from torchvision import transforms
from PIL import Image
import os
import sys
from typing import Dict, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 全局变量
_classifier_model = None
_classifier_device = None
_classifier_transform = None


def get_classifier():
    """获取分类器（单例模式）"""
    global _classifier_model, _classifier_device, _classifier_transform
    
    if _classifier_model is None:
        print("正在加载分类模型 (ResNet50)...")
        from config import CLASSIFIER_CHECKPOINT, CLASSIFIER_NUM_CLASSES
        
        _classifier_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"  使用设备: {_classifier_device}")
        
        # 加载模型
        _classifier_model = models.resnet50(weights=None)
        _classifier_model.fc = nn.Linear(_classifier_model.fc.in_features, CLASSIFIER_NUM_CLASSES)
        _classifier_model.load_state_dict(torch.load(CLASSIFIER_CHECKPOINT, map_location=_classifier_device))
        _classifier_model.eval().to(_classifier_device)
        
        # 预处理
        _classifier_transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.5037570595741272, 0.5405001640319824, 0.5926753878593445],
                std=[0.21774673461914062, 0.20995022356510162, 0.21212837100028992]
            )
        ])
        
        print("分类模型加载完成")
    
    return _classifier_model, _classifier_device, _classifier_transform


def predict_image(image_path):
    """对单张图片进行分类预测"""
    from config import CLASSIFIER_CLASS_NAMES
    
    model, device, transform = get_classifier()
    
    # 读取并预处理图像
    img = Image.open(image_path).convert("RGB")
    input_tensor = transform(img).unsqueeze(0).to(device)
    
    # 推理
    with torch.no_grad():
        output = model(input_tensor)
        probabilities = torch.softmax(output, dim=1)
        pred_idx = torch.argmax(probabilities, dim=1).item()
        confidence = probabilities[0][pred_idx].item()
        all_probs = probabilities[0].cpu().numpy().tolist()
    
    class_name = CLASSIFIER_CLASS_NAMES[pred_idx] if pred_idx < len(CLASSIFIER_CLASS_NAMES) else f"类别{pred_idx}"
    
    return pred_idx, class_name, confidence, all_probs


class VideoClassifierService:
    """视频场景分类服务"""
    
    def __init__(self):
        # 标签映射（根据你的8个类别）
        # "穿过高架桥", "阴天", "晴天无太阳", "镜头雨滴", "黑夜", "隧道内", "暴雨", "太阳光直射弓头"
        
        self.class_to_weather = {
            "晴天无太阳": "晴天",
            "阴天": "阴天",
            "镜头雨滴": "雨天",
            "暴雨": "雨天"
        }
        
        self.class_to_location = {
            "穿过高架桥": "桥梁",
            "隧道内": "隧道内"
        }
        
        self.class_to_time_period = {
            "黑夜": "夜晚",
            "太阳光直射弓头": "白天",
            "晴天无太阳": "白天",
            "阴天": "白天"
        }
    
    def classify(self, image_path: str, frame_idx: int = 0) -> Dict:
        """
        对图片进行分类
        
        Args:
            image_path: 图片路径
            frame_idx: 帧序号
        
        Returns:
            分类结果字典
        """
        # 调用 ResNet50 模型
        class_idx, class_name, confidence, all_probs = predict_image(image_path)
        
        # 将分类结果映射到多维度标签
        weather = self.class_to_weather.get(class_name, None)
        location = self.class_to_location.get(class_name, None)
        time_period = self.class_to_time_period.get(class_name, None)
        
        # 获取所有类别名称
        from config import CLASSIFIER_CLASS_NAMES
        
        # 构造完整的标签JSON
        labels_json = {
            'primary_class': class_name,
            'primary_confidence': round(confidence, 4),
            'all_classes': {
                name: round(prob, 4) 
                for name, prob in zip(CLASSIFIER_CLASS_NAMES, all_probs)
            }
        }
        
        result = {
            'label_weather': weather,
            'label_weather_score': round(confidence, 4) if weather else None,
            'label_location': location,
            'label_location_score': round(confidence, 4) if location else None,
            'label_time_period': time_period,
            'label_time_period_score': round(confidence, 4) if time_period else None,
            'label_anomaly': '正常',  # 默认正常，可以后续扩展
            'label_anomaly_score': 0.95,
            'labels_json': labels_json
        }
        
        return result
    
    def batch_classify(self, image_paths: List[str], start_frame_idx: int = 0) -> List[Dict]:
        """批量分类"""
        results = []
        for i, image_path in enumerate(image_paths):
            result = self.classify(image_path, start_frame_idx + i)
            results.append(result)
        return results
    
    def get_label_categories(self) -> Dict:
        """获取所有标签类别"""
        return {
            'weather': ['晴天', '阴天', '雨天', '雾天', '雪天'],
            'location': ['站台', '隧道内', '出站', '进站', '桥梁', '平原', '山区'],
            'time_period': ['白天', '夜晚', '黄昏', '黎明'],
            'anomaly': ['正常', '异常']
        }


# 全局实例
video_classifier_service = VideoClassifierService()


if __name__ == '__main__':
    # 测试
    import sys
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
    else:
        test_image = "/root/autodl-tmp/backend/data/video_frames/1/1/frame_000000.jpg"
    
    if os.path.exists(test_image):
        service = VideoClassifierService()
        result = service.classify(test_image, 0)
        print("\n=== 分类结果 ===")
        for key, value in result.items():
            if key != 'labels_json':
                print(f"{key}: {value}")
        print("\n完整JSON:")
        import json
        print(json.dumps(result['labels_json'], ensure_ascii=False, indent=2))
    else:
        print(f"测试图片不存在: {test_image}")
        print("用法: python video_classifier_service.py <图片路径>")
