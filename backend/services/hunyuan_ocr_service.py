"""
HunyuanOCR 服务
基于 Transformers 的 HunYuanVL 模型实现 OCR
支持多进程并行推理（多卡 x 单卡多实例）

特点：
- 基于视觉语言模型，OCR精度高
- 使用 Transformers 库，支持 bfloat16/float16 推理
- 与 PaddleOCR 服务接口兼容，可互换使用
"""
import os
import sys
import threading
from typing import Dict, List, Tuple
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 全局变量：模型实例（进程内单例）
_hunyuan_model = None
_hunyuan_processor = None
_hunyuan_device = None
_hunyuan_lock = threading.Lock()


def _get_hunyuan_config():
    """获取 HunyuanOCR 配置"""
    from config import (
        HUNYUAN_OCR_MODEL_PATH,
        HUNYUAN_OCR_DTYPE,
        HUNYUAN_OCR_ATTN_IMPL,
        HUNYUAN_OCR_MAX_NEW_TOKENS,
        HUNYUAN_OCR_PROMPT,
    )
    return {
        'model_path': HUNYUAN_OCR_MODEL_PATH,
        'dtype': HUNYUAN_OCR_DTYPE,
        'attn_impl': HUNYUAN_OCR_ATTN_IMPL,
        'max_new_tokens': HUNYUAN_OCR_MAX_NEW_TOKENS,
        'prompt': HUNYUAN_OCR_PROMPT,
    }


def _get_torch_dtype(dtype_str: str):
    """将字符串转换为 torch dtype"""
    import torch
    dtype_map = {
        'bfloat16': torch.bfloat16,
        'float16': torch.float16,
        'float32': torch.float32,
    }
    return dtype_map.get(dtype_str, torch.bfloat16)


def _create_hunyuan_instance(gpu_id: str):
    """
    创建 HunyuanOCR 模型实例
    
    Args:
        gpu_id: GPU编号（CUDA_VISIBLE_DEVICES设置后的相对编号）
    
    Returns:
        (model, processor, device) 元组
    """
    import torch
    from transformers import AutoProcessor, HunYuanVLForConditionalGeneration
    
    config = _get_hunyuan_config()
    
    device = torch.device(f"cuda:{gpu_id}" if torch.cuda.is_available() else "cpu")
    dtype = _get_torch_dtype(config['dtype'])
    
    print(f"[HunyuanOCR] 加载模型: {config['model_path']}")
    print(f"[HunyuanOCR] 设备: {device}, dtype: {config['dtype']}, attn: {config['attn_impl']}")
    
    processor = AutoProcessor.from_pretrained(config['model_path'], use_fast=False)
    
    model = HunYuanVLForConditionalGeneration.from_pretrained(
        config['model_path'],
        attn_implementation=config['attn_impl'],
        dtype=dtype,
    ).to(device)
    
    # 设置为推理模式
    model.eval()
    
    return model, processor, device


def get_hunyuan_ocr(device_id: str = "0"):
    """获取 HunyuanOCR 模型实例（进程内单例）"""
    global _hunyuan_model, _hunyuan_processor, _hunyuan_device
    
    with _hunyuan_lock:
        if _hunyuan_model is None:
            print(f"正在加载 HunyuanOCR 模型 on cuda:{device_id}...")
            _hunyuan_model, _hunyuan_processor, _hunyuan_device = _create_hunyuan_instance(device_id)
            print("HunyuanOCR 模型加载完成")
        return _hunyuan_model, _hunyuan_processor, _hunyuan_device


