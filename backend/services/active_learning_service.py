"""
主动学习服务 - 目标检测
负责：数据格式转换、模型训练、批量推理
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    CHECKPOINTS_DIR,
    DATASETS_DIR,
    ANNOTATIONS_DIR,
    DETECTION_CLASS_MAPPING,
    BASE_DIR
)
from models.database import (
    get_db, get_dataset, get_dataset_images, get_dataset_labels,
    get_annotation, save_annotation
)

# ==================== 配置 ====================

# YOLO训练临时目录
ACTIVE_LEARNING_WORK_DIR = os.path.join(BASE_DIR, 'data', 'active_learning_workspace')
os.makedirs(ACTIVE_LEARNING_WORK_DIR, exist_ok=True)

# 训练参数
DEFAULT_EPOCHS = 50  # 主动学习每轮训练轮数（可以较少，因为会多轮迭代）
DEFAULT_IMGSZ = 640
DEFAULT_BATCH = 8


# ==================== 数据格式转换 ====================

def get_class_mapping_from_labels(labels):
    """
    从数据集标签生成类别映射
    
    Args:
        labels: 数据集标签列表
    
    Returns:
        class_mapping: {label_name: class_id}
        id_to_name: {class_id: label_name}
    """
    # 按标签ID排序，保证映射稳定
    sorted_labels = sorted(labels, key=lambda x: x['id'])
    class_mapping = {}
    id_to_name = {}
    
    for idx, label in enumerate(sorted_labels):
        class_mapping[label['name']] = idx
        id_to_name[idx] = label['name']
    
    return class_mapping, id_to_name


def convert_annotation_to_yolo(annotation_data, image_width, image_height, class_mapping):
    """
    将EasyData标注格式转换为YOLO格式
    
    Args:
        annotation_data: EasyData标注数据
        image_width: 图片宽度
        image_height: 图片高度
        class_mapping: 类别名称到ID的映射
    
    Returns:
        YOLO格式的标注行列表
    """
    yolo_lines = []
    
    shapes = annotation_data.get('shapes', [])
    for shape in shapes:
        label_name = shape.get('labelName', '')
        if label_name not in class_mapping:
            continue
        
        class_id = class_mapping[label_name]
        points = shape.get('points', [])
        
        if not points:
            continue
        
        # 计算边界框
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]
        
        x_min = min(x_coords)
        x_max = max(x_coords)
        y_min = min(y_coords)
        y_max = max(y_coords)
        
        # 转换为YOLO格式（归一化的中心坐标和宽高）
        x_center = ((x_min + x_max) / 2) / image_width
        y_center = ((y_min + y_max) / 2) / image_height
        width = (x_max - x_min) / image_width
        height = (y_max - y_min) / image_height
        
        # 确保值在[0, 1]范围内
        x_center = max(0, min(1, x_center))
        y_center = max(0, min(1, y_center))
        width = max(0, min(1, width))
        height = max(0, min(1, height))
        
        yolo_lines.append(f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}")
    
    return yolo_lines


def prepare_yolo_dataset(task_id, dataset_id, labels):
    """
    准备YOLO训练数据集
    
    Args:
        task_id: 任务ID
        dataset_id: 数据集ID
        labels: 标签列表
    
    Returns:
        dataset_path: YOLO数据集路径
        class_mapping: 类别映射
    """
    # 创建工作目录
    work_dir = os.path.join(ACTIVE_LEARNING_WORK_DIR, f'task_{task_id}')
    dataset_path = os.path.join(work_dir, 'dataset')
    
    # 清理旧目录
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    
    # 创建目录结构
    train_images_dir = os.path.join(dataset_path, 'images', 'train')
    train_labels_dir = os.path.join(dataset_path, 'labels', 'train')
    val_images_dir = os.path.join(dataset_path, 'images', 'val')
    val_labels_dir = os.path.join(dataset_path, 'labels', 'val')
    
    for d in [train_images_dir, train_labels_dir, val_images_dir, val_labels_dir]:
        os.makedirs(d, exist_ok=True)
    
    # 获取类别映射
    class_mapping, id_to_name = get_class_mapping_from_labels(labels)
    
    # 获取已标注图片
    annotated_images = get_dataset_images(dataset_id, annotated=True)
    
    if len(annotated_images) == 0:
        raise ValueError("没有已标注的图片，无法训练")
    
    print(f"📊 准备训练数据：{len(annotated_images)} 张已标注图片")
    
    # 划分训练集和验证集（9:1）
    from random import shuffle, seed
    seed(42)
    shuffled_images = annotated_images.copy()
    shuffle(shuffled_images)
    
    val_count = max(1, len(shuffled_images) // 10)  # 至少1张验证
    val_images = shuffled_images[:val_count]
    train_images = shuffled_images[val_count:]
    
    print(f"📂 训练集：{len(train_images)} 张，验证集：{len(val_images)} 张")
    
    # 处理训练集
    for idx, img in enumerate(train_images):
        _process_image_for_yolo(
            img, idx, train_images_dir, train_labels_dir, 
            dataset_id, class_mapping
        )
    
    # 处理验证集
    for idx, img in enumerate(val_images):
        _process_image_for_yolo(
            img, idx, val_images_dir, val_labels_dir,
            dataset_id, class_mapping
        )
    
    # 生成dataset.yaml
    yaml_path = os.path.join(dataset_path, 'dataset.yaml')
    yaml_content = f"""# Auto-generated for active learning task {task_id}
