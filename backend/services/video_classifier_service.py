"""
视频分类服务
调用 ResNet50 模型进行场景分类
支持多GPU并行和真正的batch推理
"""
import torch
import torchvision.models as models
import torch.nn as nn
from torchvision import transforms
from PIL import Image
import os
import sys
from typing import Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 全局变量：分类器实例池
_classifier_instances = {}  # key: gpu_id, value: (model, device, transform)
_classifier_instances_lock = threading.Lock()
_classifier_initialized = False


def _create_classifier_instance(gpu_id: str):
    """创建单个分类器实例"""
    from config import CLASSIFIER_CHECKPOINT, CLASSIFIER_NUM_CLASSES
    
    device_str = f"cuda:{gpu_id}" if gpu_id != "cpu" else "cpu"
    
    if device_str.startswith("cuda") and not torch.cuda.is_available():
        print(f"⚠️ CUDA不可用，回退到CPU")
        device_str = "cpu"
    
    device = torch.device(device_str)
    print(f"   正在加载分类模型 on {device}...")
    
    # 加载模型
    model = models.resnet50(weights=None)
    model.fc = nn.Linear(model.fc.in_features, CLASSIFIER_NUM_CLASSES)
    model.load_state_dict(torch.load(CLASSIFIER_CHECKPOINT, map_location=device))
    model.eval().to(device)
    
    # 预处理
    transform = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.5037570595741272, 0.5405001640319824, 0.5926753878593445],
            std=[0.21774673461914062, 0.20995022356510162, 0.21212837100028992]
        )
    ])
    
    print(f"   分类模型 on {device} 加载完成")
    return model, device, transform


def init_classifier_pool():
    """初始化分类器实例池"""
    global _classifier_instances, _classifier_initialized
    
    with _classifier_instances_lock:
        if _classifier_initialized:
            return
        
        from config import CLASSIFIER_DEVICE_IDS
        
        print(f"🔧 初始化分类器实例池: GPUs={CLASSIFIER_DEVICE_IDS}")
        
        for gpu_id in CLASSIFIER_DEVICE_IDS:
            gpu_id = gpu_id.strip()
            _classifier_instances[gpu_id] = _create_classifier_instance(gpu_id)
        
        print(f"✅ 分类器实例池初始化完成，共 {len(_classifier_instances)} 个实例")
        _classifier_initialized = True


def get_classifier(gpu_id: str = None):
    """获取分类器实例"""
    global _classifier_instances, _classifier_initialized
    
    # 确保实例池已初始化
    if not _classifier_initialized:
        init_classifier_pool()
    
    with _classifier_instances_lock:
        if gpu_id is None:
            # 返回第一个可用的实例
            if _classifier_instances:
                return list(_classifier_instances.values())[0]
            # 创建默认实例
            from config import CLASSIFIER_DEVICE_IDS
            gpu_id = CLASSIFIER_DEVICE_IDS[0].strip()
        
        if gpu_id in _classifier_instances:
            return _classifier_instances[gpu_id]
        
        # 创建新实例
        instance = _create_classifier_instance(gpu_id)
        _classifier_instances[gpu_id] = instance
        return instance


def get_all_classifier_instances() -> List[Tuple[str, object, object, object]]:
    """获取所有分类器实例"""
    if not _classifier_initialized:
        init_classifier_pool()
    
    with _classifier_instances_lock:
        return [(gpu_id, model, device, transform) 
                for gpu_id, (model, device, transform) in _classifier_instances.items()]


def predict_image(image_path, gpu_id: str = None):
    """对单张图片进行分类预测"""
    from config import CLASSIFIER_CLASS_NAMES
    
    model, device, transform = get_classifier(gpu_id)
    
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


def batch_predict_images(image_paths: List[str], gpu_id: str = None, batch_size: int = None) -> List[Tuple]:
    """
    真正的batch推理：批量对图片进行分类预测
    
    Args:
        image_paths: 图片路径列表
        gpu_id: GPU ID
        batch_size: 批处理大小
    
    Returns:
        [(pred_idx, class_name, confidence, all_probs), ...] 每张图片的预测结果
    """
    from config import CLASSIFIER_CLASS_NAMES, CLASSIFIER_BATCH_SIZE
    
    if batch_size is None:
        batch_size = CLASSIFIER_BATCH_SIZE
    
    model, device, transform = get_classifier(gpu_id)
    
    results = []
    
    # 分批处理
    for i in range(0, len(image_paths), batch_size):
        batch_paths = image_paths[i:i + batch_size]
        
        # 预处理批量图片
        batch_tensors = []
        valid_indices = []
        
        for j, img_path in enumerate(batch_paths):
            try:
                if not os.path.exists(img_path):
                    results.append((0, "未知", 0.0, []))
                    continue
                
                img = Image.open(img_path).convert("RGB")
                tensor = transform(img)
                batch_tensors.append(tensor)
                valid_indices.append(i + j)
            except Exception as e:
                print(f"⚠️ 图片加载失败 {img_path}: {e}")
                results.append((0, "未知", 0.0, []))
        
        if not batch_tensors:
            continue
        
        # 组成batch
        batch_input = torch.stack(batch_tensors).to(device)
        
        # 批量推理
        with torch.no_grad():
            outputs = model(batch_input)
            probabilities = torch.softmax(outputs, dim=1)
            pred_indices = torch.argmax(probabilities, dim=1).cpu().numpy()
            all_probs_batch = probabilities.cpu().numpy()
        
        # 解析结果
        for k, (pred_idx, probs) in enumerate(zip(pred_indices, all_probs_batch)):
            confidence = probs[pred_idx]
            class_name = CLASSIFIER_CLASS_NAMES[pred_idx] if pred_idx < len(CLASSIFIER_CLASS_NAMES) else f"类别{pred_idx}"
            results.append((int(pred_idx), class_name, float(confidence), probs.tolist()))
    
    return results


