import sqlite3
import json
from datetime import datetime
import os
import sys

# 添加父目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE_PATH

def get_db():
    """获取数据库连接"""
    # conn = sqlite3.connect(DATABASE_PATH) # 原来是这样的吧
    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=30.0,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    # 提升健壮性与并发能力
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA cache_size=-10000')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn

def init_db():
    """初始化数据库表"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 数据集表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            data_type TEXT NOT NULL,  -- image/video
            annotation_type TEXT NOT NULL,  -- classification/segmentation/ocr
            template TEXT NOT NULL,  -- single_label/multi_label/instance_segmentation等
            version TEXT DEFAULT 'V1',
            status TEXT DEFAULT 'created',  -- created/importing/completed
            image_count INTEGER DEFAULT 0,
            annotated_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 图片表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            is_annotated INTEGER DEFAULT 0,  -- 0=未标注, 1=已标注
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dataset_id) REFERENCES datasets(id)
        )
    ''')
    
    # 标注结果表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id INTEGER NOT NULL,
            dataset_id INTEGER NOT NULL,
            annotation_data TEXT NOT NULL,  -- JSON格式的标注数据
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (image_id) REFERENCES images(id),
            FOREIGN KEY (dataset_id) REFERENCES datasets(id)
        )
    ''')
    
    # 标签表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            color TEXT DEFAULT '#FF0000',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dataset_id) REFERENCES datasets(id)
        )
    ''')
    
    # 智能标注任务表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS smart_annotation_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            task_type TEXT NOT NULL,  -- active_learning/specify_model
            model_path TEXT,  -- 指定模型的checkpoint路径
            status TEXT DEFAULT 'pending',  -- pending/running/completed/failed
            progress INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dataset_id) REFERENCES datasets(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("数据库初始化完成")

# 数据集操作函数
def create_dataset(name, data_type, annotation_type, template):
    """创建数据集"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO datasets (name, data_type, annotation_type, template)
        VALUES (?, ?, ?, ?)
    ''', (name, data_type, annotation_type, template))
    dataset_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # 创建数据集目录
    from config import DATASETS_DIR, ANNOTATIONS_DIR
    os.makedirs(os.path.join(DATASETS_DIR, str(dataset_id)), exist_ok=True)
    os.makedirs(os.path.join(ANNOTATIONS_DIR, str(dataset_id)), exist_ok=True)
    
    return dataset_id

def get_all_datasets():
    """获取所有数据集"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM datasets ORDER BY created_at DESC')
    datasets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return datasets

def get_dataset(dataset_id):
    """获取单个数据集"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM datasets WHERE id = ?', (dataset_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_dataset(dataset_id):
    """删除数据集"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM annotations WHERE dataset_id = ?', (dataset_id,))
    cursor.execute('DELETE FROM images WHERE dataset_id = ?', (dataset_id,))
    cursor.execute('DELETE FROM labels WHERE dataset_id = ?', (dataset_id,))
    cursor.execute('DELETE FROM datasets WHERE id = ?', (dataset_id,))
    conn.commit()
    conn.close()

# 图片操作函数
def add_image(dataset_id, filename, filepath):
    """添加图片到数据集"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO images (dataset_id, filename, filepath)
        VALUES (?, ?, ?)
    ''', (dataset_id, filename, filepath))
    image_id = cursor.lastrowid
    
    # 更新数据集图片数量
    cursor.execute('''
        UPDATE datasets SET image_count = image_count + 1, updated_at = ?
        WHERE id = ?
    ''', (datetime.now(), dataset_id))
    
    conn.commit()
    conn.close()
    return image_id

def get_dataset_images(dataset_id, annotated=None):
    """获取数据集的图片列表"""
    conn = get_db()
    cursor = conn.cursor()
    
    if annotated is None:
        cursor.execute('SELECT * FROM images WHERE dataset_id = ? ORDER BY id', (dataset_id,))
    else:
        cursor.execute('SELECT * FROM images WHERE dataset_id = ? AND is_annotated = ? ORDER BY id', 
                      (dataset_id, 1 if annotated else 0))
    
    images = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return images