path: {dataset_path}
train: images/train
val: images/val

nc: {len(class_mapping)}

names:
"""
    for name, idx in sorted(class_mapping.items(), key=lambda x: x[1]):
        yaml_content += f"  {idx}: {name}\n"
    
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)
    
    print(f"✅ YOLO数据集准备完成：{yaml_path}")
    
    return dataset_path, class_mapping, id_to_name


def _process_image_for_yolo(img, idx, images_dir, labels_dir, dataset_id, class_mapping):
    """处理单张图片，复制图片并生成YOLO标签"""
    from PIL import Image
    
    # 复制图片
    src_path = img['filepath']
    dst_path = os.path.join(images_dir, f"{idx}.jpg")
    shutil.copy2(src_path, dst_path)
    
    # 获取图片尺寸
    with Image.open(src_path) as pil_img:
        img_width, img_height = pil_img.size
    
    # 获取标注
    annotation = get_annotation(img['id'])
    if annotation and annotation.get('annotation_data'):
        yolo_lines = convert_annotation_to_yolo(
            annotation['annotation_data'],
            img_width, img_height,
            class_mapping
        )
        
        # 保存标签文件
        label_path = os.path.join(labels_dir, f"{idx}.txt")
        with open(label_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(yolo_lines))


# ==================== 模型训练 ====================

def train_yolo_model(task_id, dataset_path, epochs=DEFAULT_EPOCHS):
    """
    训练YOLO模型
    
    Args:
        task_id: 任务ID
        dataset_path: YOLO数据集路径
        epochs: 训练轮数
    
    Returns:
        checkpoint_path: 训练好的模型路径
    """
    from ultralytics import YOLO
    
    # 获取当前轮次
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT current_round FROM smart_annotation_tasks WHERE id = ?', (task_id,))
    row = cursor.fetchone()
    current_round = row['current_round'] if row else 1
    conn.close()
    
    # 输出目录
    work_dir = os.path.join(ACTIVE_LEARNING_WORK_DIR, f'task_{task_id}')
    output_dir = os.path.join(work_dir, 'runs')
    
    yaml_path = os.path.join(dataset_path, 'dataset.yaml')
    
    print(f"🚀 开始训练 - 任务{task_id} 第{current_round}轮")
    print(f"📁 数据集：{yaml_path}")
    print(f"⚙️ 参数：epochs={epochs}, imgsz={DEFAULT_IMGSZ}, batch={DEFAULT_BATCH}")
    
    # 加载预训练模型
    model = YOLO('yolov8m.pt')  # 使用YOLOv8m作为基础模型
    
    # 训练
    results = model.train(
        data=yaml_path,
        epochs=epochs,
        imgsz=DEFAULT_IMGSZ,
        batch=DEFAULT_BATCH,
        project=output_dir,
        name=f'round_{current_round}',
        exist_ok=True,
        verbose=True,
        device=0  # 使用GPU
    )
    
    # 找到best.pt
    best_pt = os.path.join(output_dir, f'round_{current_round}', 'weights', 'best.pt')
    
    if not os.path.exists(best_pt):
        raise FileNotFoundError(f"训练完成但未找到模型文件：{best_pt}")
    
    # 复制到checkpoints目录
    checkpoint_name = f"active_learning_{task_id}_round_{current_round}.pt"
    checkpoint_path = os.path.join(CHECKPOINTS_DIR, checkpoint_name)
    shutil.copy2(best_pt, checkpoint_path)
    
    print(f"✅ 训练完成，模型保存到：{checkpoint_path}")
    
    return checkpoint_path


# ==================== 批量推理 ====================

def run_batch_inference(task_id, dataset_id, checkpoint_path, batch_size, labels, id_to_name):
    """
    对未标注图片进行批量推理
    
    Args:
        task_id: 任务ID
        dataset_id: 数据集ID
        checkpoint_path: 模型路径
        batch_size: 本轮预标注数量
        labels: 标签列表
        id_to_name: 类别ID到名称的映射
    
    Returns:
        success_count: 成功标注数量
        image_ids: 被标注的图片ID列表
    """
    from ultralytics import YOLO
    from PIL import Image
    
    # 获取未标注图片
    unannotated_images = get_dataset_images(dataset_id, annotated=False)
    
    if len(unannotated_images) == 0:
        print("⚠️ 没有未标注的图片")
        return 0, []
    
    # 取前batch_size张
    images_to_annotate = unannotated_images[:batch_size]
    
    print(f"🔍 开始推理：{len(images_to_annotate)} 张图片")
    
    # 加载模型
    model = YOLO(checkpoint_path)
    
    # 构建标签名称到标签对象的映射
    label_map = {label['name']: label for label in labels}
    
    success_count = 0
    annotated_image_ids = []
    
    for img in images_to_annotate:
        try:
            # 获取图片尺寸
            with Image.open(img['filepath']) as pil_img:
                img_width, img_height = pil_img.size
            
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
                    
                    # 获取类别名称
                    class_name = id_to_name.get(class_id)
                    if not class_name or class_name not in label_map:
                        continue
                    
                    label = label_map[class_name]
                    
                    # 获取边界框坐标
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    
                    shapes.append({
                        'type': 'polygon',
                        'shapeType': 'rect',
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
                    'activelearningRound': get_current_round(task_id),
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
                annotated_image_ids.append(img['id'])
                
        except Exception as e:
            print(f"❌ 推理失败 {img['filepath']}: {str(e)}")
    
    print(f"✅ 推理完成：成功标注 {success_count} 张图片")
    
    return success_count, annotated_image_ids


def get_current_round(task_id):
    """获取任务当前轮次"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT current_round FROM smart_annotation_tasks WHERE id = ?', (task_id,))
    row = cursor.fetchone()
    conn.close()
    return row['current_round'] if row else 0