def _hunyuan_recognize_single(image_path: str) -> str:
    """
    使用 HunyuanOCR 识别单张图片
    
    Args:
        image_path: 图片路径
    
    Returns:
        识别的文本内容
    """
    import torch
    from PIL import Image
    
    global _hunyuan_model, _hunyuan_processor, _hunyuan_device
    
    if _hunyuan_model is None:
        raise RuntimeError("HunyuanOCR 模型未初始化")
    
    config = _get_hunyuan_config()
    
    try:
        image = Image.open(image_path).convert('RGB')
    except Exception as e:
        print(f"⚠️ 无法打开图片 {image_path}: {e}")
        return ""
    
    # 构建消息格式
    messages = [
        {"role": "system", "content": ""},
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image_path},
                {"type": "text", "text": config['prompt']},
            ],
        }
    ]
    
    # 处理输入
    texts = [_hunyuan_processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)]
    inputs = _hunyuan_processor(
        text=texts,
        images=image,
        padding=True,
        return_tensors="pt",
    )
    
    # 推理
    with torch.no_grad():
        inputs = inputs.to(_hunyuan_device)
        generated_ids = _hunyuan_model.generate(
            **inputs,
            max_new_tokens=config['max_new_tokens'],
            do_sample=False
        )
    
    # 解码输出
    if "input_ids" in inputs:
        input_ids = inputs.input_ids
    else:
        input_ids = inputs.inputs
    
    generated_ids_trimmed = [
        out_ids[len(in_ids):] for in_ids, out_ids in zip(input_ids, generated_ids)
    ]
    
    output_texts = _hunyuan_processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False
    )
    
    return output_texts[0] if output_texts else ""


def _parse_hunyuan_result(text: str) -> List[Dict]:
    """
    将 HunyuanOCR 的文本输出转换为与 PaddleOCR 兼容的格式
    
    HunyuanOCR 直接输出文本，没有位置信息
    为了兼容性，我们将整个文本作为一个结果项
    
    Args:
        text: HunyuanOCR 输出的文本
    
    Returns:
        与 PaddleOCR 兼容的结果格式 [{'box': None, 'text': str, 'confidence': float}]
    """
    if not text or not text.strip():
        return []
    
    # HunyuanOCR 是 VLM 模型，没有检测框信息
    # 将整个输出作为一个识别结果
    return [{
        'box': None,  # 无位置信息
        'text': text.strip(),
        'confidence': 1.0  # VLM 模型没有置信度输出
    }]


# ============ 多进程相关函数 ============

def _process_worker_init_hunyuan(gpu_id: str):
    """进程初始化函数：在工作进程中预加载 HunyuanOCR 模型"""
    global _hunyuan_model, _hunyuan_processor, _hunyuan_device
    
    # 设置CUDA可见设备
    os.environ['CUDA_VISIBLE_DEVICES'] = gpu_id
    print(f"[PID:{os.getpid()}] 初始化 HunyuanOCR 工作进程，GPU={gpu_id}")
    
    # 预加载模型（使用gpu:0因为CUDA_VISIBLE_DEVICES映射后只有一个GPU可见）
    _hunyuan_model, _hunyuan_processor, _hunyuan_device = _create_hunyuan_instance("0")
    print(f"[PID:{os.getpid()}] HunyuanOCR 模型加载完成")


def _process_single_image_hunyuan(image_path: str) -> Tuple[str, List[Dict]]:
    """处理单张图片（在工作进程中执行）"""
    if not os.path.exists(image_path):
        return (image_path, [])
    
    try:
        text = _hunyuan_recognize_single(image_path)
        items = _parse_hunyuan_result(text)
        return (image_path, items)
    except Exception as e:
        print(f"⚠️ HunyuanOCR 处理失败 {image_path}: {e}")
        import traceback
        traceback.print_exc()
        return (image_path, [])


# ============ 多进程池管理 ============
_hunyuan_process_pools = {}  # gpu_id -> ProcessPoolExecutor
_hunyuan_pools_lock = threading.Lock()


def _get_or_create_hunyuan_process_pool(gpu_id: str, workers_per_gpu: int) -> ProcessPoolExecutor:
    """获取或创建指定GPU的进程池"""
    global _hunyuan_process_pools
    
    with _hunyuan_pools_lock:
        if gpu_id not in _hunyuan_process_pools:
            print(f"🔧 创建 HunyuanOCR GPU {gpu_id} 的进程池，工作进程数={workers_per_gpu}")
            # 使用spawn方式创建进程
            ctx = mp.get_context('spawn')
            pool = ProcessPoolExecutor(
                max_workers=workers_per_gpu,
                mp_context=ctx,
                initializer=_process_worker_init_hunyuan,
                initargs=(gpu_id,)
            )
            _hunyuan_process_pools[gpu_id] = pool
        return _hunyuan_process_pools[gpu_id]


