from flask import Flask, jsonify
from flask_cors import CORS
import os
import sys

# 添加当前目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config, HOST, PORT
from models.database import init_db
from models.video_database import video_db
from routes.dataset import dataset_bp
from routes.annotation import annotation_bp
from routes.model import model_bp
from routes.video import video_bp
from routes.frame import frame_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # 启用CORS，允许前端跨域访问
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    # 注册蓝图
    app.register_blueprint(dataset_bp, url_prefix='/api')
    app.register_blueprint(annotation_bp, url_prefix='/api')
    app.register_blueprint(model_bp, url_prefix='/api')
    app.register_blueprint(video_bp, url_prefix='/api')
    app.register_blueprint(frame_bp, url_prefix='/api')
    
    # 健康检查接口
    @app.route('/api/health', methods=['GET'])
    def health_check():
        return jsonify({'status': 'ok', 'message': 'EasyData Demo Backend Running'})
    
    # 错误处理
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'success': False, 'message': '接口不存在'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500
    
    return app

if __name__ == '__main__':
    # 初始化数据库
    print("正在初始化数据库...")
    init_db()  # 初始化图像标注数据库
    # video_db 在模块加载时已初始化，这里无需重复初始化
    
    # 创建应用
    app = create_app()
    
    print(f"\n{'='*60}")
    print(f"EasyData Video Management Backend 启动中...")
    print(f"监听地址: {HOST}:{PORT}")
    print(f"健康检查: http://{HOST}:{PORT}/api/health")
    print(f"\n视频管理API:")
    print(f"  - 视频列表: http://{HOST}:{PORT}/api/videos")
    print(f"  - 帧查询: http://{HOST}:{PORT}/api/frames/query")
    print(f"  - 统计信息: http://{HOST}:{PORT}/api/videos/statistics")
    print(f"{'='*60}\n")
    
    # 启动服务
    app.run(host=HOST, port=PORT, 
    debug=True)