def get_image(image_id):
    """获取单张图片信息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM images WHERE id = ?', (image_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# 标注操作函数
def save_annotation(image_id, dataset_id, annotation_data):
    """保存标注结果"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 检查是否已有标注
    cursor.execute('SELECT id FROM annotations WHERE image_id = ?', (image_id,))
    existing = cursor.fetchone()
    
    if existing:
        # 更新现有标注
        cursor.execute('''
            UPDATE annotations SET annotation_data = ?, updated_at = ?
            WHERE image_id = ?
        ''', (json.dumps(annotation_data), datetime.now(), image_id))
    else:
        # 插入新标注
        cursor.execute('''
            INSERT INTO annotations (image_id, dataset_id, annotation_data)
            VALUES (?, ?, ?)
        ''', (image_id, dataset_id, json.dumps(annotation_data)))
        
        # 更新图片标注状态
        cursor.execute('UPDATE images SET is_annotated = 1 WHERE id = ?', (image_id,))
        
        # 更新数据集已标注数量
        cursor.execute('''
            UPDATE datasets SET annotated_count = annotated_count + 1, updated_at = ?
            WHERE id = ?
        ''', (datetime.now(), dataset_id))
    
    conn.commit()
    conn.close()

def get_annotation(image_id):
    """获取图片的标注结果"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM annotations WHERE image_id = ?', (image_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        result = dict(row)
        result['annotation_data'] = json.loads(result['annotation_data'])
        return result
    return None

# 标签操作函数
def add_label(dataset_id, name, color='#FF0000'):
    """添加标签"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO labels (dataset_id, name, color)
        VALUES (?, ?, ?)
    ''', (dataset_id, name, color))
    label_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return label_id

def get_dataset_labels(dataset_id):
    """获取数据集的所有标签"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM labels WHERE dataset_id = ? ORDER BY id', (dataset_id,))
    labels = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return labels

def delete_label_cascade(label_id):
    """级联删除标签及相关标注"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. 获取标签信息
    cursor.execute('SELECT * FROM labels WHERE id = ?', (label_id,))
    label = cursor.fetchone()
    if not label:
        conn.close()
        return {'affected_images': 0, 'success': False, 'message': '标签不存在'}
    
    dataset_id = label['dataset_id']
    
    # 2. 获取所有该数据集的标注记录
    cursor.execute('SELECT * FROM annotations WHERE dataset_id = ?', (dataset_id,))
    annotations = cursor.fetchall()
    
    if len(annotations) == 0:
        # 没有任何标注，直接删除标签
        cursor.execute('DELETE FROM labels WHERE id = ?', (label_id,))
        conn.commit()
        conn.close()
        return {'success': True, 'affected_images': 0, 'message': '标签已删除'}
    
    affected_images = set()  # 使用集合去重
    
    for annotation in annotations:
        annotation_data = json.loads(annotation['annotation_data'])
        image_id = annotation['image_id']
        modified = False
        
        # 处理分类标注
        if 'classification' in annotation_data:
            if annotation_data['classification'].get('labelId') == label_id:
                # 删除整条标注记录
                cursor.execute('DELETE FROM annotations WHERE id = ?', (annotation['id'],))
                cursor.execute('UPDATE images SET is_annotated = 0 WHERE id = ?', (image_id,))
                affected_images.add(image_id)
                modified = True
        
        # 处理分割/检测标注
        if 'shapes' in annotation_data and not modified:
            original_count = len(annotation_data['shapes'])
            annotation_data['shapes'] = [
                shape for shape in annotation_data['shapes'] 
                if shape.get('labelId') != label_id
            ]
            
            if len(annotation_data['shapes']) < original_count:
                modified = True
                affected_images.add(image_id)
                
                if len(annotation_data['shapes']) == 0:
                    # 没有标注了，删除记录
                    cursor.execute('DELETE FROM annotations WHERE id = ?', (annotation['id'],))
                    cursor.execute('UPDATE images SET is_annotated = 0 WHERE id = ?', (image_id,))
                else:
                    # 还有其他标注，更新JSON
                    cursor.execute('''
                        UPDATE annotations SET annotation_data = ?, updated_at = ?
                        WHERE id = ?
                    ''', (json.dumps(annotation_data), datetime.now(), annotation['id']))
    
    # 3. 删除标签
    cursor.execute('DELETE FROM labels WHERE id = ?', (label_id,))
    
    # 4. 更新数据集的已标注数量
    cursor.execute('''
        UPDATE datasets SET annotated_count = (
            SELECT COUNT(DISTINCT image_id) FROM annotations WHERE dataset_id = ?
        ), updated_at = ?
        WHERE id = ?
    ''', (dataset_id, datetime.now(), dataset_id))
    
    conn.commit()
    conn.close()
    
    return {
        'success': True,
        'affected_images': len(affected_images),
        'message': f'已删除标签，清理了 {len(affected_images)} 张图片的相关标注'
    }

def delete_label(label_id):
    """删除标签（保留作为接口兼容，内部调用级联删除）"""
    return delete_label_cascade(label_id)

def get_label_usage(label_id):
    """查询标签的使用情况"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取标签信息
    cursor.execute('SELECT * FROM labels WHERE id = ?', (label_id,))
    label = cursor.fetchone()
    if not label:
        conn.close()
        return {'success': False, 'message': '标签不存在'}
    
    dataset_id = label['dataset_id']
    
    # 统计使用该标签的图片数量
    cursor.execute('SELECT * FROM annotations WHERE dataset_id = ?', (dataset_id,))
    annotations = cursor.fetchall()
    
    used_images = set()
    
    for annotation in annotations:
        annotation_data = json.loads(annotation['annotation_data'])
        
        # 检查分类标注
        if 'classification' in annotation_data:
            if annotation_data['classification'].get('labelId') == label_id:
                used_images.add(annotation['image_id'])
        
        # 检查分割/检测标注
        if 'shapes' in annotation_data:
            for shape in annotation_data['shapes']:
                if shape.get('labelId') == label_id:
                    used_images.add(annotation['image_id'])
                    break
    
    conn.close()
    
    return {
        'success': True,
        'label_name': label['name'],
        'used_count': len(used_images),
        'image_ids': list(used_images)
    }

def update_label(label_id, name=None, color=None):
    """更新标签名称/颜色，并同步更新所有标注记录"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. 获取标签信息
    cursor.execute('SELECT * FROM labels WHERE id = ?', (label_id,))
    label = cursor.fetchone()
    if not label:
        conn.close()
        return {'success': False, 'message': '标签不存在'}
    
    dataset_id = label['dataset_id']
    old_name = label['name']
    old_color = label['color']
    
    new_name = name if name else old_name
    new_color = color if color else old_color
    
    # 2. 更新标签表
    cursor.execute('''
        UPDATE labels SET name = ?, color = ? WHERE id = ?
    ''', (new_name, new_color, label_id))
    
    # 3. 更新所有标注记录中的 labelName 和 color
    cursor.execute('SELECT * FROM annotations WHERE dataset_id = ?', (dataset_id,))
    annotations = cursor.fetchall()
    
    updated_count = 0
    for annotation in annotations:
        annotation_data = json.loads(annotation['annotation_data'])
        modified = False
        
        # 处理分类标注
        if 'classification' in annotation_data:
            if annotation_data['classification'].get('labelId') == label_id:
                annotation_data['classification']['labelName'] = new_name
                modified = True
        
        # 处理分割/检测标注
        if 'shapes' in annotation_data:
            for shape in annotation_data['shapes']:
                if shape.get('labelId') == label_id:
                    shape['labelName'] = new_name
                    shape['color'] = new_color
                    modified = True
        
        if modified:
            cursor.execute('''
                UPDATE annotations SET annotation_data = ?, updated_at = ?
                WHERE id = ?
            ''', (json.dumps(annotation_data), datetime.now(), annotation['id']))
            updated_count += 1
    
    conn.commit()
    conn.close()
    
    return {
        'success': True,
        'message': f'标签已更新，同步更新了 {updated_count} 条标注记录'
    }
    
if __name__ == '__main__':
    init_db()