def _classifier_worker(gpu_id: str, image_paths: List[str], batch_size: int) -> List[Tuple[str, Tuple]]:
    """单个分类器实例的工作函数"""
    results = batch_predict_images(image_paths, gpu_id, batch_size)
    return list(zip(image_paths, results))


def parallel_classify_images(image_paths: List[str], batch_size: int = None) -> Dict[str, Tuple]:
    """
    多GPU并行分类推理
    
    Args:
        image_paths: 图片路径列表
        batch_size: 批处理大小
    
    Returns:
        {image_path: (pred_idx, class_name, confidence, all_probs)} 的字典
    """
    from config import CLASSIFIER_BATCH_SIZE
    
    if batch_size is None:
        batch_size = CLASSIFIER_BATCH_SIZE
    
    if not image_paths:
        return {}
    
    # 获取所有分类器实例
    instances = get_all_classifier_instances()
    if not instances:
        print("⚠️ 没有可用的分类器实例")
        return {}
    
    num_instances = len(instances)
    
    # 将图片均分到各个GPU
    chunks = [[] for _ in range(num_instances)]
    for i, img_path in enumerate(image_paths):
        chunks[i % num_instances].append(img_path)
    
    # 并行执行
    results = {}
    with ThreadPoolExecutor(max_workers=num_instances) as executor:
        futures = {}
        for i, (gpu_id, model, device, transform) in enumerate(instances):
            if chunks[i]:
                future = executor.submit(_classifier_worker, gpu_id, chunks[i], batch_size)
                futures[future] = gpu_id
        
        for future in as_completed(futures):
            gpu_id = futures[future]
            try:
                worker_results = future.result()
                for img_path, pred_result in worker_results:
                    results[img_path] = pred_result
            except Exception as e:
                print(f"⚠️ 分类器实例 [{gpu_id}] 执行失败: {e}")
    
    return results


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
    
    def _build_result(self, class_idx: int, class_name: str, confidence: float, all_probs: List[float]) -> Dict:
        """根据分类结果构建返回字典"""
        from config import CLASSIFIER_CLASS_NAMES
        
        weather = self.class_to_weather.get(class_name, None)
        location = self.class_to_location.get(class_name, None)
        time_period = self.class_to_time_period.get(class_name, None)
        
        labels_json = {
            'primary_class': class_name,
            'primary_confidence': round(confidence, 4),
            'all_classes': {
                name: round(prob, 4) 
                for name, prob in zip(CLASSIFIER_CLASS_NAMES, all_probs)
            } if all_probs else {}
        }
        
        return {
            'label_weather': weather,
            'label_weather_score': round(confidence, 4) if weather else None,
            'label_location': location,
            'label_location_score': round(confidence, 4) if location else None,
            'label_time_period': time_period,
            'label_time_period_score': round(confidence, 4) if time_period else None,
            'label_anomaly': '正常',
            'label_anomaly_score': 0.95,
            'labels_json': labels_json
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
        class_idx, class_name, confidence, all_probs = predict_image(image_path)
        return self._build_result(class_idx, class_name, confidence, all_probs)
    
    def batch_classify(self, image_paths: List[str], start_frame_idx: int = 0, use_parallel: bool = True) -> List[Dict]:
        """
        批量分类（真正的batch推理 + 多GPU并行）
        
        Args:
            image_paths: 图片路径列表
            start_frame_idx: 起始帧序号
            use_parallel: 是否使用多GPU并行
        
        Returns:
            分类结果列表
        """
        if not image_paths:
            return []
        
        if use_parallel:
            # 使用多GPU并行 + 真正batch推理
            pred_dict = parallel_classify_images(image_paths)
            
            results = []
            for img_path in image_paths:
                if img_path in pred_dict:
                    pred_idx, class_name, confidence, all_probs = pred_dict[img_path]
                    results.append(self._build_result(pred_idx, class_name, confidence, all_probs))
                else:
                    results.append(self._build_result(0, "未知", 0.0, []))
            return results
        else:
            # 单GPU batch推理
            pred_results = batch_predict_images(image_paths)
            return [self._build_result(*pred) for pred in pred_results]
    
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
