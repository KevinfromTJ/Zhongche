import torch
import torchvision.models as models
import torch.nn as nn
from torchvision import transforms
from PIL import Image
import os
import sys

# 全局变量
_classifier_model = None
_classifier_device = None
_classifier_transform = None

def get_classifier():
    """获取分类器（单例模式）"""
    global _classifier_model, _classifier_device, _classifier_transform
    
    if _classifier_model is None:
        print("正在加载分类模型...")
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config import CLASSIFIER_CHECKPOINT, CLASSIFIER_NUM_CLASSES
        
        _classifier_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
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
    """
    对单张图片进行分类预测
    
    Args:
        image_path: 图片路径
    
    Returns:
        class_idx: 预测类别索引
        class_name: 预测类别名称
        confidence: 置信度
        all_probs: 所有类别的概率
    """
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

def predict_batch(image_paths):
    """
    批量预测多张图片
    
    Args:
        image_paths: 图片路径列表
    
    Returns:
        results: 预测结果列表
    """
    results = []
    for path in image_paths:
        try:
            class_idx, class_name, confidence, all_probs = predict_image(path)
            results.append({
                'image_path': path,
                'class_idx': class_idx,
                'class_name': class_name,
                'confidence': confidence,
                'all_probs': all_probs
            })
        except Exception as e:
            results.append({
                'image_path': path,
                'error': str(e)
            })
    
    return results