#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频管理API测试脚本

测试功能：
1. 视频上传与信息提取
2. 视频抽帧
3. AI处理（OCR + 分类）
4. 多条件查询
"""

import requests
import json
import time
import os
from pathlib import Path
import zipfile
from .config import PORT

# API基础URL
BASE_URL = f"http://localhost:{PORT}/api"

def print_separator(title=""):
    """打印分隔线"""
    print("\n" + "="*80)
    if title:
        print(f"  {title}")
        print("="*80)

def print_response(response):
    """美化打印响应"""
    try:
        data = response.json()
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except:
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

TEST_OUT_ROOT = os.environ.get(
    "TEST_OUT_DIR",
    "/data/chenjuntao/OtherProj/dataManage/ref_fengchen_251225/test_outputs"
)

# ============================================================================
# 测试1: 注册视频路径
# ============================================================================
def test_upload_video(video_path ="/data/chenjuntao/OtherProj/dataManage/test_wrong.MP4"):
    """测试视频注册（使用已存在的视频路径）"""
    print_separator("测试1: 注册视频路径")
    
    # 使用已存在的视频路径
    # 可通过环境变量覆盖：TEST_VIDEO_PATH=/path/to/video.mp4
    # video_path = os.environ.get("TEST_VIDEO_PATH")
    if not video_path:
        # 合理的默认样例（正常 MP4），如需测试 raw h264 可在环境变量中设置
        video_path = "/data1/sd_webui/first_8class_video/video/晴天无太阳/20250205_03_08_1815_G895.MP4"
        video_path = "/data1/sd_webui/first_8class_video/video/镜头雨滴/20250616_03_08_123008_G6126.MP4"
        video_path = "/data/chenjuntao/OtherProj/dataManage/镜头雨滴_20250616_03_08_123008_G6126_mp4mux-fixed.MP4"
        video_path = "/data1/sd_webui/first_8class_video/video/晴天无太阳/20250610_03_08_084030_G6407.MP4"
    
    data = {
        "path": video_path,
        "train_no": "G4926",
        "route_section": "佛山西-宜宾"
    }
    
    print(f"注册视频: {video_path}")
    print(f"车次: {data['train_no']}, 区间: {data['route_section']}")
    
    try:
        response = requests.post(f"{BASE_URL}/videos/register", json=data)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                video_id = result['data']['video_id']
                print(f"\n✓ 视频注册成功，ID: {video_id}")
                return video_id
    except Exception as e:
        print(f"✗ 注册失败: {str(e)}")
    
    return None

# ============================================================================
# 测试2: 获取视频列表
# ============================================================================
def test_get_videos():
    """测试获取视频列表"""
    print_separator("测试2: 获取视频列表")
    
    try:
        response = requests.get(f"{BASE_URL}/videos")
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            videos = result.get('data', [])
            print(f"\n✓ 获取到 {len(videos)} 个视频")
            return videos
    except Exception as e:
        print(f"✗ 获取视频列表失败: {str(e)}")
    
    return []

# ============================================================================
# 测试3: 视频抽帧
# ============================================================================
def test_extract_frames(video_id):
    """测试视频抽帧"""
    print_separator(f"测试3: 抽帧视频 (ID={video_id})")
    
    data = {
        # "max_frames": 100,  # 最多抽50帧
        "sample_rate": 10,  # 每2秒抽1帧
        "async": False  # 同步执行
    }
    if "sample_rate" in data.keys():
        print(f"开始抽帧，根据采样率约每: {data['sample_rate']} 采一帧")
    else:
        print(f"开始抽帧，根据最大帧数: {data['max_frames']}")

    
    try:
        response = requests.post(f"{BASE_URL}/videos/{video_id}/extract", json=data)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                frame_count = result.get('frame_count', 0)
                print(f"\n✓ 抽帧成功，共 {frame_count} 帧")
                return True
    except Exception as e:
        print(f"✗ 抽帧失败: {str(e)}")
    
    return False

# ============================================================================
# 测试4: AI处理帧
# ============================================================================
def test_process_frames(video_id):
    """测试AI处理"""
    print_separator(f"测试4: AI处理帧 (ID={video_id})")
    
    data = {
        "batch_size": 10,
        "async": False  # 同步执行
    }
    
    print(f"开始AI处理，批次大小: {data['batch_size']}")
    
    try:
        response = requests.post(f"{BASE_URL}/videos/{video_id}/process-ai", json=data)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                processed = result.get('processed_count', 0)
                print(f"\n✓ AI处理成功，处理了 {processed} 帧")
                return True
    except Exception as e:
        print(f"✗ AI处理失败: {str(e)}")
    
    return False

# ============================================================================
# 测试5: 查询视频的所有帧
# ============================================================================
def test_get_frames_by_video(video_id):
    """测试查询视频的帧"""
    print_separator(f"测试5: 查询视频帧 (ID={video_id})")
    
    params = {
        "video_id": video_id,
        "limit": 10,
        "offset": 0
    }
    
    try:
        response = requests.get(f"{BASE_URL}/frames", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 获取到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []

# ============================================================================
# 新增测试: 按需随机访问抽帧（单帧）
# ============================================================================
def test_on_demand_frame_images(frames, out_dir: str):
    """测试通过 /frames/<id>/image 按需返回图片的准确性与速度"""
    print_separator("新增测试: 按需抽帧（单帧）")
    import time
    sample = frames[:10] if len(frames) > 10 else frames
    if not sample:
        print("没有可测试的帧")
        return False
    save_dir = os.path.join(out_dir, "single")
    os.makedirs(save_dir, exist_ok=True)
    latencies = []
    ok = 0
    for f in sample:
        fid = f["id"]
        t0 = time.time()
        resp = requests.get(f"{BASE_URL}/frames/{fid}/image", params={"quality": 85})
        dt = time.time() - t0
        latencies.append(dt)
        if resp.status_code == 200 and resp.headers.get("Content-Type","").startswith("image/"):
            # 简单准确性校验：内容非空
            if len(resp.content) > 1024:
                # 保存图片
                out_path = os.path.join(save_dir, f"frame_{fid}.jpg")
                with open(out_path, "wb") as wf:
                    wf.write(resp.content)
                ok += 1
        else:
            print(f"帧 {fid} 获取失败，status={resp.status_code}")
    if latencies:
        print(f"平均耗时: {sum(latencies)/len(latencies):.3f}s, 最大: {max(latencies):.3f}s, 成功: {ok}/{len(sample)}")
    return ok == len(sample)

# ============================================================================
# 新增测试: 批量按需抽帧（ZIP）
# ============================================================================
def test_batch_on_demand_images(frames, out_dir: str):
    """测试通过 /frames/batch-image 批量返回图片ZIP"""
    print_separator("新增测试: 批量按需抽帧（ZIP）")
    sample = frames[:20] if len(frames) > 20 else frames
    if not sample:
        print("没有可测试的帧")
        return False
    ids = [f["id"] for f in sample]
    t0 = time.time()
    resp = requests.post(f"{BASE_URL}/frames/batch-image", json={"frame_ids": ids, "quality": 85})
    dt = time.time() - t0
    if resp.status_code == 200 and resp.headers.get("Content-Type","").startswith("application/zip"):
        size = len(resp.content or b"")
        print(f"ZIP 大小: {size} 字节, 耗时: {dt:.3f}s, 帧数: {len(ids)}")
        save_dir = os.path.join(out_dir, "batch")
        os.makedirs(save_dir, exist_ok=True)
        zip_path = os.path.join(save_dir, "frames.zip")
        with open(zip_path, "wb") as wf:
            wf.write(resp.content)
        # 解压
        unzip_dir = os.path.join(save_dir, "unzipped")
        os.makedirs(unzip_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(unzip_dir)
        # 简单准确性校验：ZIP大小>每帧最小jpeg预期（粗略）
        return size > len(ids) * 800  # 粗略阈值
    else:
        print_response(resp)
        return False

# ============================================================================
# 新增测试: 条件检索 + 直接按需抽帧到目录
# ============================================================================
def test_condition_query_and_extract(out_dir: str):
    """按固定标记条件（G-TARGET / 隧道内）检索并按需抽帧保存"""
    print_separator("新增测试: 条件检索 + 直接按需抽帧")
    cond_dir = os.path.join(out_dir, "condition")
    os.makedirs(cond_dir, exist_ok=True)

    # 条件1：标记车次
    params1 = {"train_no": "G-TARGET", "limit": 20, "offset": 0}
    r1 = requests.get(f"{BASE_URL}/frames/query", params=params1)
    print_response(r1)
    frames1 = r1.json().get("data", []) if r1.status_code == 200 else []
    print(f"按车次=G-TARGET 命中: {len(frames1)}")
    save1 = os.path.join(cond_dir, "train_G-TARGET")
    os.makedirs(save1, exist_ok=True)
    for f in frames1[:10]:
        fid = f["id"]
        resp = requests.get(f"{BASE_URL}/frames/{fid}/image", params={"quality": 85})
        if resp.status_code == 200 and resp.headers.get("Content-Type","").startswith("image/"):
            with open(os.path.join(save1, f"frame_{fid}.jpg"), "wb") as wf:
                wf.write(resp.content)

    # 条件2：标记标签（位置=隧道内）
    params2 = {"location": "隧道内", "limit": 20, "offset": 0}
    r2 = requests.get(f"{BASE_URL}/frames/query", params=params2)
    print_response(r2)
    frames2 = r2.json().get("data", []) if r2.status_code == 200 else []
    print(f"按位置=隧道内 命中: {len(frames2)}")
    save2 = os.path.join(cond_dir, "location_tunnel")
    os.makedirs(save2, exist_ok=True)
    for f in frames2[:10]:
        fid = f["id"]
        resp = requests.get(f"{BASE_URL}/frames/{fid}/image", params={"quality": 85})
        if resp.status_code == 200 and resp.headers.get("Content-Type","").startswith("image/"):
            with open(os.path.join(save2, f"frame_{fid}.jpg"), "wb") as wf:
                wf.write(resp.content)

# ============================================================================
# 测试6: 按时间范围查询
# ============================================================================
def test_query_by_time_range():
    """测试按时间范围查询"""
    print_separator("测试6: 按时间范围查询")
    
    params = {
        "start_time": "2025-02-14T00:00:00",
        "end_time": "2025-02-14T23:59:59",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询时间范围: {params['start_time']} ~ {params['end_time']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []

# ============================================================================
# 测试7: 按车次查询
# ============================================================================
def test_query_by_train():
    """测试按车次查询"""
    print_separator("测试7: 按车次查询")
    
    params = {
        "train_no": "G4926",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询车次: {params['train_no']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []


# ============================================================================
# 测试8: 按区间查询
# ============================================================================
def test_query_by_route():
    """测试按区间查询"""
    print_separator("测试8: 按区间查询")
    
    params = {
        "route_section": "佛山西-宜宾",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询区间: {params['route_section']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []


# ============================================================================
# 测试9: 按标签查询（多标签）
# ============================================================================
def test_query_by_labels():
    """测试按标签查询"""
    print_separator("测试9: 按标签查询")
    
    params = {
        "weather": "晴天",
        "location": "隧道内",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询条件: 天气={params['weather']}, 位置={params['location']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []


# ============================================================================
# 测试10: OCR全文检索
# ============================================================================
def test_ocr_search():
    """测试OCR全文检索"""
    print_separator("测试10: OCR全文检索")
    
    params = {
        "keyword": "G4926",
        "limit": 20
    }
    
    print(f"搜索关键词: {params['keyword']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/search", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 搜索到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 搜索失败: {str(e)}")
    
    return []


# ============================================================================
# 测试11: 组合查询
# ============================================================================
def test_combined_query():
    """测试组合查询"""
    print_separator("测试11: 组合查询（时间+车次+标签）")
    
    params = {
        "start_time": "2025-02-14T00:00:00",
        "end_time": "2025-02-14T23:59:59",
        "train_no": "G4926",
        "weather": "晴天",
        "limit": 20,
        "offset": 0
    }
    
    print(f"查询条件:")
    print(f"  时间: {params['start_time']} ~ {params['end_time']}")
    print(f"  车次: {params['train_no']}")
    print(f"  天气: {params['weather']}")
    
    try:
        response = requests.get(f"{BASE_URL}/frames/query", params=params)
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            frames = result.get('data', [])
            count = result.get('count', 0)
            print(f"\n✓ 查询到 {count} 帧")
            return frames
    except Exception as e:
        print(f"✗ 查询失败: {str(e)}")
    
    return []


# ============================================================================
# 测试12: 获取统计信息
# ============================================================================
def test_get_stats():
    """测试获取统计信息"""
    print_separator("测试12: 获取统计信息")
    
    try:
        # 获取视频统计
        response = requests.get(f"{BASE_URL}/videos/statistics")
        print("视频统计:")
        print_response(response)
        
        if response.status_code == 200:
            result = response.json()
            stats = result.get('data', {})
            print(f"\n✓ 视频统计:")
            print(f"  总视频数: {stats.get('total_videos', 0)}")
            print(f"  总帧数: {stats.get('total_frames', 0)}")
            print(f"  已处理帧数: {stats.get('processed_frames', 0)}")
            
        # 获取帧分布统计
        print("\n\n帧分布统计:")
        response2 = requests.get(f"{BASE_URL}/frames/statistics")
        print_response(response2)
        
        return stats
    except Exception as e:
        print(f"✗ 获取统计失败: {str(e)}")
    
    return {}

# ============================================================================
# 新增测试: /videos/<id>/image-at?t=...（含 seed 修复）
# ============================================================================
def test_video_image_at(video_id, seed_video_id=None, t_list=None):
    print_separator("新增测试: /videos/<id>/image-at")
    if not t_list:
        t_list = [0.0, 1.0, 2.0, 5.0]
    out_dir = os.path.join(TEST_OUT_ROOT, "image_at", f"video_{video_id}")
    os.makedirs(out_dir, exist_ok=True)
    ok = 0
    for t in t_list:
        params = {"t": t, "quality": 85}
        if seed_video_id is not None:
            params["seed_video_id"] = seed_video_id
        resp = requests.get(f"{BASE_URL}/videos/{video_id}/image-at", params=params)
        if resp.status_code == 200 and resp.headers.get("Content-Type","").startswith("image/"):
            out_path = os.path.join(out_dir, f"t_{str(t).replace('.','_')}.jpg")
            with open(out_path, "wb") as wf:
                wf.write(resp.content)
            ok += 1
        else:
            print_response(resp)
    print(f"image-at 成功: {ok}/{len(t_list)} -> 输出目录: {out_dir}")
    return ok == len(t_list)
# ============================================================================
# 主测试流程
# ============================================================================
def run_all_tests():
    """运行所有测试"""
    print("\n" + "█"*80)
    print("█" + " "*78 + "█")
    print("█" + " "*25 + "视频管理系统 API 测试" + " "*25 + "█")
    print("█" + " "*78 + "█")
    print("█"*80)
    
    # 检查服务是否运行
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=2)
        print(f"\n✓ 服务运行正常 (Status: {response.status_code})")
    except:
        print("\n✗ 无法连接到服务，请确保后端服务已启动")
        print("  启动命令: python app.py")
        return
    
    # 执行测试
    video_id = None
    
    # 1. 上传视频
    video_path = "/data/chenjuntao/OtherProj/dataManage/test_wrong.MP4"
    video_id = test_upload_video(video_path=video_path)
    if not video_id:
        print("\n⚠ 视频上传失败，尝试获取现有视频...")
        videos = test_get_videos()
        if videos:
            video_id = videos[0]['id']
            print(f"使用现有视频 ID: {video_id}")
    
    time.sleep(1)
    
    # 2. 获取视频列表
    test_get_videos()
    time.sleep(1)
    
    if video_id:
        # 3. 视频抽帧
        if test_extract_frames(video_id):
            time.sleep(2)
            
            # 4. AI处理
            test_process_frames(video_id)
            time.sleep(2)
            
            # exit()
            # 5. 查询视频的帧
            frames = test_get_frames_by_video(video_id)
            time.sleep(1)
            if frames:
                # 新增：按需抽帧（单帧）
                run_dir = os.path.join(TEST_OUT_ROOT, time.strftime("%Y%m%d_%H%M%S"))
                os.makedirs(run_dir, exist_ok=True)
                test_on_demand_frame_images(frames, run_dir)
                time.sleep(1)
                # 新增：批量按需抽帧（ZIP）
                test_batch_on_demand_images(frames, run_dir)
                time.sleep(1)
                # 新增：条件检索 + 直接按需抽帧
                test_condition_query_and_extract(run_dir)
            time.sleep(1)

    # 针对“raw h264 伪装成 MP4”的文件，演示 /image-at 的 seed 修复能力
    # try:
    #     # 假设第2个视频是raw h264（刚刚注册），第1个是正常MP4，可作为seed
    #     videos = test_get_videos()
    #     if len(videos) >= 2:
    #         vid_raw = videos[0]['id'] if videos[0]['width'] == 0 else videos[1]['id']
    #         vid_seed = videos[1]['id'] if videos[0]['width'] == 0 else videos[0]['id']
    #         print(f"尝试对视频 {vid_raw} 使用 seed={vid_seed} 进行 image-at 抽帧")
    #         test_video_image_at(vid_raw, seed_video_id=vid_seed, t_list=[0.0, 1.0, 2.0])
    # except Exception as _:
    #     pass
    # exit()

    # 6-11. 各种查询测试
    test_query_by_time_range()
    time.sleep(1)
    
    test_query_by_train()
    time.sleep(1)
    
    test_query_by_route()
    time.sleep(1)
    
    test_query_by_labels()
    time.sleep(1)
    
    test_ocr_search()
    time.sleep(1)
    
    test_combined_query()
    time.sleep(1)
    
    # 12. 统计信息
    test_get_stats()
    
    # 测试完成
    print_separator("测试完成")
    print("\n所有测试已执行完毕！")
    print("\n提示:")
    print("  - 如果某些测试失败，请检查后端日志")
    print("  - 确保视频文件路径正确")
    print("  - 数据库文件位于: backend/data/easydata.db")
    print("\n" + "█"*80 + "\n")

# ============================================================================
# 快速测试（不需要真实视频文件）
# ============================================================================
def quick_test():
    """快速测试（仅测试查询功能）"""
    print_separator("快速测试模式")
    
    # 测试获取列表
    videos = test_get_videos()
    time.sleep(1)
    
    if videos:
        video_id = videos[0]['id']
        test_get_frames_by_video(video_id)
    
    # 测试各种查询
    test_query_by_time_range()
    test_query_by_train()
    test_query_by_labels()
    test_ocr_search()
    test_get_stats()
    
    print_separator("快速测试完成")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        quick_test()
    else:
        run_all_tests()