# ==================== 主动学习主流程 ====================

def run_active_learning_round(task_id):
    """
    执行一轮主动学习（训练 + 推理）
    
    Args:
        task_id: 任务ID
    
    Returns:
        result: 执行结果
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
        batch_size = task['batch_size'] or 20
        current_round = (task['current_round'] or 0) + 1
        
        # 获取标签
        from models.database import get_dataset_labels
        labels = get_dataset_labels(dataset_id)
        
        if not labels:
            return {'success': False, 'message': '数据集没有标签'}
        
        # 更新状态：训练中
        cursor.execute('''
            UPDATE smart_annotation_tasks 
            SET status = 'training', current_round = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (current_round, task_id))
        conn.commit()
        
        print(f"\n{'='*60}")
        print(f"🔄 主动学习 - 任务{task_id} 第{current_round}轮")
        print(f"{'='*60}")
        
        # 第一步：准备YOLO数据集
        print("\n📦 第一步：准备训练数据...")
        dataset_path, class_mapping, id_to_name = prepare_yolo_dataset(task_id, dataset_id, labels)
        
        # 第二步：训练模型
        print("\n🏋️ 第二步：训练模型...")
        checkpoint_path = train_yolo_model(task_id, dataset_path)
        
        # 更新checkpoint路径
        cursor.execute('''
            UPDATE smart_annotation_tasks 
            SET current_checkpoint = ?, status = 'inferring', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (checkpoint_path, task_id))
        conn.commit()
        
        # 第三步：批量推理
        print("\n🔍 第三步：批量推理...")
        success_count, annotated_ids = run_batch_inference(
            task_id, dataset_id, checkpoint_path, batch_size, labels, id_to_name
        )
        
        # 更新任务状态
        total_annotated = (task['total_annotated'] or 0) + success_count
        
        # 记录轮次历史
        round_history = json.loads(task['round_history'] or '[]')
        round_history.append({
            'round': current_round,
            'checkpoint': checkpoint_path,
            'annotated_count': success_count,
            'annotated_image_ids': annotated_ids,
            'timestamp': datetime.now().isoformat()
        })
        
        cursor.execute('''
            UPDATE smart_annotation_tasks 
            SET status = 'completed', 
                progress = 100,
                total_annotated = ?,
                round_history = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (total_annotated, json.dumps(round_history), task_id))
        conn.commit()
        
        print(f"\n{'='*60}")
        print(f"✅ 第{current_round}轮完成！")
        print(f"   本轮标注：{success_count} 张")
        print(f"   累计标注：{total_annotated} 张")
        print(f"{'='*60}\n")
        
        return {
            'success': True,
            'message': f'第{current_round}轮完成',
            'round': current_round,
            'annotated_count': success_count,
            'total_annotated': total_annotated,
            'checkpoint': checkpoint_path
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        
        cursor.execute('''
            UPDATE smart_annotation_tasks 
            SET status = 'failed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (task_id,))
        conn.commit()
        
        return {'success': False, 'message': str(e)}
    
    finally:
        conn.close()


def save_final_model(task_id, target_name=None):
    """
    保存最终模型到检测模型目录
    
    Args:
        task_id: 任务ID
        target_name: 目标文件名（可选）
    
    Returns:
        保存路径
    """
    from config import DETECTION_MODELS_DIR
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT current_checkpoint, dataset_id FROM smart_annotation_tasks WHERE id = ?', (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row['current_checkpoint']:
        raise ValueError("没有可保存的模型")
    
    checkpoint_path = row['current_checkpoint']
    
    if not os.path.exists(checkpoint_path):
        raise FileNotFoundError(f"Checkpoint文件不存在：{checkpoint_path}")
    
    # 生成目标文件名
    if not target_name:
        target_name = f"active_learning_task{task_id}_final.pt"
    
    target_path = os.path.join(DETECTION_MODELS_DIR, target_name)
    shutil.copy2(checkpoint_path, target_path)
    
    print(f"✅ 模型已保存到：{target_path}")
    
    return target_path


def cleanup_task_checkpoints(task_id, keep_final=True):
    """
    清理任务的中间checkpoint，只保留最终模型
    
    Args:
        task_id: 任务ID
        keep_final: 是否保留最终模型
    """
    import glob
    
    # 清理checkpoints目录中的该任务的所有checkpoint
    pattern = os.path.join(CHECKPOINTS_DIR, f"active_learning_{task_id}_round_*.pt")
    checkpoints = glob.glob(pattern)
    
    if keep_final and checkpoints:
        # 保留最后一个（最新的）
        checkpoints_sorted = sorted(checkpoints)
        for cp in checkpoints_sorted[:-1]:
            os.remove(cp)
            print(f"🗑️ 已删除：{cp}")
    else:
        for cp in checkpoints:
            os.remove(cp)
            print(f"🗑️ 已删除：{cp}")
    
    # 清理工作目录
    work_dir = os.path.join(ACTIVE_LEARNING_WORK_DIR, f'task_{task_id}')
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
        print(f"🗑️ 已清理工作目录：{work_dir}")