def parallel_recognize_text_hunyuan(image_paths: List[str]) -> Dict[str, List[Dict]]:
    """
    多进程并行 HunyuanOCR 识别
    
    Args:
        image_paths: 图片路径列表
    
    Returns:
        {image_path: recognized_items} 的字典
    """
    if not image_paths:
        return {}
    
    from config import OCR_DEVICE_IDS, OCR_INSTANCES_PER_GPU
    
    gpu_ids = [g.strip() for g in OCR_DEVICE_IDS]
    num_gpus = len(gpu_ids)
    
    if num_gpus == 0:
        print("⚠️ 没有配置 OCR GPU")
        return {}
    
    # HunyuanOCR 是大模型，每个GPU通常只能运行1-2个实例
    # 但使用相同的配置参数，由用户根据显存调整
    # instances_per_gpu = min(OCR_INSTANCES_PER_GPU, 4)  
    # print(f"HunyuanOCR 每个GPU当前限制最多运行 4 个实例, 实际运行 {instances_per_gpu} 个实例")
    instances_per_gpu = OCR_INSTANCES_PER_GPU
    
    # 将图片均分到各个GPU
    gpu_tasks = {gpu_id: [] for gpu_id in gpu_ids}
    for i, img_path in enumerate(image_paths):
        gpu_id = gpu_ids[i % num_gpus]
        gpu_tasks[gpu_id].append(img_path)
    
    results = {}
    all_futures = []
    
    # 为每个GPU提交任务
    for gpu_id, tasks in gpu_tasks.items():
        if not tasks:
            continue
        
        pool = _get_or_create_hunyuan_process_pool(gpu_id, instances_per_gpu)
        
        # 提交任务到进程池
        for img_path in tasks:
            future = pool.submit(_process_single_image_hunyuan, img_path)
            all_futures.append((future, gpu_id))
    
    # 收集结果
    for future, gpu_id in all_futures:
        try:
            img_path, items = future.result(timeout=120)  # HunyuanOCR较慢，120秒超时
            results[img_path] = items
        except Exception as e:
            print(f"⚠️ GPU {gpu_id} HunyuanOCR 任务失败: {e}")
    
    return results


def recognize_text_hunyuan(image_path: str) -> List[Dict]:
    """
    识别单张图片中的文字（使用 HunyuanOCR）
    
    Args:
        image_path: 图片路径
    
    Returns:
        results: 识别结果列表
    """
    if not os.path.exists(image_path):
        print(f"⚠️ 图片不存在: {image_path}")
        return []
    
    from config import OCR_DEVICE_IDS
    gpu_id = OCR_DEVICE_IDS[0].strip() if OCR_DEVICE_IDS else "0"
    
    # 确保模型已加载
    get_hunyuan_ocr(gpu_id)
    
    text = _hunyuan_recognize_single(image_path)
    return _parse_hunyuan_result(text)


def shutdown_hunyuan_pools():
    """关闭所有 HunyuanOCR 进程池"""
    global _hunyuan_process_pools
    
    with _hunyuan_pools_lock:
        for gpu_id, pool in _hunyuan_process_pools.items():
            print(f"🔧 关闭 HunyuanOCR GPU {gpu_id} 的进程池")
            pool.shutdown(wait=True)
        _hunyuan_process_pools.clear()


if __name__ == '__main__':
    # 测试
    import sys
    
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
    else:
        test_image = "/data/chenjuntao/OtherProj/dataManage/OCR/6bd19657357ba82fa991df578e904cff.png"
    
    if os.path.exists(test_image):
        print(f"\n=== 测试 HunyuanOCR: {test_image} ===")
        
        # 测试单张图片识别
        results = recognize_text_hunyuan(test_image)
        print("\n识别结果:")
        for item in results:
            print(f"  文本: {item['text']}")
            print(f"  置信度: {item['confidence']}")
    else:
        print(f"测试图片不存在: {test_image}")
        print("用法: python hunyuan_ocr_service.py <图片路径>")
